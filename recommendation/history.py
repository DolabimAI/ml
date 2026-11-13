"""E4 karar geçmişi ve eğitim örnekleri; A3 yerine geçmeyen yerel sözleşme."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .features import encode_outfit
from .filter import Outfit
from .models import ClothingItem, Weather, load_catalog


# Ortak kod listesindeki result_key -> (value, seçilen yöntem, son karar).
RESULT_STATUSES = {
    "BK": ("BEKLIYOR", None, None),
    "KS": ("KURAL_SECILDI", "kural", None),
    "OS": ("OGRENEN_SECILDI", "ogrenen", None),
    "KT": ("KURAL_TEMIZ", "kural", "temiz"),
    "KD": ("KURAL_DEGISIKLIKLE", "kural", "degisiklikle"),
    "KR": ("KURAL_RED", "kural", "red"),
    "OT": ("OGRENEN_TEMIZ", "ogrenen", "temiz"),
    "OD": ("OGRENEN_DEGISIKLIKLE", "ogrenen", "degisiklikle"),
    "OR": ("OGRENEN_RED", "ogrenen", "red"),
    "HB": ("HICBIRI", None, "hicbiri"),
    "AT": ("AYNI_TEMIZ", "ikisi", "temiz"),
    "AD": ("AYNI_DEGISIKLIKLE", "ikisi", "degisiklikle"),
    "AR": ("AYNI_RED", "ikisi", "red"),
    "TP": ("TEPKISIZ", None, None),
}
LEARNING_KEYS = frozenset(("KT", "KD", "KR", "OT", "OD", "OR", "HB"))
RULE_KEYS = frozenset(("KT", "KD", "KR"))


def main_outfit_key(outfit: Outfit) -> tuple[int, ...]:
    return tuple(sorted(i.id for i in outfit.items if i.category != "aksesuar"))


def _require_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} boş olmayan bir metin olmalı")


@dataclass(frozen=True)
class ComparisonDecision:
    user_id: str
    comparison_id: str
    result_key: str
    completed_at: datetime | None
    weather: Weather
    style: str
    rule_outfit: Outfit | None = None
    learned_outfit: Outfit | None = None
    final_outfit: Outfit | None = None

    def __post_init__(self) -> None:
        _require_id(self.user_id, "user_id")
        _require_id(self.comparison_id, "comparison_id")
        if not isinstance(self.result_key, str) or self.result_key not in RESULT_STATUSES:
            raise ValueError(f"Bilinmeyen result_key: {self.result_key}")
        if not isinstance(self.weather, Weather):
            raise ValueError("Geçmiş hava bilgisi Weather olmalı")
        if self.style not in load_catalog()["styles"]:
            raise ValueError(f"Bilinmeyen etkinlik: {self.style}")
        _, method, outcome = RESULT_STATUSES[self.result_key]
        if outcome is not None and self.completed_at is None:
            raise ValueError("Son karar için completed_at gerekli")
        if self.completed_at is not None:
            if (not isinstance(self.completed_at, datetime) or self.completed_at.tzinfo is None
                    or self.completed_at.utcoffset() is None):
                raise ValueError("completed_at saat dilimi içeren bir datetime olmalı")
        for outfit in (self.rule_outfit, self.learned_outfit, self.final_outfit):
            if outfit is not None:
                if not isinstance(outfit, Outfit):
                    raise ValueError("Geçmiş kombin bilgisi Outfit olmalı")
                encode_outfit(outfit, self.weather, self.style)
        if self.result_key not in LEARNING_KEYS:
            return
        if self.rule_outfit is None or self.learned_outfit is None:
            raise ValueError("Öğrenmeye giren kararda iki ilk kombin de gerekli")
        if outcome == "degisiklikle" and self.final_outfit is None:
            raise ValueError("Değişiklikle kabul için final_outfit gerekli")
        selected = self.rule_outfit if method == "kural" else self.learned_outfit
        if outcome == "temiz" and self.final_outfit is not None:
            if main_outfit_key(selected) != main_outfit_key(self.final_outfit):
                raise ValueError("Temiz kabulde son kombinin ana parçaları değişemez")

    @classmethod
    def from_dict(cls, data: dict) -> "ComparisonDecision":
        required = {"user_id", "comparison_id", "result_key", "completed_at", "weather", "style"}
        optional = {"rule_outfit", "learned_outfit", "final_outfit"}
        if not isinstance(data, dict) or not required <= data.keys() or data.keys() - required - optional:
            raise ValueError("Geçmiş kaydında eksik veya bilinmeyen alan var")

        def read_outfit(value) -> Outfit | None:
            if value is None:
                return None
            if (not isinstance(value, dict) or set(value) != {"template", "items"}
                    or not isinstance(value["items"], list)
                    or any(not isinstance(item, dict) for item in value["items"])):
                raise ValueError("Geçmiş kombin template ve items listesi içermeli")
            return Outfit(value["template"], tuple(ClothingItem.from_dict(i) for i in value["items"]))

        weather = data["weather"]
        if not isinstance(weather, dict) or set(weather) != {"feels_like_temp", "condition"}:
            raise ValueError("Geçmiş hava bilgisi feels_like_temp ve condition içermeli")
        completed = data["completed_at"]
        if completed is not None and not isinstance(completed, str):
            raise ValueError("JSON completed_at ISO 8601 metni veya null olmalı")
        return cls(
            user_id=data["user_id"], comparison_id=data["comparison_id"], result_key=data["result_key"],
            completed_at=datetime.fromisoformat(completed) if completed is not None else None,
            weather=Weather(**weather), style=data["style"],
            rule_outfit=read_outfit(data.get("rule_outfit")),
            learned_outfit=read_outfit(data.get("learned_outfit")),
            final_outfit=read_outfit(data.get("final_outfit")),
        )


def load_history(path: str | Path) -> tuple[ComparisonDecision, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Geçmiş JSON'u karşılaştırmaların listesi olmalı")
    return tuple(ComparisonDecision.from_dict(row) for row in data)


@dataclass(frozen=True)
class TrainingExample:
    comparison_id: str
    source_method: str
    outfit: Outfit
    features: tuple[float, ...]
    label: int


@dataclass(frozen=True)
class TrainingData:
    examples: tuple[TrainingExample, ...]
    decision_count: int
    rule_decision_count: int

    @property
    def positive_count(self) -> int:
        return sum(example.label == 1 for example in self.examples)

    @property
    def negative_count(self) -> int:
        return len(self.examples) - self.positive_count


def _decision_examples(decision: ComparisonDecision) -> list[tuple[str, Outfit, int]]:
    rule, learned = decision.rule_outfit, decision.learned_outfit
    # Doğrulanmış, öğrenmeye giren kayıtlarda ikisi de zorunludur.
    if rule is None or learned is None:
        raise ValueError("İki ilk kombin de gerekli")
    _, method, outcome = RESULT_STATUSES[decision.result_key]
    if outcome == "hicbiri":
        return [("kural", rule, 0), ("ogrenen", learned, 0)]
    selected, other = (rule, learned) if method == "kural" else (learned, rule)
    selected_method = "kural" if method == "kural" else "ogrenen"
    other_method = "ogrenen" if method == "kural" else "kural"
    if outcome == "temiz":
        return [(selected_method, selected, 1), (other_method, other, 0)]
    if outcome == "degisiklikle":
        if decision.final_outfit is None:
            raise ValueError("Değişiklikle kabul için final_outfit gerekli")
        return [(selected_method, decision.final_outfit, 1),
                (selected_method, selected, 0), (other_method, other, 0)]
    examples = [("kural", rule, 0), ("ogrenen", learned, 0)]
    if decision.final_outfit is not None and main_outfit_key(decision.final_outfit) != main_outfit_key(selected):
        examples.append((selected_method, decision.final_outfit, 0))
    return examples


def build_training_data(
    history: Iterable[ComparisonDecision], *, user_id: str, rule_learning_limit: int = 10,
) -> TrainingData:
    """Kronolojik kararları işler; iki sayaç örnek sayısından bağımsızdır."""
    _require_id(user_id, "user_id")
    if type(rule_learning_limit) is not int or rule_learning_limit < 0:
        raise ValueError("rule_learning_limit negatif olmayan tam sayı olmalı")
    ids: set[str] = set()
    completed: list[tuple[datetime, str, ComparisonDecision]] = []
    for decision in history:
        if decision.user_id != user_id:
            raise ValueError("Geçmiş başka kullanıcıya ait kayıt içeriyor")
        if decision.comparison_id in ids:
            raise ValueError("Tekrarlı comparison_id")
        ids.add(decision.comparison_id)
        if decision.result_key in LEARNING_KEYS:
            if decision.completed_at is None:
                raise ValueError("Son karar için completed_at gerekli")
            completed.append((decision.completed_at, decision.comparison_id, decision))
    completed.sort(key=lambda row: (row[0], row[1]))
    examples: list[TrainingExample] = []
    rule_count = 0
    for _, _, decision in completed:
        # 10. kural kararında önce örnekler alınır, sonra sayaç artırılır.
        allow_rule = rule_count < rule_learning_limit
        seen: set[tuple[tuple[int, ...], int]] = set()
        for method, outfit, label in _decision_examples(decision):
            if method == "kural" and not allow_rule:
                continue
            key = (main_outfit_key(outfit), label)
            if key in seen:
                continue
            seen.add(key)
            examples.append(TrainingExample(decision.comparison_id, method, outfit,
                                             encode_outfit(outfit, decision.weather, decision.style), label))
        if decision.result_key in RULE_KEYS:
            rule_count += 1
    return TrainingData(tuple(examples), len(completed), rule_count)
