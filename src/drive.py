"""Download do áudio da gravação a partir do Google Drive CENTRAL (DEC-002/009/011).

O áudio sobe browser→Drive na conta central (escopo drive.file: a conta só enxerga o que o
app criou). O back-p baixa o mesmo arquivo reusando as credenciais centrais do front
(DRIVE_CLIENT_ID/SECRET/REFRESH_TOKEN) — sem escopo novo, sem service account. O access token
(vida ~1h) é cacheado in-process com folga de expiração.
"""
import asyncio
import logging
import time

import httpx

from .config import settings

log = logging.getLogger("backp.drive")

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE = "https://www.googleapis.com/drive/v3"

_token: str | None = None
_token_exp: float = 0.0
_token_lock = asyncio.Lock()


class DriveError(RuntimeError):
    """Falha ao acessar/baixar do Drive (token, metadata ou conteúdo)."""


async def _access_token() -> str:
    global _token, _token_exp
    async with _token_lock:
        if _token and time.monotonic() < _token_exp - 60:
            return _token
        if not (settings.drive_client_id and settings.drive_client_secret and settings.drive_refresh_token):
            raise DriveError("credenciais do Drive ausentes no ambiente (DRIVE_CLIENT_ID/SECRET/REFRESH_TOKEN)")
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(TOKEN_URL, data={
                "client_id": settings.drive_client_id,
                "client_secret": settings.drive_client_secret,
                "refresh_token": settings.drive_refresh_token,
                "grant_type": "refresh_token",
            })
        if r.status_code != 200:
            raise DriveError(f"refresh token do Drive falhou: HTTP {r.status_code}")
        body = r.json()
        _token = body["access_token"]
        _token_exp = time.monotonic() + int(body.get("expires_in", 3600))
        return _token


async def get_metadata(file_id: str) -> dict:
    """Metadata do arquivo: name, mimeType, size (bytes, string). Escopo drive.file."""
    token = await _access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{DRIVE}/files/{file_id}",
            params={"fields": "id,name,mimeType,size"},
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code != 200:
        raise DriveError(f"metadata do Drive falhou (file {file_id}): HTTP {r.status_code}")
    return r.json()


async def download(file_id: str) -> tuple[bytes, dict]:
    """Baixa o conteúdo (alt=media) do arquivo. Devolve (bytes, metadata)."""
    meta = await get_metadata(file_id)
    token = await _access_token()
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.get(
            f"{DRIVE}/files/{file_id}",
            params={"alt": "media"},
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code != 200:
        raise DriveError(f"download do Drive falhou (file {file_id}): HTTP {r.status_code}")
    return r.content, meta
