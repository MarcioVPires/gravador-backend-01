"""Escada de fallback do `ai_services` (DEC-021/022).

Nível 1 (pré-chamada): elegibilidade por `limitation`. No v1 só o GATE DE TAMANHO
(>= 24,9 MB → key com teto de 25 MB é inelegível → pula). Nível 2 (pós-chamada) e o avanço de
`current_priority` moram no worker (in-process), usando a escada que este módulo monta.
"""

# ~24,9 MB — fonte ÚNICA do corte (DEC-021/023). Acima disso, sem barreira elegível no v1.
SIZE_GATE_BYTES = 24_900_000


def _service_file_cap_bytes(service: dict) -> int | None:
    """Teto de tamanho de arquivo (bytes) do serviço, do `limitation` conforme o tier. None = sem teto conhecido."""
    limitation = service.get("limitation") or {}
    tier = service.get("account_tier") or "free"
    caps = limitation.get(tier) or limitation.get("free") or limitation.get("paid") or {}
    file_mb = caps.get("file_mb")
    return int(file_mb) * 1_000_000 if file_mb else None


def is_eligible(service: dict, size_bytes: int | None) -> tuple[bool, str | None]:
    """Nível 1. Devolve (elegível, motivo_da_inelegibilidade)."""
    if size_bytes is None:
        return True, None  # tamanho desconhecido → tenta (degrada no 413, cai no fallback)
    cap = _service_file_cap_bytes(service)
    if cap is not None and size_bytes > cap:
        return False, f"arquivo {size_bytes}B > teto {cap}B ({service.get('provider')}/{service.get('key_env')})"
    # margem única do projeto: ≥24,9 MB não passa em key de teto 25 MB
    if size_bytes >= SIZE_GATE_BYTES and (cap is None or cap <= 25_000_000):
        return False, f"arquivo {size_bytes}B ≥ gate {SIZE_GATE_BYTES}B"
    return True, None


def eligible_from(services: list[dict], start_priority: int, size_bytes: int | None) -> list[dict]:
    """Escada elegível a partir de `current_priority` (inclusive), já ordenada por priority."""
    out = []
    for s in services:
        if s["priority"] < start_priority:
            continue
        ok, _ = is_eligible(s, size_bytes)
        if ok:
            out.append(s)
    return out
