"""Cálculo de custo por `kind` (DEC-024). Forma nova = novo kind + nova função aqui."""


def compute_cost(pricing: dict | None, usage: dict) -> float:
    """Custo em USD a partir do rate card (pricing) e das quantidades (usage)."""
    if not pricing:
        return 0.0
    kind = pricing.get("kind")
    if kind == "per_1m_tokens":
        i = usage.get("input_tokens_real") or usage.get("input_tokens_estimated") or 0
        o = usage.get("output_tokens") or 0
        c = usage.get("cached_input_tokens") or 0
        return (i * pricing.get("input", 0) + o * pricing.get("output", 0)
                + c * pricing.get("cached_input", 0)) / 1_000_000
    if kind == "per_audio_minute":
        secs = usage.get("audio_seconds") or 0
        return (secs / 60.0) * pricing.get("rate", 0)
    return 0.0
