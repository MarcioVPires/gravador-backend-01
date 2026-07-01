"""Cliente OpenAI-compatível uniforme (DEC-021/023).

Um único cliente serve OpenAI, Gemini (endpoint compat) e kie: muda `base_url` + `key` +
`model`; o que varia modelo-a-modelo vai no body (vem do `ai_services.config` jsonb).

Quirk kie (verificado 2026-06-30): a kie põe o **modelo no PATH** da `base_url`
(`https://api.kie.ai/<model>/v1`), NÃO no body → para provider 'kie' o `model` não vai no body.
A kie também devolve HTTP 200 com envelope de erro `{"code":<n>,"msg":...}` → tratamos como falha.
"""
import logging

import httpx

log = logging.getLogger("backp.ai_client")


class AIError(RuntimeError):
    """Falha classificável de chamada de IA."""

    def __init__(self, message: str, *, transient: bool, status: int | None = None, raw=None):
        super().__init__(message)
        self.transient = transient  # True = tenta de novo (rede/429/5xx/timeout); False = 4xx/config def.
        self.status = status
        self.raw = raw


class MalformedOutput(RuntimeError):
    """Resposta veio, mas fora do contrato (JSON inválido/campos faltando) → retry IMEDIATO (DEC-022)."""

    def __init__(self, message: str, *, raw=None):
        super().__init__(message)
        self.raw = raw


def _kie_envelope_error(body) -> str | None:
    """kie retorna 200 com {code,msg} quando falha. Devolve a msg de erro se for esse caso."""
    if isinstance(body, dict):
        code = body.get("code")
        if code not in (None, 0, 200) and "choices" not in body:
            return str(body.get("msg") or body.get("message") or body)
    return None


async def transcribe(
    *, base_url: str, api_key: str, model: str, audio: bytes, filename: str, mime: str, config: dict | None
) -> dict:
    """POST /audio/transcriptions (multipart). Devolve o JSON cru (verbose_json)."""
    url = base_url.rstrip("/") + "/audio/transcriptions"
    cfg = config or {}
    data = {
        "model": model,
        "response_format": cfg.get("response_format", "verbose_json"),
        "language": cfg.get("language", "pt"),
    }
    files = {"file": (filename, audio, mime or "application/octet-stream")}
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(url, headers={"Authorization": f"Bearer {api_key}"}, data=data, files=files)
    except httpx.HTTPError as e:
        raise AIError(f"rede/timeout na transcrição: {e}", transient=True) from e
    if r.status_code == 200:
        return r.json()
    # 413 (arquivo grande) e 4xx de request = não-transitório; 429/5xx = transitório.
    transient = r.status_code == 429 or r.status_code >= 500
    raise AIError(f"transcrição HTTP {r.status_code}: {r.text[:300]}", transient=transient, status=r.status_code)


async def chat(
    *, base_url: str, api_key: str, model: str, provider: str, messages: list, response_format: dict | None,
    config: dict | None,
) -> dict:
    """POST /chat/completions. Devolve o JSON cru. Para 'kie' o model vai no PATH (base_url), não no body."""
    url = base_url.rstrip("/") + "/chat/completions"
    cfg = config or {}
    body: dict = {"messages": messages}
    if provider != "kie":
        body["model"] = model
    if "temperature" in cfg:
        body["temperature"] = cfg["temperature"]
    if response_format:
        body["response_format"] = response_format
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
            )
    except httpx.HTTPError as e:
        raise AIError(f"rede/timeout na análise: {e}", transient=True) from e
    if r.status_code != 200:
        transient = r.status_code == 429 or r.status_code >= 500
        raise AIError(f"análise HTTP {r.status_code}: {r.text[:300]}", transient=transient, status=r.status_code)
    data = r.json()
    env_err = _kie_envelope_error(data)
    if env_err:
        # kie 200-com-erro: "model not supported" etc. Não-transitório (config errada).
        raise AIError(f"análise (envelope kie): {env_err}", transient=False, status=200, raw=data)
    return data
