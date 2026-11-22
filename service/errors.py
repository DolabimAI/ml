"""Ortak hata biçimi (A3 sözleşmesi, bölüm 8): her hata `{"code": ..., "message": ...}` döner."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("service.errors")


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message})


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return error_response(422, "invalid_request", "İstek biçimi geçersiz.")

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        log.exception("beklenmeyen hata")
        return error_response(500, "internal_error", "Beklenmeyen bir hata oluştu.")
