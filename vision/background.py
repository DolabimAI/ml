"""D2: arka plan temizleme, küçültme ve kıyafet maskesi.

Orijinal fotoğraf hiçbir yere yazılmaz; yalnızca bellekte işlenir.
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

SETTINGS_PATH = Path(__file__).resolve().parent / "image_settings.json"
_session = None


def load_image_settings(path: Path = SETTINGS_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


class ImageError(ValueError):
    """Görsel açılamadı ya da içinde kıyafet bulunamadı."""


def open_image(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # telefon fotoğraflarının yönü
        return img.convert("RGB")
    except Exception as exc:  # bozuk ya da desteklenmeyen dosya
        raise ImageError("görsel açılamadı") from exc


def remove_background(img: Image.Image, settings: dict | None = None) -> Image.Image:
    """Arka planı saydamlaştırır (RGBA döner). Model ilk çağrıda bir kez yüklenir."""
    global _session
    from rembg import new_session, remove  # ağır bağımlılık, yalnızca gerektiğinde içe aktarılır

    settings = settings or load_image_settings()
    if _session is None:
        _session = new_session(settings["background_model"])
    return remove(img, session=_session).convert("RGBA")


def shrink_to_webp(rgba: Image.Image, settings: dict | None = None) -> tuple[bytes, tuple[int, int]]:
    """Önce uzun kenarı küçültür, sonra boyut hedefin altına inene kadar kaliteyi, gerekirse
    ölçüyü düşürür. Saydam zemin korunur. (webp baytları, (genişlik, yükseklik)) döner."""
    s = settings or load_image_settings()
    side = s["max_side_px"]
    while True:
        img = rgba.copy()
        img.thumbnail((side, side), Image.LANCZOS)
        quality = s["webp_quality"]
        while True:
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=quality, method=6)
            data = buf.getvalue()
            if len(data) <= s["target_max_bytes"]:
                return data, img.size
            if quality - s["webp_quality_step"] < s["webp_min_quality"]:
                break
            quality -= s["webp_quality_step"]
        if side <= s["min_side_px"]:
            raise ImageError("görsel hedef boyuta indirilemedi")
        side = max(s["min_side_px"], int(side * 0.85))


def clothing_pixels(rgba: Image.Image, settings: dict | None = None) -> np.ndarray:
    """Renk adımı için yalnızca kıyafete ait piksellerin (N x 3, RGB) maskesi. Çok büyükse
    düzenli aralıkla örneklenir (rastgelelik yok, sonuç tekrarlanabilir)."""
    s = settings or load_image_settings()
    arr = np.asarray(rgba.convert("RGBA"))
    mask = arr[..., 3] >= s["mask_alpha_threshold"]
    pixels = arr[..., :3][mask]
    if len(pixels) == 0:
        raise ImageError("kıyafet bulunamadı")
    if len(pixels) > s["mask_max_pixels"]:
        pixels = pixels[:: int(np.ceil(len(pixels) / s["mask_max_pixels"]))]
    return pixels


@dataclass(frozen=True)
class ProcessedImage:
    webp: bytes
    size_px: tuple[int, int]
    pixels: np.ndarray  # D6'ya giden kıyafet maskesi


def process_image(data: bytes, settings: dict | None = None) -> ProcessedImage:
    s = settings or load_image_settings()
    rgba = remove_background(open_image(data), s)
    pixels = clothing_pixels(rgba, s)
    webp, size = shrink_to_webp(rgba, s)
    return ProcessedImage(webp, size, pixels)
