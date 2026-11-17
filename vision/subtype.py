"""D4: FashionCLIP ile alt tür tahmini.

Model 35 İngilizce etiket ifadesine puan verir (ayar dosyası: vision/subtype_settings.json).
Güven (0-1), ifadeler üzerindeki softmax olasılığıdır. Güven eşiğin altındaysa `subtype` boş döner
(kullanıcı kendisi seçer); en yüksek tahmin ve güveni yine de döner (C# model_predictions'a yazar).
Kategori, tarz, mevsim, kalınlık ve sıcaklık modele sorulmaz; alt türden gelir (shared/subtypes.json).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from service import codes

SETTINGS_PATH = Path(__file__).resolve().parent / "subtype_settings.json"


def load_subtype_settings(path: Path = SETTINGS_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        settings = json.load(f)
    if list(settings["labels"]) != list(codes.subtype_values()):
        raise ValueError("etiket anahtarları ortak kod listesiyle birebir aynı olmalı")
    return settings


@dataclass(frozen=True)
class SubtypePrediction:
    subtype: str | None      # eşiğin altındaysa None
    top_subtype: str         # en yüksek tahmin, her zaman dolu
    confidence: float        # en yüksek tahminin güveni, 0-1


class Embedder(Protocol):
    logit_scale: float

    def encode_image(self, image) -> np.ndarray: ...
    def encode_texts(self, texts: list[str]) -> np.ndarray: ...


def softmax_scores(image_emb: np.ndarray, text_embs: np.ndarray, logit_scale: float) -> np.ndarray:
    """CLIP puanı: normalize edilmiş gömmelerin iç çarpımı x logit_scale, sonra softmax."""
    img = image_emb / np.linalg.norm(image_emb)
    txt = text_embs / np.linalg.norm(text_embs, axis=1, keepdims=True)
    logits = logit_scale * (txt @ img)
    logits = logits - logits.max()
    p = np.exp(logits)
    return p / p.sum()


class SubtypePredictor:
    def __init__(self, embedder: Embedder, settings: dict | None = None):
        self.settings = settings or load_subtype_settings()
        self.embedder = embedder
        self.values = list(self.settings["labels"])
        self.text_embs = embedder.encode_texts([self.settings["labels"][v] for v in self.values])

    def predict(self, image) -> SubtypePrediction:
        probs = softmax_scores(self.embedder.encode_image(image), self.text_embs, self.embedder.logit_scale)
        top = int(np.argmax(probs))
        confidence = float(probs[top])
        accepted = confidence >= self.settings["confidence_threshold"]
        return SubtypePrediction(self.values[top] if accepted else None, self.values[top], confidence)


class FashionClipEmbedder:
    """Gerçek model. transformers ve torch gerekir; ilk çağrıda ağırlıkları indirir (~600 MB).
    Servis açılırken bir kez yüklenmelidir (D7). NOT: bu sınıf geliştirme ortamında çalıştırılamadı
    (Hugging Face erişimi yoktu); ilk gerçek deneme D3'te yapılacak."""

    def __init__(self, model_id: str | None = None):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        model_id = model_id or load_subtype_settings()["model_id"]
        self._torch = torch
        self.model = CLIPModel.from_pretrained(model_id).eval()
        self.processor = CLIPProcessor.from_pretrained(model_id)
        self.logit_scale = float(self.model.logit_scale.exp().item())

    def encode_image(self, image) -> np.ndarray:
        inputs = self.processor(images=image.convert("RGB"), return_tensors="pt")
        with self._torch.no_grad():
            return self.model.get_image_features(**inputs)[0].numpy()

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        inputs = self.processor(text=texts, return_tensors="pt", padding=True)
        with self._torch.no_grad():
            return self.model.get_text_features(**inputs).numpy()
