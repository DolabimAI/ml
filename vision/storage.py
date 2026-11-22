"""D2: temiz görseli Supabase Storage'a yazar ve dosya yolunu döner.

Python veritabanına hiçbir şey yazmaz; yalnızca görsel deposuna yazar.
Dönen yol bucket içindeki yoldur: <kullanıcı-id>/<rastgele-ad>.webp (A3 sözleşmesi, `clothes.image_path`).
C# hesap silmede klasörü tek seferde siler.
"""
from __future__ import annotations

import re
import uuid

import httpx

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class StorageError(RuntimeError):
    pass


def build_path(user_id: str) -> str:
    if not _SAFE_ID.match(user_id):
        raise ValueError("geçersiz kullanıcı id")
    return f"{user_id}/{uuid.uuid4().hex}.webp"


def _headers(service_key: str) -> dict:
    return {"Authorization": f"Bearer {service_key}", "apikey": service_key}


def upload_webp(
    data: bytes,
    user_id: str,
    *,
    supabase_url: str,
    service_key: str,
    bucket: str,
    client: httpx.Client | None = None,
) -> str:
    if not supabase_url or not service_key:
        raise StorageError("SUPABASE_URL ve SUPABASE_SERVICE_KEY ayarlanmamış")
    path = build_path(user_id)
    url = f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{path}"
    headers = {**_headers(service_key), "Content-Type": "image/webp", "x-upsert": "false"}
    own = client is None
    client = client or httpx.Client(timeout=20)
    try:
        resp = client.post(url, content=data, headers=headers)
    finally:
        if own:
            client.close()
    if resp.status_code >= 300:
        raise StorageError(f"depoya yazılamadı ({resp.status_code})")
    return path


def delete_object(
    path: str,
    *,
    supabase_url: str,
    service_key: str,
    bucket: str,
    client: httpx.Client | None = None,
) -> None:
    """Yazılmış görseli siler (analiz sonradan başarısız olursa). Hata fırlatmaz; yalnızca bool değil
    sessizce döner, çünkü asıl hata zaten kullanıcıya döneceği hatadır."""
    own = client is None
    client = client or httpx.Client(timeout=20)
    try:
        client.delete(f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{path}", headers=_headers(service_key))
    except httpx.HTTPError:
        pass
    finally:
        if own:
            client.close()
