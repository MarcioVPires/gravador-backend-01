"""Análise — LLM OpenAI-compat (DEC-025).

Monta o prompt a partir dos blocos (`prompts.blocks`) + placeholders, chama o modelo com
structured output (schema nativo + bloco `output` sempre), valida o JSON e grava:
reports (relatorio_md + raw_response), recordings.titulo/resumo, tags (source='ai') + recording_tags.
Cada tentativa = 1 `processing_jobs` (+ `ai_usage` no sucesso). O worker seta status='done' ao concluir.
"""
import json
import logging
import os
import re

from .. import ai_client, cost, db

log = logging.getLogger("backp.analysis")

# Schema nativo do output (OpenAI/Gemini/kie suportam — verificado 2026-06-30).
OUTPUT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "analise_gravacao",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string"},
                "resumo": {"type": "string"},
                "content": {"type": "string"},
                "tags_selecionadas": {"type": "array", "items": {"type": "string"}},
                "tags_sugeridas": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["titulo", "resumo", "content", "tags_selecionadas", "tags_sugeridas"],
            "additionalProperties": False,
        },
    },
}


def normalize_tag_name(name: str) -> str:
    """Igual ao front (lib/taxonomy.normalizeTagName): trim + colapsa espaços + minúsculas. NÃO tira acento."""
    return re.sub(r"\s+", " ", name or "").strip().lower()


def _build_prompt(blocks: list, *, titulo: str | None, observacao: str | None,
                  transcript: str, existing_tags: list[str]) -> str:
    has_title = bool(titulo and titulo.strip())
    has_observation = bool(observacao and observacao.strip())
    tags_str = ", ".join(existing_tags) if existing_tags else "(nenhuma)"
    subs = {
        "<placeholder-title>": titulo or "",
        "<placeholder-observation>": observacao or "",
        "<placeholder-transcript>": transcript or "",
        "<placeholder-existing-tags>": tags_str,
    }
    parts = []
    for b in blocks:
        when = b.get("when")
        if when == "has_title" and not has_title:
            continue
        if when == "no_title" and has_title:
            continue
        if when == "has_observation" and not has_observation:
            continue
        if when == "no_observation" and has_observation:
            continue
        text = b.get("text", "")
        for ph, val in subs.items():
            text = text.replace(ph, val)
        parts.append(text)
    return "\n\n".join(parts)


async def run(task: dict, recording: dict, service: dict) -> None:
    """UMA tentativa com `service`. Sucesso → escreve tudo; falha → registra job e propaga (worker decide)."""
    provider, model = service["provider"], service["model"]
    api_key = os.environ.get(service["key_env"], "")
    if not api_key:
        raise ai_client.AIError(f"chave {service['key_env']} ausente no ambiente", transient=False)

    tr = await db.get_transcription(recording["id"])
    if not tr or not (tr.get("texto") or "").strip():
        raise ai_client.AIError("transcrição ausente/vazia para a análise", transient=False)

    prompt_row = await db.get_active_prompt("report")
    if not prompt_row:
        raise ai_client.AIError("nenhum prompt ativo para 'report'", transient=False)

    existing_tags = await db.get_workspace_tag_names(recording["workspace_id"])
    prompt_text = _build_prompt(
        prompt_row["blocks"], titulo=recording.get("titulo"), observacao=recording.get("observacoes"),
        transcript=tr["texto"], existing_tags=existing_tags,
    )
    messages = [{"role": "user", "content": prompt_text}]

    try:
        raw = await ai_client.chat(
            base_url=service["base_url"], api_key=api_key, model=model, provider=provider,
            messages=messages, response_format=OUTPUT_SCHEMA, config=service.get("config"),
        )
    except ai_client.AIError as e:
        await db.insert_job(
            recording_id=recording["id"], workspace_id=recording["workspace_id"], task="report",
            provider=provider, model=model, status="error", error=str(e),
            raw=(e.raw if isinstance(e.raw, dict) else None), task_id=task["id"],
            prompt_id=prompt_row["id"],
        )
        raise

    # Extrai e valida o output estruturado.
    try:
        content_str = raw["choices"][0]["message"]["content"]
        out = json.loads(content_str)
        titulo = str(out["titulo"]).strip()
        resumo = str(out["resumo"]).strip()
        content_md = str(out["content"])
        tags_sel = [normalize_tag_name(t) for t in (out.get("tags_selecionadas") or []) if str(t).strip()]
        tags_sug = [normalize_tag_name(t) for t in (out.get("tags_sugeridas") or []) if str(t).strip()]
    except (KeyError, IndexError, ValueError, TypeError) as e:
        await db.insert_job(
            recording_id=recording["id"], workspace_id=recording["workspace_id"], task="report",
            provider=provider, model=model, status="error", error=f"output malformado: {e}",
            raw=raw if isinstance(raw, dict) else None, task_id=task["id"], prompt_id=prompt_row["id"],
        )
        raise ai_client.MalformedOutput(f"output malformado: {e}", raw=raw)

    # Grava report + título/resumo.
    await db.upsert_report(
        recording_id=recording["id"], workspace_id=recording["workspace_id"],
        author_id=recording.get("author_id"), api=provider, model=model,
        relatorio_md=content_md, raw_response=raw,
    )
    await db.update_recording_titulo_resumo(recording["id"], titulo or None, resumo or None)

    # Tags: selecionadas (reusa existentes) + sugeridas (cria source='ai'); dedup por nome normalizado.
    seen: set[str] = set()
    for name in tags_sel:
        if name in seen:
            continue
        seen.add(name)
        tag_id = await db.upsert_tag(workspace_id=recording["workspace_id"], name=name, source="ai",
                                     created_by_model=None)
        await db.link_recording_tag(recording["id"], tag_id)
    for name in tags_sug:
        if name in seen:
            continue
        seen.add(name)
        tag_id = await db.upsert_tag(workspace_id=recording["workspace_id"], name=name, source="ai",
                                     created_by_model=model)
        await db.link_recording_tag(recording["id"], tag_id)

    # Job + uso (tokens).
    job_id = await db.insert_job(
        recording_id=recording["id"], workspace_id=recording["workspace_id"], task="report",
        provider=provider, model=model, status="done", error=None, raw=None,
        task_id=task["id"], prompt_id=prompt_row["id"],
    )
    u = raw.get("usage") or {}
    usage = {
        "input_tokens_real": u.get("prompt_tokens"),
        "output_tokens": u.get("completion_tokens"),
        "input_tokens_estimated": None,
        "cached_input_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
    }
    pricing = await db.get_model_pricing(provider, model)
    await db.insert_usage(
        job_id=job_id, recording_id=recording["id"], workspace_id=recording["workspace_id"],
        task="report", provider=provider, model=model,
        cost_total=cost.compute_cost(pricing, usage), usage=usage, pricing_snapshot=pricing,
    )
    log.info("análise ok: rec=%s provider=%s tags=%d", recording["id"], provider, len(seen))
