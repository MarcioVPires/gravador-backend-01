"""Acesso ao Postgres do Supabase via psycopg3 (pool async).

Escolha: Postgres direto (não supabase-py) — o coração do back-p é claim transacional
e queries de fila (DEC-022), muito mais limpos em SQL. Acesso por service_role/conn string
(o pooler tem credenciais próprias). DEC-019.
"""
import logging

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
    _pool = AsyncConnectionPool(
        settings.db_url, min_size=1, max_size=4, open=False, configure=_configure
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
