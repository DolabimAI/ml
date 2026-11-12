"""E3: kombin ve bağlam için konuma göre ayrılmış, sabit sayısal özellikler.

Eğitim verisinden sütun öğrenilmez; geçmiş ve yeni adaylar aynı şemayı kullanır.
Renk uyum kuralları, puanlar ve karar etiketleri bu modülün girdisi değildir.
"""

from typing import Iterable

from .filter import Outfit
from .models import ClothingItem, Weather, load_catalog


FEATURE_SCHEMA_VERSION = "e3_v1"
_SLOTS = ("ust", "alt", "tek_parca", "dis", "ayakkabi")
# Belgedeki canlı renk sayımı için bağımsız tanım; E2 ayarları okunmaz.
_NEUTRAL_COLORS = frozenset(("siyah", "beyaz", "gri", "bej", "lacivert", "kahverengi"))
_COLORS = tuple(sorted(load_catalog()["colors"]))
_TONES = tuple(sorted(load_catalog()["tones"]))
_STYLES = tuple(sorted(load_catalog()["styles"]))
_SUBTYPES = {
    slot: tuple(sorted(s["value"] for s in load_catalog()["subtypes"] if s["category"] == slot))
    for slot in _SLOTS
}
_TEMPLATES = {
    "ust_alt": frozenset(("ust", "alt", "ayakkabi")),
    "tek_parca": frozenset(("tek_parca", "ayakkabi")),
}


def feature_names() -> tuple[str, ...]:
    """Vektörle aynı sıradaki sütunlar; mevcut katalogda 126 sütun vardır.

    Katalog kodları değiştiğinde şema sürümü ve şema testleri birlikte güncellenmeli.
    Katalogdaki satır sırasının değişmesi sütun sırasını değiştirmez.
    """
    names = []
    for slot in _SLOTS:
        names.append(f"{slot}.present")
        names.extend(f"{slot}.subtype={code}" for code in _SUBTYPES[slot])
        names.extend(f"{slot}.color={code}" for code in _COLORS)
        names.extend(f"{slot}.tone={code}" for code in _TONES)
        names.append(f"{slot}.is_patterned")
    names.extend(f"context.style={code}" for code in _STYLES)
    names.extend(("context.feels_like_temp", "outfit.vivid_color_count"))
    return tuple(names)


def _validate_style(style: str) -> None:
    if style not in _STYLES:
        raise ValueError(f"Bilinmeyen etkinlik: {style}")


def _main_items(outfit: Outfit) -> dict[str, ClothingItem]:
    if outfit.template not in _TEMPLATES:
        raise ValueError(f"Bilinmeyen kombin şablonu: {outfit.template}")
    slots: dict[str, ClothingItem] = {}
    ids: set[int] = set()
    for item in outfit.items:
        if item.category == "aksesuar":
            continue
        if item.id in ids:
            raise ValueError("Kombin aynı ana parça kimliğini birden fazla kez içeremez")
        if item.category not in _SLOTS:
            raise ValueError(f"Bilinmeyen ana parça konumu: {item.category}")
        if item.category in slots:
            raise ValueError(f"Bir konumda birden fazla ana parça olamaz: {item.category}")
        ids.add(item.id)
        slots[item.category] = item
    required = _TEMPLATES[outfit.template]
    if not required <= slots.keys():
        missing = ", ".join(sorted(required - slots.keys()))
        raise ValueError(f"Kombinde zorunlu konum eksik: {missing}")
    if slots.keys() - (required | {"dis"}):
        raise ValueError("Kombin şablonuna ait olmayan ana parça var")
    return slots


def encode_outfit(outfit: Outfit, weather: Weather, style: str) -> tuple[float, ...]:
    """Bir kombini kodlar; uygunluk filtresi veya model eğitimi uygulamaz."""
    _validate_style(style)
    slots = _main_items(outfit)
    values: list[float] = []
    for slot in _SLOTS:
        item = slots.get(slot)
        if item is None:
            width = 1 + len(_SUBTYPES[slot]) + len(_COLORS) + len(_TONES) + 1
            values.extend([0.0] * width)
            continue
        values.append(1.0)
        values.extend(float(item.subtype == code) for code in _SUBTYPES[slot])
        values.extend(float(item.color == code) for code in _COLORS)
        values.extend(float(item.tone == code) for code in _TONES)
        values.append(float(item.is_patterned))
    values.extend(float(style == code) for code in _STYLES)
    values.append(float(weather.feels_like_temp))
    values.append(float(len({i.color for i in slots.values() if i.color not in _NEUTRAL_COLORS})))
    return tuple(values)


def encode_outfits(
    candidates: Iterable[Outfit], weather: Weather, style: str,
) -> tuple[tuple[float, ...], ...]:
    """Aday sırasını korur; boş havuzda boş tuple döndürür."""
    _validate_style(style)
    return tuple(encode_outfit(outfit, weather, style) for outfit in candidates)
