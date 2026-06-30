"""Configuração via env (DEC-019). Sem segredo hardcoded; tudo do ambiente."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_url: str
    webhook_secret: str
    max_concurrency: int


def load_settings() -> Settings:
    return Settings(
        db_url=os.environ.get("SUPABASE_DB_URL", ""),
        webhook_secret=os.environ.get("WEBHOOK_SECRET", ""),
        max_concurrency=int(os.environ.get("MAX_CONCURRENCY", "1")),
    )


settings = load_settings()
