"""Acesso ao Postgres do Supabase via psycopg3 (pool async).

Escolha: Postgres direto (não supabase-py) — o coração do back-p é claim transacional
e queries de fila (DEC-022), muito mais limpos em SQL. Acesso por service_role/conn string
(o pooler tem credenciais próprias). DEC-019.
"""
import logging

from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import AsyncConnectionPool

from .config import settings

log = logging.getLogger("backp.db")

_pool: AsyncConnectionPool | None = None


async def _configure(conn) -> None:
    # O POOLER do Supabase (pgbouncer, transaction mode) não suporta prepared statements
    # server-side persistentes → desliga o prepare do psycopg para evitar erros sob carga.
    conn.prepare_threshold = None


async def open_pool() -> None:
    global _pool
    if not settings.db_url:
        raise RuntimeError("SUPABASE_DB_URL não definido no ambiente")
    # Senha vai SEPARADA (env SUPABASE_DB_PASSWORD), nunca na URL → caractere especial na
    # senha não quebra o parse. sslmode=require: o Supabase exige SSL.
    conn_kwargs: dict = {"sslmode": "require"}
    if settings.db_password:
        conn_kwargs["password"] = settings.db_password
    _pool = AsyncConnectionPool(
        settings.db_url, min_size=1, max_size=4, open=False,
        configure=_configure, kwargs=conn_kwargs,
    )
    await _pool.open()
    log.info("pool Postgres aberto")


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("pool não inicializado (open_pool não rodou)")
    return _pool


async def healthcheck() -> bool:
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select 1")
            await cur.fetchone()
    return True


async def ensure_transcription_task(recording_id: str, workspace_id: str) -> None:
    """Cria a task de transcrição de forma DURÁVEL e IDEMPOTENTE (DEC-020/022).

    1 task por (recording, task) → `on conflict do nothing`. É o que torna o trabalho
    recuperável mesmo se o webhook se perder (a próxima drenagem pega).
    """
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                insert into processing_tasks (recording_id, workspace_id, task)
                values (%s, %s, 'transcription')
                on conflict (recording_id, task) do nothing
                """,
                (recording_id, workspace_id),
            )


async def count_pending() -> int:
    """Tamanho da 'fila' (DEC-022): tasks prontas para rodar agora."""
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select count(*) from processing_tasks "
                "where state='pending' and next_attempt_at <= now()"
            )
            row = await cur.fetchone()
            return int(row[0]) if row else 0


# ===========================================================================
# Etapa 5 — camada de dados do worker (claim/fila + leituras + escritas idempotentes)
# ===========================================================================

async def _fetchone(sql: str, params: tuple = ()) -> dict | None:
    async with pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return await cur.fetchone()


async def _fetchall(sql: str, params: tuple = ()) -> list[dict]:
    async with pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())


async def _exec(sql: str, params: tuple = ()) -> None:
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)


# ---- fila / claim (DEC-022) -----------------------------------------------

async def claim_next_task(worker_id: str) -> dict | None:
    """Claim ATÔMICO da próxima task devida (só um worker ganha). FOR UPDATE SKIP LOCKED."""
    async with pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                update processing_tasks set state='running', claimed_at=now(),
                       claimed_by=%s, updated_at=now()
                where id = (
                    select id from processing_tasks
                    where state='pending' and next_attempt_at <= now()
                    order by next_attempt_at
                    for update skip locked
                    limit 1
                )
                returning *
                """,
                (worker_id,),
            )
            return await cur.fetchone()


async def reclaim_stuck(timeout_seconds: int) -> int:
    """Devolve a 'pending' tasks 'running' presas tempo demais (worker morreu)."""
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "update processing_tasks set state='pending', updated_at=now() "
                "where state='running' and claimed_at < now() - (%s || ' seconds')::interval",
                (timeout_seconds,),
            )
            return cur.rowcount


# ---- transições de estado da task (DEC-022) --------------------------------

async def mark_task_done(task_id: str) -> None:
    await _exec("update processing_tasks set state='done', last_error=null, updated_at=now() where id=%s", (task_id,))


async def requeue_task(task_id: str, backoff_seconds: int, last_error: str) -> None:
    """Erro transitório: volta a pending, attempt_count++, espera backoff."""
    await _exec(
        "update processing_tasks set state='pending', attempt_count=attempt_count+1, "
        "next_attempt_at = now() + (%s || ' seconds')::interval, last_error=%s, "
        "claimed_at=null, claimed_by=null, updated_at=now() where id=%s",
        (backoff_seconds, last_error[:1000], task_id),
    )


async def requeue_immediate(task_id: str, last_error: str) -> None:
    """Output malformado: re-tenta imediato (sem espera), attempt_count++."""
    await _exec(
        "update processing_tasks set state='pending', attempt_count=attempt_count+1, "
        "next_attempt_at=now(), last_error=%s, claimed_at=null, claimed_by=null, updated_at=now() where id=%s",
        (last_error[:1000], task_id),
    )


async def advance_priority(task_id: str, last_error: str) -> None:
    """Esgotou N na prioridade atual: avança current_priority, zera attempt_count, re-pending imediato."""
    await _exec(
        "update processing_tasks set current_priority=current_priority+1, attempt_count=0, "
        "state='pending', next_attempt_at=now(), last_error=%s, claimed_at=null, claimed_by=null, "
        "updated_at=now() where id=%s",
        (last_error[:1000], task_id),
    )


async def bump_priority_pointer(task_id: str, last_error: str) -> None:
    """Avança current_priority MANTENDO o claim (state='running') — persiste p/ retomar após crash."""
    await _exec(
        "update processing_tasks set current_priority=current_priority+1, attempt_count=0, "
        "last_error=%s, updated_at=now() where id=%s",
        (last_error[:1000], task_id),
    )


async def mark_task_failed(task_id: str, last_error: str) -> None:
    await _exec(
        "update processing_tasks set state='failed', last_error=%s, updated_at=now() where id=%s",
        (last_error[:1000], task_id),
    )


async def ensure_analysis_task(recording_id: str, workspace_id: str) -> None:
    """Habilita a task de análise (só fica elegível quando a transcrição concluiu). Idempotente."""
    await _exec(
        "insert into processing_tasks (recording_id, workspace_id, task) values (%s,%s,'report') "
        "on conflict (recording_id, task) do nothing",
        (recording_id, workspace_id),
    )


# ---- leituras --------------------------------------------------------------

async def get_recording(recording_id: str) -> dict | None:
    return await _fetchone(
        "select id, workspace_id, author_id, titulo, observacoes, status, drive_file_id, size_bytes "
        "from recordings where id=%s",
        (recording_id,),
    )


async def get_services(task: str) -> list[dict]:
    return await _fetchall(
        "select * from ai_services where task=%s and enabled=true order by priority", (task,)
    )


async def get_transcription(recording_id: str) -> dict | None:
    return await _fetchone(
        "select texto, idioma from transcriptions where recording_id=%s", (recording_id,)
    )


async def get_active_prompt(task: str) -> dict | None:
    return await _fetchone("select id, blocks from prompts where task=%s and active=true limit 1", (task,))


async def get_workspace_tag_names(workspace_id: str) -> list[str]:
    rows = await _fetchall("select name from tags where workspace_id=%s order by name", (workspace_id,))
    return [r["name"] for r in rows]


async def get_model_pricing(provider: str, model: str) -> dict | None:
    row = await _fetchone(
        "select pricing from model_prices where provider=%s and model=%s "
        "order by effective_from desc limit 1",
        (provider, model),
    )
    return row["pricing"] if row else None


# ---- escritas idempotentes (DEC-036: re-rodar substitui, não duplica) ------

async def upsert_transcription(
    *, recording_id: str, workspace_id: str, author_id: str | None, api: str, model: str,
    srt: str, texto: str, idioma: str | None,
) -> None:
    await _exec(
        """
        insert into transcriptions (recording_id, workspace_id, author_id, api, model, srt, texto, idioma)
        values (%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (recording_id) do update set
            api=excluded.api, model=excluded.model, srt=excluded.srt,
            texto=excluded.texto, idioma=excluded.idioma
        """,
        (recording_id, workspace_id, author_id, api, model, srt, texto, idioma),
    )


async def upsert_report(
    *, recording_id: str, workspace_id: str, author_id: str | None, api: str, model: str,
    relatorio_md: str, raw_response: dict,
) -> None:
    await _exec(
        """
        insert into reports (recording_id, workspace_id, author_id, api, model, relatorio_md, raw_response)
        values (%s,%s,%s,%s,%s,%s,%s)
        on conflict (recording_id) do update set
            api=excluded.api, model=excluded.model, relatorio_md=excluded.relatorio_md,
            raw_response=excluded.raw_response
        """,
        (recording_id, workspace_id, author_id, api, model, relatorio_md, Json(raw_response)),
    )


async def update_recording_titulo_resumo(recording_id: str, titulo: str | None, resumo: str | None) -> None:
    await _exec(
        "update recordings set titulo=coalesce(%s, titulo), resumo=coalesce(%s, resumo), updated_at=now() "
        "where id=%s",
        (titulo, resumo, recording_id),
    )


async def set_recording_status(recording_id: str, status: str) -> None:
    await _exec("update recordings set status=%s, updated_at=now() where id=%s", (status, recording_id))


async def upsert_tag(*, workspace_id: str, name: str, source: str, created_by_model: str | None) -> str:
    """Cria a tag (ou reusa a existente por (workspace_id,name)) e devolve o id. Não altera source de tag existente."""
    row = await _fetchone(
        """
        insert into tags (workspace_id, name, source, created_by_model)
        values (%s,%s,%s,%s)
        on conflict (workspace_id, name) do update set name=excluded.name
        returning id
        """,
        (workspace_id, name, source, created_by_model),
    )
    return row["id"]


async def link_recording_tag(recording_id: str, tag_id: str) -> None:
    await _exec(
        "insert into recording_tags (recording_id, tag_id) values (%s,%s) on conflict do nothing",
        (recording_id, tag_id),
    )


# ---- custo / uso (DEC-024) -------------------------------------------------

async def insert_job(
    *, recording_id: str, workspace_id: str, task: str, provider: str, model: str, status: str,
    error: str | None, raw: dict | None, task_id: str, prompt_id: str | None,
) -> str:
    row = await _fetchone(
        """
        insert into processing_jobs
            (recording_id, workspace_id, task, provider, model, status, started_at, finished_at,
             error, raw, task_id, prompt_id)
        values (%s,%s,%s,%s,%s,%s,now(),now(),%s,%s,%s,%s)
        returning id
        """,
        (recording_id, workspace_id, task, provider, model, status, (error[:2000] if error else None),
         Json(raw) if raw is not None else None, task_id, prompt_id),
    )
    return row["id"]


async def insert_usage(
    *, job_id: str, recording_id: str, workspace_id: str, task: str, provider: str, model: str,
    cost_total: float, usage: dict, pricing_snapshot: dict | None,
) -> None:
    await _exec(
        """
        insert into ai_usage
            (job_id, recording_id, workspace_id, task, provider, model, cost_total, currency,
             usage, pricing_snapshot)
        values (%s,%s,%s,%s,%s,%s,%s,'USD',%s,%s)
        """,
        (job_id, recording_id, workspace_id, task, provider, model, cost_total,
         Json(usage), Json(pricing_snapshot) if pricing_snapshot is not None else None),
    )
