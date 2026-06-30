"""Escada de fallback do `ai_services` (DEC-021). ESQUELETO — Etapa 5.

Nível 1 (pré-chamada): elegibilidade por `limitation`; no v1 só o GATE DE TAMANHO
(>= 24,9 MB → key com teto de 25 MB é inelegível → pula). Nível 2 (pós-chamada):
retry/avança `current_priority`.
"""

# ~24,9 MB — fonte ÚNICA do corte (DEC-021/023). Acima disso, sem barreira elegível no v1.
SIZE_GATE_BYTES = 24_900_000

# TODO(Etapa 5):
#   ler ai_services da task (enabled, ordenado por priority);
#   Nível 1: pular keys inelegíveis (gate de tamanho via recordings.size_bytes);
#   tentar a current_priority; ao esgotar N, avançar; ao esgotar todas, terminal (DEC-022).
