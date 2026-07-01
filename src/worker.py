"""Worker: drena o registro `processing_tasks` e despacha o processamento (DEC-020/021/022).

Ao acordar (webhook), DRENA tudo que está pendente: reivindica presas por crash, faz claim
atômico e processa cada task. Retry/fallback é IN-PROCESS (Decisão A): backoff na mesma execução;
malformado = imediato; esgotou N na prioridade → avança current_priority; esgotou todas → error.
Um recording flui inteiro numa acordada (transcrição habilita a análise, drenada na sequência).
"""
import asyncio
import logging

from . import ai_client, db, drive, fallback
from .config import settings
from .tasks import analysis, transcription

log = logging.getLogger("backp.worker")

# Tuning (setup/dev, DEC-022): N por prioridade, backoff, reclaim.
N_ATTEMPTS = 3
BACKOFF_SECONDS = 10
CLAIM_TIMEOUT_SECONDS = 900  # 15 min: 'running' presa além disso é reivindicada (worker morreu)
WORKER_ID = "cloudrun"

# Teto de concorrência de IA in-process (DEC-019). max_instances=1/concurrency=1 no v1.
_sem = asyncio.Semaphore(settings.max_concurrency)


async def _try_service(handler, task, recording, service, **kwargs) -> bool:
    """N tentativas com `service`. True = sucesso. Transitório→backoff; malformado→imediato;
    4xx/config→desiste desta key (deixa o worker avançar de prioridade)."""
    last = ""
    for attempt in range(N_ATTEMPTS):
        try:
            await handler(task, recording, service, **kwargs)
            return True
        except ai_client.MalformedOutput as e:
            last = str(e)
            if attempt < N_ATTEMPTS - 1:
                continue  # retry imediato
            return False
        except ai_client.AIError as e:
            last = str(e)
            if e.transient:
                if attempt < N_ATTEMPTS - 1:
                    await asyncio.sleep(BACKOFF_SECONDS)
                    continue
                return False
            return False  # não-transitório (401/404/413/envelope): trocar de key não ajuda → avança
    log.warning("service esgotado (%s/%s): %s", service.get("provider"), service.get("key_env"), last[:200])
    return False


async def _dispatch_transcription(task: dict, recording: dict, services: list[dict]) -> None:
    # Pré-requisito: baixar o áudio (uma vez). Drive fora = transitório → re-agenda a task inteira.
    try:
        audio, meta = await drive.download(recording["drive_file_id"])
    except drive.DriveError as e:
        await db.requeue_task(task["id"], BACKOFF_SECONDS, f"drive: {e}")
        log.warning("download falhou (re-agendado): rec=%s %s", recording["id"], e)
        return

    size = recording.get("size_bytes")
    if size is None:
        try:
            size = int(meta.get("size")) if meta.get("size") else None  # fallback: tamanho do Drive
        except (TypeError, ValueError):
            size = None

    ladder = fallback.eligible_from(services, task["current_priority"], size)
    if not ladder:
        await db.mark_task_failed(task["id"], f"sem serviço elegível (gate de tamanho; size={size})")
        await db.set_recording_status(recording["id"], "error")
        return

    for service in ladder:
        ok = await _try_service(transcription.run, task, recording, service, audio=audio, meta=meta)
        if ok:
            await db.mark_task_done(task["id"])
            await db.ensure_analysis_task(recording["id"], recording["workspace_id"])
            return
        await db.bump_priority_pointer(task["id"], f"prioridade {service['priority']} esgotada")

    await db.mark_task_failed(task["id"], "transcrição: esgotou todas as prioridades")
    await db.set_recording_status(recording["id"], "error")


async def _dispatch_analysis(task: dict, recording: dict, services: list[dict]) -> None:
    ladder = fallback.eligible_from(services, task["current_priority"], None)  # texto: sem gate de tamanho
    if not ladder:
        await db.mark_task_failed(task["id"], "análise: nenhum serviço habilitado")
        await db.set_recording_status(recording["id"], "error")
        return
    for service in ladder:
        ok = await _try_service(analysis.run, task, recording, service)
        if ok:
            await db.mark_task_done(task["id"])
            await db.set_recording_status(recording["id"], "done")
            return
        await db.bump_priority_pointer(task["id"], f"prioridade {service['priority']} esgotada")

    await db.mark_task_failed(task["id"], "análise: esgotou todas as prioridades")
    await db.set_recording_status(recording["id"], "error")


async def _process_one(task: dict) -> None:
    recording = await db.get_recording(task["recording_id"])
    if not recording:
        await db.mark_task_failed(task["id"], "gravação inexistente")
        return
    # reflete que está processando (a PWA nunca muda status — REQ-007)
    if recording.get("status") == "awaiting_processing":
        await db.set_recording_status(recording["id"], "processing")

    services = await db.get_services(task["task"])
    if task["task"] == "transcription":
        await _dispatch_transcription(task, recording, services)
    else:
        await _dispatch_analysis(task, recording, services)


async def drain() -> dict:
    reclaimed = await db.reclaim_stuck(CLAIM_TIMEOUT_SECONDS)
    if reclaimed:
        log.info("reclaim: %s task(s) presa(s) devolvida(s) a pending", reclaimed)

    processed = 0
    # Drena até a fila esvaziar. O semáforo limita a concorrência real de IA (DEC-019).
    while True:
        task = await db.claim_next_task(WORKER_ID)
        if not task:
            break
        async with _sem:
            try:
                await _process_one(task)
            except Exception as e:  # noqa: BLE001 — rede/DB inesperado: re-agenda, não perde a task
                log.exception("erro inesperado na task %s", task.get("id"))
                await db.requeue_task(task["id"], BACKOFF_SECONDS, f"inesperado: {e}")
        processed += 1

    return {"drained": {"processed": processed, "reclaimed": reclaimed}}
