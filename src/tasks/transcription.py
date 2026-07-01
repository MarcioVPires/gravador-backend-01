"""Transcrição — Groq `whisper-large-v3-turbo` (DEC-023).

Usa `verbose_json` e deriva `srt` + `texto` + `idioma` numa só chamada. Upsert em
`transcriptions` (1:1 por gravação). Cada tentativa (sucesso/falha) = 1 `processing_jobs`
(+ `ai_usage` no sucesso). O worker cuida de retry/fallback e de habilitar a análise (DEC-022).
"""
import logging
import os

from .. import ai_client, cost, db

log = logging.getLogger("backp.transcription")


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _to_srt(segments: list) -> str:
    blocks = []
    for i, seg in enumerate(segments or [], 1):
        start = _ts(float(seg.get("start", 0)))
        end = _ts(float(seg.get("end", 0)))
        text = (seg.get("text") or "").strip()
        blocks.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(blocks)


async def run(task: dict, recording: dict, service: dict, *, audio: bytes, meta: dict) -> None:
    """UMA tentativa com `service`. Sucesso → escreve tudo; falha → registra job e propaga (worker decide)."""
    provider, model = service["provider"], service["model"]
    api_key = os.environ.get(service["key_env"], "")
    if not api_key:
        raise ai_client.AIError(f"chave {service['key_env']} ausente no ambiente", transient=False)

    filename = meta.get("name") or f"{recording['id']}.audio"
    mime = meta.get("mimeType") or "application/octet-stream"

    try:
        raw = await ai_client.transcribe(
            base_url=service["base_url"], api_key=api_key, model=model,
            audio=audio, filename=filename, mime=mime, config=service.get("config"),
        )
    except ai_client.AIError as e:
        await db.insert_job(
            recording_id=recording["id"], workspace_id=recording["workspace_id"], task="transcription",
            provider=provider, model=model, status="error", error=str(e),
            raw=(e.raw if isinstance(e.raw, dict) else None), task_id=task["id"], prompt_id=None,
        )
        raise

    segments = raw.get("segments") or []
    texto = (raw.get("text") or "").strip()
    idioma = raw.get("language")
    duration = float(raw.get("duration") or 0)
    srt = _to_srt(segments)

    await db.upsert_transcription(
        recording_id=recording["id"], workspace_id=recording["workspace_id"],
        author_id=recording.get("author_id"), api=provider, model=model,
        srt=srt, texto=texto, idioma=idioma,
    )
    job_id = await db.insert_job(
        recording_id=recording["id"], workspace_id=recording["workspace_id"], task="transcription",
        provider=provider, model=model, status="done", error=None, raw=None,
        task_id=task["id"], prompt_id=None,
    )
    usage = {"audio_seconds": duration}
    pricing = await db.get_model_pricing(provider, model)
    await db.insert_usage(
        job_id=job_id, recording_id=recording["id"], workspace_id=recording["workspace_id"],
        task="transcription", provider=provider, model=model,
        cost_total=cost.compute_cost(pricing, usage), usage=usage, pricing_snapshot=pricing,
    )
    log.info("transcrição ok: rec=%s provider=%s dur=%.1fs", recording["id"], provider, duration)
