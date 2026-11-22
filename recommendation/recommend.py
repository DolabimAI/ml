"""E7: bir karşılaştırma için iki kartı ve ortak aksesuarları üreten akış.

Uç katmanından (`router.py`) bağımsızdır; FastAPI olmadan da çağrılabilir.
E1 bir kez çalışır; E2 ve E4 aynı havuzdan seçer; E6 iki karta aynı aksesuarları ekler.
"""

import random
from dataclasses import dataclass
from typing import Iterable, Sequence

from .accessory import select_accessories
from .filter import Outfit, generate_candidates
from .history import ComparisonDecision
from .learned import select_learned_outfit
from .models import ClothingItem, Weather
from .rule_based import select_rule_outfit


@dataclass(frozen=True)
class Recommendation:
    rule_outfit: Outfit
    learned_outfit: Outfit
    is_same_outfit: bool
    learned_pick_mode: str
    accessories: tuple[ClothingItem, ...]


def recommend(
    *,
    wardrobe: Sequence[ClothingItem],
    weather: Weather,
    style: str,
    is_daytime: bool,
    wants_accessories: bool,
    rejected_outfits: Iterable[Iterable[int]],
    history: Sequence[ComparisonDecision],
    user_id: str,
    rng: random.Random,
) -> Recommendation | None:
    """İki kartı üretir; uygun kombin yoksa None döner.

    Tek `rng` sırayla E1, E2, E4 ve E6'ya verilir; aynı tohum aynı sonucu üretir.
    İki yöntem aynı ana parça kümesini seçtiyse aksesuar tek karta göre seçilir.
    """
    pool = generate_candidates(wardrobe, weather, style, rejected_outfits=rejected_outfits, rng=rng)
    if not pool.candidates:
        return None
    rule = select_rule_outfit(pool.candidates, rng=rng)
    learned = select_learned_outfit(pool.candidates, weather, style, history, user_id=user_id, rng=rng)
    if rule is None or learned is None:
        raise RuntimeError("Boş olmayan havuzdan kart seçilemedi")
    is_same = rule.outfit.key == learned.outfit.key
    cards = (rule.outfit,) if is_same else (rule.outfit, learned.outfit)
    choices = select_accessories(cards, wardrobe, weather, style, is_daytime=is_daytime,
                                 wants_accessories=wants_accessories, rng=rng)
    return Recommendation(rule.outfit, learned.outfit, is_same, learned.ogrenen_mode,
                          tuple(choice.item for choice in choices))
