"""E7, E5: POST /recommend ve POST /swap uçları (A3 sözleşmesi, bölüm 6 ve 7).

`service/main.py` bu dosyadaki `router`'ı kendiliğinden bağlar. Hatalar sözleşmenin
`{code, message}` biçimindedir; FastAPI'nin `{"detail": [...]}` cevabı hiç dönmez.
Python'un mesajı kullanıcıya gösterilmez, yalnız C#'ın loguna yazılır.
"""

import logging
import random
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .filter import Outfit
from .recommend import recommend
from .schemas import RecommendRequest, SwapRequest
from .swap import swap

router = APIRouter(tags=["recommendation"])
log = logging.getLogger(__name__)

INTERNAL_ERROR_MESSAGE = "Beklenmeyen bir hata oluştu."


def get_rng() -> random.Random:
    """Her istek için yeni rastgelelik; testler bunu sabit tohumla değiştirir."""
    return random.Random()


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status)


def _describe(error: ValidationError, limit: int = 3) -> str:
    parts = []
    for detail in error.errors(include_url=False)[:limit]:
        location = ".".join(str(part) for part in detail["loc"]) or "gövde"
        parts.append(f"{location}: {detail['msg']}")
    extra = error.error_count() - limit
    return "; ".join(parts) + (f" (+{extra} hata)" if extra > 0 else "")


def _outfit_json(outfit: Outfit) -> dict:
    return {"template": outfit.template, "itemIds": [item.id for item in outfit.items]}


@router.post("/recommend")
async def recommend_endpoint(request: Request, rng: random.Random = Depends(get_rng)) -> JSONResponse:
    try:
        inputs = RecommendRequest.model_validate_json(await request.body()).to_domain()
    except ValidationError as error:  # ValueError'ın alt sınıfı; önce yakalanır.
        return _error(422, "invalid_request", _describe(error))
    except ValueError as error:
        return _error(422, "invalid_request", str(error))

    started = time.perf_counter()
    try:
        result = await run_in_threadpool(lambda: recommend(**inputs, rng=rng))
    except Exception:
        log.exception("/recommend beklenmeyen hata")
        return _error(500, "internal_error", INTERNAL_ERROR_MESSAGE)
    log.info("/recommend %.0f ms, %d parça, %d geçmiş karar", (time.perf_counter() - started) * 1000,
             len(inputs["wardrobe"]), len(inputs["history"]))

    if result is None:
        return JSONResponse({"status": "no_candidates"})
    return JSONResponse({
        "status": "ok",
        "ruleOutfit": _outfit_json(result.rule_outfit),
        "learnedOutfit": _outfit_json(result.learned_outfit),
        "isSameOutfit": result.is_same_outfit,
        "learnedPickMode": result.learned_pick_mode,
        "accessoryIds": [item.id for item in result.accessories],
    })


@router.post("/swap")
async def swap_endpoint(request: Request, rng: random.Random = Depends(get_rng)) -> JSONResponse:
    try:
        inputs = SwapRequest.model_validate_json(await request.body()).to_domain()
    except ValidationError as error:  # ValueError'ın alt sınıfı; önce yakalanır.
        return _error(422, "invalid_request", _describe(error))
    except ValueError as error:
        return _error(422, "invalid_request", str(error))

    started = time.perf_counter()
    try:
        item = await run_in_threadpool(lambda: swap(**inputs, rng=rng))
    except Exception:
        log.exception("/swap beklenmeyen hata")
        return _error(500, "internal_error", INTERNAL_ERROR_MESSAGE)
    log.info("/swap %s %.0f ms, %d parça, %d geçmiş karar", inputs["method"],
             (time.perf_counter() - started) * 1000, len(inputs["wardrobe"]), len(inputs["history"]))

    if item is None:
        return JSONResponse({"status": "no_alternative"})
    return JSONResponse({"status": "ok", "newItemId": item.id})
