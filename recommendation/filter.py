"""E1: iki yöntemin paylaşacağı aday havuzu, hava yedekleri ve tekrar engeli."""

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

from .models import ClothingItem, FilterSettings, Weather, load_catalog


@dataclass(frozen=True)
class Outfit:
    template: str
    items: tuple[ClothingItem, ...]

    @property
    def key(self) -> tuple[int, ...]:
        """Parça sırasından bağımsız kombin kimliği; dış giyim dahildir."""
        return tuple(sorted(item.id for item in self.items))


@dataclass(frozen=True)
class CandidatePool:
    candidates: tuple[Outfit, ...]
    fallback_slots: tuple[str, ...]
    candidate_space_size: int  # Tekrar engeli uygulanmadan önceki kombin sayısı.
    limit_reached: bool


def generate_candidates(
    clothes: Sequence[ClothingItem],
    weather: Weather,
    style: str,
    *,
    rejected_outfits: Iterable[Iterable[int]] = (),
    settings: FilterSettings | None = None,
    rng: random.Random | None = None,
) -> CandidatePool:
    """Aday üretir; puanlama veya kart seçimi yapmaz.

    rejected_outfits yalnız mevcut oturumun reddedilmiş ana kombinlerini içerir.
    Aksesuarlar bu ana kombinlere ve tekrar anahtarlarına dahil edilmez.
    Sıcaklık/etkinlik filtreleri hiçbir yedek tarafından gevşetilmez.
    """
    settings = settings if settings is not None else FilterSettings.load()
    rng = rng if rng is not None else random.Random()
    if style not in load_catalog()["styles"]:
        raise ValueError(f"Bilinmeyen etkinlik: {style}")
    if len({item.id for item in clothes}) != len(clothes):
        raise ValueError("Dolapta aynı parça id'si birden fazla kez bulunamaz")
    rejected = set()
    for ids in rejected_outfits:
        ids = tuple(ids)
        if any(type(i) is not int or i < 1 for i in ids) or len(ids) != len(set(ids)):
            raise ValueError("Reddedilen kombin benzersiz pozitif parça id'leri içermeli")
        rejected.add(tuple(sorted(ids)))

    slots: dict[str, list[ClothingItem]] = defaultdict(list)
    for item in clothes:
        if item.status != "onayli" or item.category == "aksesuar":
            continue
        if not item.min_temp <= weather.feels_like_temp <= item.max_temp:
            continue
        if style not in item.styles:
            continue
        slots[item.category].append(item)

    fallbacks = []

    def restrict_slot(category: str, predicate, reason: str) -> None:
        original = slots[category]
        if not original:
            return  # Önceki sıcaklık/etkinlik filtresinin elediğini geri getirme.
        preferred = [item for item in original if predicate(item)]
        if preferred:
            slots[category] = preferred
        else:
            fallbacks.append(f"{reason}:{category}")

    if weather.has_flag("is_wet"):
        restrict_slot("ayakkabi", lambda item: not item.avoid_when_wet, "islak")
        restrict_slot("dis", lambda item: item.preferred_when_wet, "islak")
    elif weather.feels_like_temp >= settings.hot_threshold_c and weather.has_flag("is_sunny"):
        restrict_slot("ayakkabi", lambda item: item.preferred_when_hot, "sicak")

    # Dış giyim yalnız sıcaklık ve etkinlikten geçen parçalardan eklenir.
    # Uygun dış giyim varsa tüm adaylara bir dış giyim eklenir; yoksa eklenmez.
    templates = []
    for name, categories in (("ust_alt", ("ust", "alt", "ayakkabi")),
                             ("tek_parca", ("tek_parca", "ayakkabi"))):
        if not all(slots[category] for category in categories):
            continue
        pools = tuple(slots[category] for category in categories)
        if slots["dis"]:
            pools += (slots["dis"],)
        templates.append((name, pools, math.prod(len(pool) for pool in pools)))

    total = sum(size for _, _, size in templates)
    if total == 0:
        return CandidatePool((), tuple(fallbacks), 0, False)

    # Tüm kartezyen çarpımı belleğe alma. Rastgele başlangıç ve total ile
    # aralarında asal adım her indeksi en fazla bir kez ziyaret eder.
    # Bu, sınıra kadar çeşitlilik sağlar; tüm alt kümeleri eşit olasılıkla örneklemez.
    start = rng.randrange(total)
    step = 1
    if total > 1:
        step = rng.randrange(1, total)
        while math.gcd(step, total) != 1:
            step = step % (total - 1) + 1

    candidates = []
    for offset in range(total):
        index = (start + offset * step) % total
        for name, pools, size in templates:
            if index >= size:
                index -= size
                continue
            selected = []
            for pool in reversed(pools):
                index, position = divmod(index, len(pool))
                selected.append(pool[position])
            outfit = Outfit(name, tuple(reversed(selected)))
            break
        else:
            raise RuntimeError("Aday indeksi hiçbir kombin şablonuyla eşleşmedi")
        if outfit.key in rejected:
            continue
        candidates.append(outfit)
        if len(candidates) == settings.candidate_limit:
            break

    return CandidatePool(tuple(candidates), tuple(fallbacks), total,
                         len(candidates) == settings.candidate_limit)
