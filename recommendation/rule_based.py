"""E2: ortak aday havuzundan sabit renk kurallarıyla Kural Kartı seçimi.

Puanlar kullanıcı geçmişinden öğrenilmez. Bu modülün uyum puanları ve renk
ilişkileri öğrenen yönteme özellik olarak verilmemelidir.
"""

import json
import math
import random
from dataclasses import dataclass, fields
from itertools import combinations
from pathlib import Path
from typing import Iterable

from .filter import Outfit
from .models import load_catalog


@dataclass(frozen=True)
class RuleSettings:
    neutral_colors: tuple[str, ...]
    color_wheel: tuple[str, ...]
    complementary_pairs: tuple[tuple[str, str], ...]
    high_score: float
    medium_score: float
    low_score: float
    extra_color_penalty: float

    def __post_init__(self) -> None:
        for name in ("neutral_colors", "color_wheel"):
            colors = getattr(self, name)
            if not isinstance(colors, tuple) or not all(isinstance(c, str) for c in colors):
                raise ValueError(f"{name} renk kodlarından oluşan bir tuple olmalı")
            if len(colors) != len(set(colors)):
                raise ValueError(f"{name} tekrarlı renk içeremez")
        neutrals, vivid = set(self.neutral_colors), set(self.color_wheel)
        if not neutrals or len(vivid) < 3:
            raise ValueError("Nötr renk listesi boş olamaz; çember en az üç renk içermeli")
        if neutrals & vivid:
            raise ValueError("Bir renk hem nötr hem canlı olarak tanımlanamaz")
        if neutrals | vivid != set(load_catalog()["colors"]):
            raise ValueError("Renk grupları katalogdaki bütün renkleri tam olarak kapsamalı")

        if not isinstance(self.complementary_pairs, tuple):
            raise ValueError("complementary_pairs tuple olmalı")
        seen = set()
        for pair in self.complementary_pairs:
            if (not isinstance(pair, tuple) or len(pair) != 2
                    or not all(isinstance(c, str) for c in pair)):
                raise ValueError("Her karşıt çift iki renk kodu içermeli")
            if pair[0] == pair[1] or not set(pair) <= vivid:
                raise ValueError("Karşıt çiftler iki farklı canlı renkten oluşmalı")
            key = frozenset(pair)
            if key in seen:
                raise ValueError("Karşıt çiftler yönünden bağımsız olarak benzersiz olmalı")
            seen.add(key)
            distance = abs(self.color_wheel.index(pair[0]) - self.color_wheel.index(pair[1]))
            if distance in (1, len(self.color_wheel) - 1):
                raise ValueError("Bir renk çifti hem komşu hem karşıt olamaz")

        for name in ("high_score", "medium_score", "low_score", "extra_color_penalty"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} sonlu bir sayı olmalı")
        if not 0 <= self.low_score < self.medium_score < self.high_score:
            raise ValueError("Puanlar 0 <= düşük < orta < yüksek sırasını sağlamalı")
        if self.extra_color_penalty < 0:
            raise ValueError("Canlı renk cezası negatif olamaz")

    @classmethod
    def load(cls, path: str | Path | None = None) -> "RuleSettings":
        source = Path(path) if path is not None else Path(__file__).with_name("rule_settings.json")
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {field.name for field in fields(cls)}:
            raise ValueError("Kural ayarlarında eksik veya bilinmeyen alan var")
        for name in ("neutral_colors", "color_wheel", "complementary_pairs"):
            if not isinstance(data[name], list):
                raise ValueError(f"JSON {name} alanı liste olmalı")
        if any(not isinstance(pair, list) for pair in data["complementary_pairs"]):
            raise ValueError("JSON karşıt renk çiftleri liste olmalı")
        return cls(
            **{**data, "neutral_colors": tuple(data["neutral_colors"]),
               "color_wheel": tuple(data["color_wheel"]),
               "complementary_pairs": tuple(tuple(pair) for pair in data["complementary_pairs"])},
        )


@dataclass(frozen=True)
class RuleScore:
    pair_average: float
    vivid_color_count: int
    penalty: float
    total: float


@dataclass(frozen=True)
class RuleSelection:
    outfit: Outfit
    score: RuleScore
    tied_best_count: int


def score_pair(color_a: str, color_b: str, settings: RuleSettings | None = None) -> float:
    """İki ana rengin simetrik puanı; ton veya desen için ek ağırlık yoktur."""
    settings = settings if settings is not None else RuleSettings.load()
    known_colors = settings.neutral_colors + settings.color_wheel
    for color in (color_a, color_b):
        if color not in known_colors:
            raise ValueError(f"Bilinmeyen renk: {color}")
    if color_a in settings.neutral_colors or color_b in settings.neutral_colors:
        return settings.high_score
    if color_a == color_b:
        return settings.high_score
    distance = abs(settings.color_wheel.index(color_a) - settings.color_wheel.index(color_b))
    if distance in (1, len(settings.color_wheel) - 1):
        return settings.high_score
    if (color_a, color_b) in settings.complementary_pairs or (color_b, color_a) in settings.complementary_pairs:
        return settings.medium_score
    return settings.low_score


def score_outfit(outfit: Outfit, settings: RuleSettings | None = None) -> RuleScore:
    """Dış giyim dahil bütün ana parça çiftlerini puanlar; aksesuarları dışarıda tutar."""
    settings = settings if settings is not None else RuleSettings.load()
    items = tuple(item for item in outfit.items if item.category != "aksesuar")
    if len(items) < 2:
        raise ValueError("Kombin puanlamak için en az iki ana parça gerekli")
    if len({item.id for item in items}) != len(items):
        raise ValueError("Kombin aynı ana parçayı birden fazla kez içeremez")
    pair_scores = [score_pair(a.color, b.color, settings) for a, b in combinations(items, 2)]
    average = math.fsum(pair_scores) / len(pair_scores)
    vivid_count = len({item.color for item in items if item.color not in settings.neutral_colors})
    penalty = settings.extra_color_penalty * max(0, vivid_count - 2)
    return RuleScore(average, vivid_count, penalty, max(0.0, average - penalty))


def select_rule_outfit(
    candidates: Iterable[Outfit],
    *,
    settings: RuleSettings | None = None,
    rng: random.Random | None = None,
) -> RuleSelection | None:
    """Verilen havuzun en yüksek puanlı adayını seçer; boş havuzda None döner.

    E1'i yeniden çalıştırmaz. Eşit en yüksek puanlı adaylar arasında eşit olasılıkla
    seçim yapılır. Sıralamada yuvarlanmamış puan kullanılır.
    """
    settings = settings if settings is not None else RuleSettings.load()
    scored = [(outfit, score_outfit(outfit, settings)) for outfit in candidates]
    if not scored:
        return None
    highest = max(score.total for _, score in scored)
    best = [(outfit, score) for outfit, score in scored if score.total == highest]
    rng = rng if rng is not None else random.Random()
    outfit, score = rng.choice(best)
    return RuleSelection(outfit, score, len(best))
