"""FastAPI do back-p. Endpoints: /health e /process (webhook do Supabase).

Mecanismo (DEC-020): o Supabase dispara um Database Webhook no INSERT de `recordings` →
POST /process. O back-p garante a task durável e DRENA tudo que está pendente. Sem
scheduler/poll/UPDATE-webhook: o back-p só acorda quando há trabalho.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request

from . import db
from .config import settings
from .worker import drain

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("backp")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Não derruba o serviço se o DB estiver mal configurado: sobe de pé e o /health reporta down.
    try:
        await db.open_pool()
    except Exception:  # noqa: BLE001
        log.exception("falha ao abrir o pool no startup; servico segue de pe (/health reporta)")
    yield
    await db.close_pool()


app = FastAPI(title="back-p · api-processamento", lifespan=lifespan)


@app.get("/health")
async def health():
    try:
        await db.healthcheck()
        return {"ok": True, "db": "up"}
    except Exception as e:  # noqa: BLE001
        log.exception("health falhou")
        return {"ok": False, "db": "down", "error": str(e)}


@app.post("/process")
async def process(
    request: Request,
    x_webhook_secret: str | None = Header(default=None),
):
    # Autentica o webhook (DEC-020). Se WEBHOOK_SECRET estiver setado, exige o header.
    if settings.webhook_secret and x_webhook_secret != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="unauthorized")

    payload = await request.json()
    # Supabase Database Webhook (INSERT em recordings): { type, table, record, old_record, ... }
    record = (payload or {}).get("record") or {}
    recording_id = record.get("id")
    workspace_id = record.get("workspace_id")

    if recording_id and workspace_id:
        await db.ensure_transcription_task(recording_id, workspace_id)

    # Drena SÍNCRONO dentro do request: no Cloud Run a CPU só é alocada durante o request,
    # e o desenho sem-piso exige que o trabalho conclua nesta acordada (o webhook do Supabase
    # é fire-and-forget — uma resposta lenta não atrapalha). DEC-020.
    result = await drain()
    return {"ok": True, "recording_id": recording_id, **result}
