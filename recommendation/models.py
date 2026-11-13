"""Yerel test veri modeli; A3 C#–Python sözleşmesi henüz kesinleşmedi."""

import json
import math
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    path = Path(__file__).parent / "catalog.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _require_temperature(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} sonlu bir sayı olmalı")


@dataclass(frozen=True)
class ClothingItem:
    id: int
    subtype: str
    category: str
    color: str
    tone: str
    is_patterned: bool
    styles: tuple[str, ...]
    min_temp: float
    max_temp: float
    avoid_when_wet: bool
    preferred_when_wet: bool
    preferred_when_hot: bool
    status: str

    def __post_init__(self) -> None:
        catalog = load_catalog()
        if type(self.id) is not int or self.id < 1:
            raise ValueError("Parça id'si pozitif bir tam sayı olmalı")
        subtype = next((s for s in catalog["subtypes"] if s["value"] == self.subtype), None)
        if subtype is None:
            raise ValueError(f"Bilinmeyen alt tür: {self.subtype}")
        if self.category != subtype["category"]:
            raise ValueError(f"{self.subtype} için kategori {subtype['category']} olmalı")
        for value, name in ((self.color, "colors"), (self.tone, "tones"), (self.status, "statuses")):
            if value not in catalog[name]:
                raise ValueError(f"Bilinmeyen {name} değeri: {value}")
        if not isinstance(self.styles, tuple) or not self.styles:
            raise ValueError("styles boş olmayan bir tuple olmalı")
        if any(s not in catalog["styles"] for s in self.styles):
            raise ValueError(f"Bilinmeyen tarz: {self.styles}")
        _require_temperature(self.min_temp, "min_temp")
        _require_temperature(self.max_temp, "max_temp")
        if self.min_temp > self.max_temp:
            raise ValueError("min_temp, max_temp değerinden büyük olamaz")
        for name in ("is_patterned", "avoid_when_wet", "preferred_when_wet", "preferred_when_hot"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} boolean olmalı")
        if self.avoid_when_wet and self.preferred_when_wet:
            raise ValueError("Bir parça ıslakta hem kaçınılan hem tercih edilen olamaz")

    @classmethod
    def from_dict(cls, data: dict) -> "ClothingItem":
        required = {field.name for field in fields(cls)}
        missing = required - data.keys()
        if missing:
            raise ValueError(f"Eksik parça alanları: {', '.join(sorted(missing))}")
        if not isinstance(data["styles"], list):
            raise ValueError("JSON styles alanı liste olmalı")
        values = {name: data[name] for name in required}
        values["styles"] = tuple(values["styles"])
        return cls(**values)


def load_wardrobe(path: str | Path) -> tuple[ClothingItem, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError("Dolap, parça nesnelerinin listesi olmalı")
    return tuple(ClothingItem.from_dict(item) for item in data)


@dataclass(frozen=True)
class Weather:
    feels_like_temp: float
    condition: str

    def __post_init__(self) -> None:
        _require_temperature(self.feels_like_temp, "feels_like_temp")
        if self.condition not in {w["value"] for w in load_catalog()["weather_conditions"]}:
            raise ValueError(f"Bilinmeyen hava durumu: {self.condition}")

    def has_flag(self, flag: str) -> bool:
        row = next(w for w in load_catalog()["weather_conditions"] if w["value"] == self.condition)
        return row[flag]


@dataclass(frozen=True)
class FilterSettings:
    hot_threshold_c: float
    candidate_limit: int

    def __post_init__(self) -> None:
        _require_temperature(self.hot_threshold_c, "hot_threshold_c")
        if type(self.candidate_limit) is not int or self.candidate_limit < 1:
            raise ValueError("candidate_limit pozitif bir tam sayı olmalı")

    @classmethod
    def load(cls) -> "FilterSettings":
        path = Path(__file__).parent / "settings.json"
        return cls(**json.loads(path.read_text(encoding="utf-8")))
