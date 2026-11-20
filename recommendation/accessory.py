"""E6: iki karta aynı aksesuarları ekleyen ortak kural.

Kural iki yöntemden bağımsızdır ve kullanıcı tepkilerinden öğrenmez. E7 iki kart için
`select_accessories`'i bir kez çağırır; E5 aksesuar değiştirmede (`ortak_kural`) aynı
`accessory_candidates` ve `rank_accessories` fonksiyonlarını seçilen kombinin o anki
hâliyle tek kart olarak kullanır. Aksesuar seçimi öğrenme örneği üretmez.
"""

import json
import math
import random
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Sequence

from .filter import Outfit
from .models import ClothingItem, Weather, load_catalog
from .rule_based import RuleSettings, score_pair

# Karşılaştırma parçası önceliği: dış giyim, yoksa üst giyim, tek parça şablonunda tek parça.
REFERENCE_CATEGORIES = ("dis", "ust", "tek_parca")


def _accessory_subtypes() -> tuple[str, ...]:
    return tuple(s["value"] for s in load_catalog()["subtypes"] if s["category"] == "aksesuar")


def _require_number(value, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} sonlu bir sayı olmalı")


def _require_subtypes(values, name: str) -> None:
    known = _accessory_subtypes()
    if not isinstance(values, tuple) or not values or not all(isinstance(v, str) for v in values):
        raise ValueError(f"{name} aksesuar alt türlerinden oluşan boş olmayan bir tuple olmalı")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} tekrarlı alt tür içeremez")
    unknown = [v for v in values if v not in known]
    if unknown:
        raise ValueError(f"{name} içinde aksesuar olmayan alt tür: {', '.join(unknown)}")


@dataclass(frozen=True)
class AccessorySettings:
    cold_below_c: float
    cold_subtypes: tuple[str, ...]
    warm_above_c: float
    warm_subtypes: tuple[str, ...]
    allowed_by_style: dict[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        _require_number(self.cold_below_c, "cold_below_c")
        _require_number(self.warm_above_c, "warm_above_c")
        if self.cold_below_c > self.warm_above_c:
            raise ValueError("Soğuk eşiği sıcak eşiğinden büyük olamaz; iki grup aynı anda çalışmamalı")
        _require_subtypes(self.cold_subtypes, "cold_subtypes")
        _require_subtypes(self.warm_subtypes, "warm_subtypes")
        if set(self.cold_subtypes) & set(self.warm_subtypes):
            raise ValueError("Bir aksesuar hem soğuk hem sıcak grubunda olamaz")
        if not isinstance(self.allowed_by_style, dict) or set(self.allowed_by_style) != set(
                load_catalog()["styles"]):
            raise ValueError("allowed_by_style katalogdaki bütün etkinlikleri tam olarak içermeli")
        for style, allowed in self.allowed_by_style.items():
            if allowed:
                _require_subtypes(allowed, f"allowed_by_style.{style}")
            elif allowed != ():
                raise ValueError(f"allowed_by_style.{style} tuple olmalı")

    @classmethod
    def load(cls, path: str | Path | None = None) -> "AccessorySettings":
        source = Path(path) if path is not None else Path(__file__).with_name("accessory_settings.json")
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {field.name for field in fields(cls)}:
            raise ValueError("Aksesuar ayarlarında eksik veya bilinmeyen alan var")
        for name in ("cold_subtypes", "warm_subtypes"):
            if not isinstance(data[name], list):
                raise ValueError(f"JSON {name} alanı liste olmalı")
        table = data["allowed_by_style"]
        if not isinstance(table, dict) or any(not isinstance(v, list) for v in table.values()):
            raise ValueError("JSON allowed_by_style etkinlikten alt tür listesine bir nesne olmalı")
        return cls(**{**data, "cold_subtypes": tuple(data["cold_subtypes"]),
                      "warm_subtypes": tuple(data["warm_subtypes"]),
                      "allowed_by_style": {style: tuple(v) for style, v in table.items()}})


@dataclass(frozen=True)
class AccessoryScore:
    item: ClothingItem
    average_score: float  # Kartların referans parçasıyla E2 çift puanlarının ortalaması.


@dataclass(frozen=True)
class AccessoryChoice:
    item: ClothingItem
    average_score: float
    tied_best_count: int


def accessory_candidates(
    wardrobe: Sequence[ClothingItem],
    weather: Weather,
    style: str,
    *,
    is_daytime: bool,
    wants_accessories: bool,
    settings: AccessorySettings | None = None,
) -> dict[str, tuple[ClothingItem, ...]]:
    """Kuralın aday adımlarını uygular; alt tür → onaylı parçalar (id sırasıyla).

    Sıra: istenmediyse hiçbiri → hissedilen sıcaklık → gündüz ve güneş (şapka, gözlük)
    → etkinlik izin tablosu → gardıropta olma. Parçanın kendi `styles` alanı
    kullanılmaz; izin tablosu ayar dosyasındadır. Sözlük ayar dosyasındaki grup
    sırasını izler.
    """
    settings = settings if settings is not None else AccessorySettings.load()
    if type(is_daytime) is not bool or type(wants_accessories) is not bool:
        raise ValueError("is_daytime ve wants_accessories boolean olmalı")
    if style not in settings.allowed_by_style:
        raise ValueError(f"Bilinmeyen etkinlik: {style}")
    if len({item.id for item in wardrobe}) != len(wardrobe):
        raise ValueError("Dolapta aynı parça id'si birden fazla kez bulunamaz")
    if not wants_accessories:
        return {}

    temperature = weather.feels_like_temp
    if temperature < settings.cold_below_c:
        subtypes = settings.cold_subtypes
    elif temperature > settings.warm_above_c and is_daytime and weather.has_flag("is_sunny"):
        subtypes = settings.warm_subtypes
    else:
        return {}

    allowed = set(settings.allowed_by_style[style])
    result = {}
    for subtype in subtypes:
        if subtype not in allowed:
            continue
        items = sorted((item for item in wardrobe if item.category == "aksesuar"
                        and item.subtype == subtype and item.status == "onayli"),
                       key=lambda item: item.id)
        if items:
            result[subtype] = tuple(items)
    return result


def _reference_item(outfit: Outfit) -> ClothingItem:
    for category in REFERENCE_CATEGORIES:
        item = next((item for item in outfit.items if item.category == category), None)
        if item is not None:
            return item
    raise ValueError("Kartta karşılaştırılacak dış giyim, üst giyim veya tek parça yok")


def rank_accessories(
    candidates: Sequence[ClothingItem],
    cards: Sequence[Outfit],
    *,
    rule_settings: RuleSettings | None = None,
    rng: random.Random | None = None,
) -> tuple[AccessoryScore, ...]:
    """Adayları kartların referans parçasıyla ortalama E2 çift puanına göre sıralar.

    Bir ya da iki kart verilir: tek kartta yalnız o kart, iki kartta iki kartın
    ortalaması. Eşit puanlıların sırası verilen `rng` ile rastgeledir; kart sırası
    sonucu değiştirmez.
    """
    rule_settings = rule_settings if rule_settings is not None else RuleSettings.load()
    rng = rng if rng is not None else random.Random()
    if not 1 <= len(cards) <= 2:
        raise ValueError("Aksesuar seçimi için bir ya da iki kart verilmeli")
    if any(item.category != "aksesuar" for item in candidates):
        raise ValueError("Sıralanacak adaylar yalnız aksesuar olmalı")
    references = [_reference_item(card) for card in cards]
    scored = [AccessoryScore(item, math.fsum(score_pair(item.color, ref.color, rule_settings)
                                             for ref in references) / len(references))
              for item in sorted(candidates, key=lambda item: item.id)]
    rng.shuffle(scored)
    scored.sort(key=lambda score: score.average_score, reverse=True)
    return tuple(scored)


def select_accessories(
    cards: Sequence[Outfit],
    wardrobe: Sequence[ClothingItem],
    weather: Weather,
    style: str,
    *,
    is_daytime: bool,
    wants_accessories: bool,
    settings: AccessorySettings | None = None,
    rule_settings: RuleSettings | None = None,
    rng: random.Random | None = None,
) -> tuple[AccessoryChoice, ...]:
    """İki karta birlikte eklenecek aksesuarları seçer; her alt türden en fazla bir parça.

    `cards` E1'in ortak havuzundan seçilen kural ve öğrenen kombinleridir; iki yöntem
    aynı kombini seçtiyse tek kart verilir.
    """
    if not 1 <= len(cards) <= 2:
        raise ValueError("Aksesuar seçimi için bir ya da iki kart verilmeli")
    for card in cards:
        _reference_item(card)
    rule_settings = rule_settings if rule_settings is not None else RuleSettings.load()
    rng = rng if rng is not None else random.Random()
    candidates = accessory_candidates(wardrobe, weather, style, is_daytime=is_daytime,
                                      wants_accessories=wants_accessories, settings=settings)
    choices = []
    for items in candidates.values():
        ranked = rank_accessories(items, cards, rule_settings=rule_settings, rng=rng)
        best = ranked[0]
        tied = sum(1 for score in ranked if score.average_score == best.average_score)
        choices.append(AccessoryChoice(best.item, best.average_score, tied))
    return tuple(choices)
