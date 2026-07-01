"""Configuração via env (DEC-019). Sem segredo hardcoded; tudo do ambiente."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_url: str
    db_password: str
    webhook_secret: str
    max_concurrency: int
    # Google Drive central (mesma conta do front): baixa o áudio da gravação (drive.file).
    drive_client_id: str
    drive_client_secret: str
    drive_refresh_token: str


def load_settings() -> Settings:
    return Settings(
        # URL do pooler SEM a senha; a senha vai separada (abaixo) p/ não quebrar o parse
        # com caracteres especiais.
        db_url=os.environ.get("SUPABASE_DB_URL", ""),
        db_password=os.environ.get("SUPABASE_DB_PASSWORD", ""),
        webhook_secret=os.environ.get("WEBHOOK_SECRET", ""),
        max_concurrency=int(os.environ.get("MAX_CONCURRENCY", "1")),
        drive_client_id=os.environ.get("DRIVE_CLIENT_ID", ""),
        drive_client_secret=os.environ.get("DRIVE_CLIENT_SECRET", ""),
        drive_refresh_token=os.environ.get("DRIVE_REFRESH_TOKEN", ""),
    )


settings = load_settings()
