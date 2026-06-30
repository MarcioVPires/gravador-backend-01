"""Cliente OpenAI-compatível uniforme (DEC-021/023). ESQUELETO — Etapa 5.

Um único cliente serve OpenAI, Gemini (endpoint compat) e kie: muda `base_url` + `key` +
`model`; o que varia modelo-a-modelo vai no body (vem do `ai_services.config` jsonb).
"""
import httpx  # noqa: F401  (usado na Etapa 5)

# TODO(Etapa 5):
#   async def call(base_url: str, api_key: str, model: str, body: dict) -> dict
#       chat/completions ou audio/transcriptions conforme a task; httpx.AsyncClient com timeout.
