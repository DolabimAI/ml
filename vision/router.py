"""D7: POST /analyze. Sözleşme: DolabimAI/api `contracts/python-api.md` bölüm 5 ve 8.

Fotoğrafı işler (D2), depoya yazar (D2), alt tür (D4), renk, ton ve desen (D6) tahmin eder.
Python güven ne olursa olsun en olası alt türü döner; eşik kararını C# verir.
Görsel yazıldıktan sonra bir adım başarısız olursa yazılan görsel silinir.
"""
from __future__ import annotations

import logging
import time
import uuid
from functools import lru_cache

import io

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from PIL import Image

from service.errors import error_response
from vision import background, color, storage
from vision.subtype import FashionClipEmbedder, SubtypePredictor

log = logging.getLogger("vision.analyze")
router = APIRouter(tags=["vision"])

class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    image_path: str
    subtype: str
    subtype_confidence: float
    color: str
    tone: str
    is_patterned: bool
    raw_color: str


@lru_cache(maxsize=1)
def get_predictor() -> SubtypePredictor:
    """FashionCLIP ve etiket gömmeleri süreç başına bir kez yüklenir."""
    return SubtypePredictor(FashionClipEmbedder())


def warm_up() -> None:
    """Servis açılırken modelleri bir kez yükler; ilk istek yavaş kalmaz. Hata olursa ilk istekte yeniden denenir."""
    try:
        background.get_session()
        get_predictor()
    except Exception:  # noqa: BLE001
        log.exception("model yüklenemedi; ilk istekte yeniden denenecek")
        get_predictor.cache_clear()


def analyze_image(data: bytes, user_id: str, settings, *, predictor: SubtypePredictor, client=None) -> AnalyzeResponse:
    processed = background.process_image(data)  # ImageError: fotoğraf okunamadı
    kwargs = dict(supabase_url=settings.supabase_url, service_key=settings.supabase_service_key,
                  bucket=settings.storage_bucket, client=client)
    path = storage.upload_webp(processed.webp, user_id, **kwargs)
    try:
        pred = predictor.predict(Image.open(io.BytesIO(processed.webp)).convert("RGB"))
        col = color.extract_color(processed.pixels)
        return AnalyzeResponse(
            image_path=path,
            subtype=pred.top_subtype,
            subtype_confidence=round(pred.confidence, 3),
            color=col.color,
            tone=col.tone,
            is_patterned=col.is_patterned,
            raw_color=col.hex.upper(),
        )
    except Exception:
        storage.delete_object(path, **kwargs)
        raise


@router.post("/analyze", response_model=AnalyzeResponse, response_model_by_alias=True)
def analyze(request: Request, image: UploadFile = File(...), user_id: str = Form(..., alias="userId")):
    started = time.perf_counter()
    try:
        uuid.UUID(user_id)
    except ValueError:
        return error_response(422, "invalid_request", "userId geçerli bir UUID olmalı.")
    data = image.file.read()
    try:
        result = analyze_image(data, user_id, request.app.state.settings, predictor=get_predictor())
    except background.ImageError:
        return error_response(422, "image_unreadable", "Fotoğraf okunamadı.")
    log.info("analyze %.2f sn (%d bayt)", time.perf_counter() - started, len(data))
    return result
