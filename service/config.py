"""Servis ayarları. Değerler ortam değişkenlerinden ya da depo kökündeki .env dosyasından okunur.

Gerçek .env dosyası depoya girmez; örnek değerler .env.example içindedir.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    # Görüntü modülü (D2 ve sonrası) bu değerleri kullanır. Python veritabanına bağlanmaz;
    # yalnızca görsel deposuna yazar.
    supabase_url: str
    supabase_service_key: str
    storage_bucket: str


def load_settings(env_file: Path | None = None) -> Settings:
    file_values = _read_dotenv(env_file or ROOT / ".env")

    def get(name: str, default: str = "") -> str:
        return os.environ.get(name, file_values.get(name, default))

    return Settings(
        host=get("ML_HOST", "127.0.0.1"),
        port=int(get("ML_PORT", "8000")),
        supabase_url=get("SUPABASE_URL"),
        supabase_service_key=get("SUPABASE_SERVICE_KEY"),
        storage_bucket=get("SUPABASE_BUCKET", "gorseller"),
    )
