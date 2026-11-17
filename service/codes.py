"""Ortak kod listesi. Tek kaynak shared/codes.json dosyasıdır.

Alt tür, renk ve ton kodları C# ve öneri modülüyle harfi harfine aynı olmalıdır.
Görüntü ve öneri modülleri kodları bu dosyadan okur, kendi içlerinde yeniden yazmaz.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CODES_PATH = Path(__file__).resolve().parent.parent / "shared" / "codes.json"


@lru_cache(maxsize=1)
def load_codes() -> dict:
    with CODES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def subtype_values() -> tuple[str, ...]:
    return tuple(s["value"] for s in load_codes()["subtypes"])


def subtype_category(value: str) -> str:
    for s in load_codes()["subtypes"]:
        if s["value"] == value:
            return s["category"]
    raise KeyError(value)


def color_values() -> tuple[str, ...]:
    return tuple(c["value"] for c in load_codes()["colors"])


def tone_values() -> tuple[str, ...]:
    return tuple(load_codes()["tones"])
