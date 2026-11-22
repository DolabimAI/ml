"""FastAPI uygulaması.

İki modül aynı serviste çalışır: `vision` (görüntü işleme, Onur) ve `recommendation`
(öneri, Ömer). Bir modül kendi uçlarını `<modül>/router.py` içinde `router` adlı bir
`APIRouter` olarak tanımlar; bu dosya var olduğu anda servis onu otomatik bağlar.
Bu dosyaya dokunmak gerekmez.

Çalıştırma (depo kökünden): python -m uvicorn service.main:app --reload
"""
from __future__ import annotations

import importlib
import importlib.util
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from service import codes
from service.config import load_settings
from service.errors import register_error_handlers

MODULES = ("vision", "recommendation")


def _load_router(module: str) -> APIRouter | None:
    if importlib.util.find_spec(f"{module}.router") is None:
        return None
    return importlib.import_module(f"{module}.router").router


def create_app() -> FastAPI:
    settings = load_settings()
    loaded: list[str] = []
    routers: dict[str, APIRouter] = {}
    for module in MODULES:
        router = _load_router(module)
        if router is not None:
            routers[module] = router
            loaded.append(module)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Modeller servis açılırken bir kez yüklenir: modülün router.py dosyasında `warm_up()` varsa çağrılır.
        for module in loaded:
            warm_up = getattr(importlib.import_module(f"{module}.router"), "warm_up", None)
            if warm_up is not None:
                warm_up()
        yield

    app = FastAPI(title="DolabımAI ml servisi", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    register_error_handlers(app)
    for router in routers.values():
        app.include_router(router)

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "modules": loaded,
            "codes": {
                "subtypes": len(codes.subtype_values()),
                "colors": len(codes.color_values()),
                "tones": len(codes.tone_values()),
            },
        }

    return app


app = create_app()
