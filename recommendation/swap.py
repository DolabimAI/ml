"""E5: seçilen kombinde tek bir parçayı ya da aksesuarı kartın yöntemiyle değiştiren akış.

Uç katmanından (`router.py`) bağımsızdır. Üç yöntem:

- `kural`: hedef yere gelebilecek her parça kombinin kalan parçalarıyla E2 puanına göre
  değerlendirilir; en yüksek puanlı seçilir.
- `ogrenen`: aynı E4 modeli kullanıcının geçmişiyle bu çağrıda eğitilir; o yer için en yüksek
  olasılıklı parça seçilir. Seçilen yorum: değiştirmede keşif yok (aşağıda).
- `ortak_kural`: E6'nın aday ve sıralama fonksiyonları kombinin o anki hâliyle tek kart olarak
  çalışır; aynı alt türden sıradaki en uyumlu aksesuar seçilir.

Ortak ön filtre (E1'in `filter_slots`) geçerlidir. Dışlanan parçalar ve şu anki parça filtreden
sonra çıkarılır; tekrar engeli gibi yedek kuralı tetiklemez.
"""

import dataclasses
import random
from typing import Collection, Sequence

from .accessory import accessory_candidates, rank_accessories
from .filter import Outfit, filter_slots
from .history import ComparisonDecision
from .learned import LearnedSettings, select_learned_outfit
from .models import ClothingItem, FilterSettings, Weather
from .rule_based import select_rule_outfit

METHODS = ("kural", "ogrenen", "ortak_kural")


def swap(
    *,
    method: str,
    wardrobe: Sequence[ClothingItem],
    weather: Weather,
    style: str,
    is_daytime: bool,
    wants_accessories: bool,
    outfit: Outfit,
    accessories: Sequence[ClothingItem],
    target_category: str | None,
    target_accessory_id: int | None,
    excluded_item_ids: Collection[int],
    history: Sequence[ComparisonDecision],
    user_id: str,
    rng: random.Random,
) -> ClothingItem | None:
    """Önerilen tek yeni parçayı döner; uygun parça yoksa None (`no_alternative`)."""
    if method not in METHODS:
        raise ValueError(f"Bilinmeyen yöntem: {method}")
    if method == "ortak_kural":
        target = next((item for item in accessories if item.id == target_accessory_id), None)
        if target is None:
            raise ValueError("Değişecek aksesuar kombinde yok")
        return _swap_accessory(target, wardrobe, weather, style, outfit, accessories, excluded_item_ids,
                               is_daytime=is_daytime, wants_accessories=wants_accessories, rng=rng)

    target = next((item for item in outfit.items if item.category == target_category), None)
    if target is None:
        raise ValueError("Değişecek kategori kombinde yok")
    blocked = set(excluded_item_ids) | {item.id for item in outfit.items}
    slots, _ = filter_slots(wardrobe, weather, style, FilterSettings.load())
    replacements = [item for item in slots[target_category] if item.id not in blocked]
    if not replacements:
        return None
    candidates = [Outfit(outfit.template,
                         tuple(new if item.id == target.id else item for item in outfit.items))
                  for new in replacements]

    if method == "kural":
        chosen = select_rule_outfit(candidates, rng=rng).outfit
    else:
        # Seçilen yorum: keşif yalnız iki kartın üretildiği /recommend'de. Değiştirmenin seçilme
        # biçimi kaydedilmediği için burada rastgele seçim analizde ayırt edilemezdi.
        settings = dataclasses.replace(LearnedSettings.load(), exploration_rate=0.0)
        chosen = select_learned_outfit(candidates, weather, style, history, user_id=user_id,
                                       settings=settings, rng=rng).outfit
    return next(item for item in chosen.items if item.category == target_category)


def _swap_accessory(
    target: ClothingItem,
    wardrobe: Sequence[ClothingItem],
    weather: Weather,
    style: str,
    outfit: Outfit,
    accessories: Sequence[ClothingItem],
    excluded_item_ids: Collection[int],
    *,
    is_daytime: bool,
    wants_accessories: bool,
    rng: random.Random,
) -> ClothingItem | None:
    groups = accessory_candidates(wardrobe, weather, style, is_daytime=is_daytime,
                                  wants_accessories=wants_accessories)
    blocked = set(excluded_item_ids) | {item.id for item in accessories}
    candidates = [item for item in groups.get(target.subtype, ()) if item.id not in blocked]
    if not candidates:
        return None
    return rank_accessories(candidates, (outfit,), rng=rng)[0].item
