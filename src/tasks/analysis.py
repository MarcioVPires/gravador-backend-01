"""Análise — LLM OpenAI-compat (DEC-025). ESQUELETO — Etapa 5.

Monta o prompt a partir dos blocos (`prompts.blocks`) + placeholders (transcrição,
observação, título, tags existentes), chama o modelo, valida o output estruturado e grava.
"""

# TODO(Etapa 5):
#   - montar prompt: filtrar blocks por `when` → substituir <placeholder-...> → concatenar.
#   - chamar (ai_client) com schema nativo onde houver + bloco `output` sempre.
#   - validar { titulo, resumo, content, tags_selecionadas, tags_sugeridas }; malformado = retry imediato.
#   - escrever reports (relatorio_md + raw_response) + recordings.titulo/resumo;
#     criar tags (source='ai', normalizeTagName) + recording_tags; setar status='done' (DEC-022).
#   - registrar processing_jobs (+ prompt_id) + ai_usage (tokens; DEC-024).
