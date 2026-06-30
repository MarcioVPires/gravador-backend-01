"""Configuração via env (DEC-019). Sem segredo hardcoded; tudo do ambiente."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_url: str
    db_password: str
    webhook_secret: str
    max_concurrency: int


def load_settings() -> Settings:
    return Settings(
        # URL do pooler SEM a senha; a senha vai separada (abaixo) p/ não quebrar o parse
        # com caracteres especiais.
        db_url=os.environ.get("SUPABASE_DB_URL", ""),
        db_password=os.environ.get("SUPABASE_DB_PASSWORD", ""),
        webhook_secret=os.environ.get("WEBHOOK_SECRET", ""),
        max_concurrency=int(os.environ.get("MAX_CONCURRENCY", "1")),
    )


settings = load_settings()
