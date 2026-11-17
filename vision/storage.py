"""D2: temiz görseli Supabase Storage'a yazar ve dosya yolunu döner.

Python veritabanına hiçbir şey yazmaz; yalnızca görsel deposuna yazar.
Dosya yolu: <bucket>/<kullanıcı-id>/<rastgele-ad>.webp (C# hesap silmede klasörü tek seferde siler).
"""
from __future__ import annotations

import re
import uuid

import httpx

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class StorageError(RuntimeError):
    pass


def build_path(bucket: str, user_id: str) -> str:
    if not _SAFE_ID.match(user_id):
        raise ValueError("geçersiz kullanıcı id")
    return f"{bucket}/{user_id}/{uuid.uuid4().hex}.webp"


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
    path = build_path(bucket, user_id)
    object_key = path[len(bucket) + 1 :]
    url = f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{object_key}"
    headers = {
        "Authorization": f"Bearer {service_key}",
        "apikey": service_key,
        "Content-Type": "image/webp",
        "x-upsert": "false",
    }
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
