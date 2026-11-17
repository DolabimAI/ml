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

from fastapi import APIRouter, FastAPI

from service import codes
from service.config import load_settings

MODULES = ("vision", "recommendation")


def _load_router(module: str) -> APIRouter | None:
    if importlib.util.find_spec(f"{module}.router") is None:
        return None
    return importlib.import_module(f"{module}.router").router


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="DolabımAI ml servisi", version="0.1.0")
    app.state.settings = settings

    loaded: list[str] = []
    for module in MODULES:
        router = _load_router(module)
        if router is not None:
            app.include_router(router)
            loaded.append(module)

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
