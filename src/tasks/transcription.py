"""Transcrição — Groq `whisper-large-v3-turbo` (DEC-023). ESQUELETO — Etapa 5.

Usa `verbose_json` e deriva `srt` + `texto` + `idioma` numa só chamada. Upsert em
`transcriptions` (1:1 por gravação). Ao concluir, habilita a task de análise (DEC-022).
"""

# TODO(Etapa 5):
#   - resolver provedor/key via fallback (DEC-021); gate de tamanho (size_bytes).
#   - chamar audio/transcriptions (ai_client) com response_format=verbose_json, language=pt.
#   - derivar srt+texto+idioma dos segmentos; upsert transcriptions on conflict (recording_id).
#   - registrar processing_jobs + ai_usage (audio_seconds; DEC-024).
