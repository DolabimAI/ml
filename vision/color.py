"""D6: kıyafetin baskın rengi, tonu ve deseni.

Girdi, kıyafet maskesinden gelen piksellerdir (N x 3, RGB). Yöntem planla aynıdır:
1. Pikseller k-means ile 3 gruba ayrılır; en kalabalık grubun ortalaması baskın renktir.
2. Baskın renk HSV'ye çevrilir (renk tonu 0-360°, doygunluk %, parlaklık %).
3. Önce nötr renkler denenir (beyaz, siyah, gri, lacivert, bej, kahverengi), sonra renk tonundan okunur.
4. Ton (acik / orta / koyu) parlaklık ve doygunluktan gelir.
5. İkinci grup piksellerin %30'undan fazlasıysa ve rengi farklıysa desenli işaretlenir.

Bütün eşikler vision/color_settings.json dosyasındadır; kodda sabit sayı yoktur.
Dönen renk ve ton kodları shared/codes.json ile aynıdır.
"""
from __future__ import annotations

import colorsys
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans

from service import codes

SETTINGS_PATH = Path(__file__).resolve().parent / "color_settings.json"


def load_color_settings(path: Path = SETTINGS_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@dataclass(frozen=True)
class ColorResult:
    color: str          # colors kodu, ör. "mavi"
    tone: str           # tones kodu: acik / orta / koyu
    is_patterned: bool
    hex: str            # baskın rengin ham kodu, ör. "#A2C0E2"
    hue: float          # 0-360
    saturation: float   # %
    value: float        # %


def rgb_to_hsv(r: float, g: float, b: float) -> tuple[float, float, float]:
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return h * 360, s * 100, v * 100


def _in_range(h: float, lo: float, hi: float) -> bool:
    """Alt sınır dahil, üst sınır hariç; 345-15 gibi sarmalı aralıkları da destekler."""
    if lo <= hi:
        return lo <= h < hi
    return h >= lo or h < hi


def classify_color(h: float, s: float, v: float, settings: dict) -> str:
    """HSV değerinden renk kodu. Nötr renkler yukarıdan aşağı denenir, ilk tutan kazanır."""
    n = settings
    if s < n["neutral_saturation_max"]:
        if v > n["white_value_min"]:
            return "beyaz"
        if v < n["black_value_max"]:
            return "siyah"
        return "gri"
    nv = n["navy"]
    if _in_range(h, nv["hue_min"], nv["hue_max"]) and v < nv["value_max"]:
        return "lacivert"
    bg = n["beige"]
    if _in_range(h, bg["hue_min"], bg["hue_max"]) and s < bg["saturation_max"] and v >= bg["value_min"]:
        return "bej"
    br = n["brown"]
    if _in_range(h, br["hue_min"], br["hue_max"]) and v < br["value_max"]:
        return "kahverengi"
    for r in n["hue_ranges"]:
        if _in_range(h, r["from"], r["to"]):
            return r["color"]
    raise ValueError(f"renk tonu hiçbir aralığa düşmedi: {h}")


def classify_tone(s: float, v: float, settings: dict) -> str:
    t = settings["tone"]
    if v < t["dark_value_max"]:
        return "koyu"
    if v >= t["light_value_min"] and s < t["light_saturation_max"]:
        return "acik"
    return "orta"


def _hex(rgb: np.ndarray) -> str:
    r, g, b = (int(round(float(x))) for x in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def extract_color(pixels: np.ndarray, settings: dict | None = None) -> ColorResult:
    """Maskelenmiş piksellerden (N x 3, RGB 0-255) renk sonucu üretir."""
    settings = settings or load_color_settings()
    pixels = np.asarray(pixels, dtype=float).reshape(-1, 3)
    if len(pixels) == 0:
        raise ValueError("kıyafet pikseli yok")

    k = settings["kmeans"]
    unique = len(np.unique(pixels, axis=0))
    clusters = max(1, min(k["clusters"], unique))
    km = KMeans(n_clusters=clusters, random_state=k["random_state"], n_init=k["n_init"]).fit(pixels)
    counts = np.bincount(km.labels_, minlength=clusters)
    order = np.argsort(-counts, kind="stable")

    dominant = km.cluster_centers_[order[0]]
    h, s, v = rgb_to_hsv(*dominant)
    color = classify_color(h, s, v, settings)
    tone = classify_tone(s, v, settings)

    patterned = False
    if clusters > 1:
        second = order[1]
        if counts[second] / len(pixels) > settings["pattern_second_group_share"]:
            h2, s2, v2 = rgb_to_hsv(*km.cluster_centers_[second])
            patterned = classify_color(h2, s2, v2, settings) != color

    assert color in codes.color_values() and tone in codes.tone_values()
    return ColorResult(color, tone, patterned, _hex(dominant), round(h, 1), round(s, 1), round(v, 1))
