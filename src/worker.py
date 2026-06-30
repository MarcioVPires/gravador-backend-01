"""Worker: drena o registro `processing_tasks` e despacha o processamento.

ESQUELETO (Etapa 4). A Etapa 5 (dev) implementa o claim atômico, o dispatch real
(transcrição/análise) sob o semáforo de concorrência, e o fallback. Por ora só REPORTA
o pendente — prova o caminho webhook → Cloud Run → DB sem mutar nem forjar resultado.
"""
import asyncio
import logging

from . import db
from .config import settings

log = logging.getLogger("backp.worker")

# Teto de concorrência de IA in-process (DEC-019). Usado pelo dispatch real na Etapa 5.
_sem = asyncio.Semaphore(settings.max_concurrency)


async def drain() -> dict:
    pending = await db.count_pending()
    log.info("drain: %s task(s) pendente(s) — processamento real = Etapa 5 (TODO)", pending)
    # TODO(Etapa 5):
    #   while há task devida:
    #     task = claim_next()            # UPDATE ... WHERE state='pending' ... RETURNING (DEC-022)
    #     async with _sem:               # respeita o teto de concorrência (RPM) — DEC-019
    #         dispatch(task)             # transcription | analysis (DEC-023/025)
    #     atualizar state/next_attempt_at/current_priority; fallback ao esgotar (DEC-021/022)
    #   reivindicar 'running' presa por crash (reclaim por timeout)
    return {"drained": {"pending_seen": pending, "processed": 0}, "note": "worker stub (Etapa 5)"}
