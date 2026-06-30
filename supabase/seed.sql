-- Seed das tabelas de config do back-p (DEC-023 ai_services / DEC-024 model_prices).
-- SEM segredos: key_env guarda só o NOME da var de env (o valor vive no env do Cloud Run / chaves.md).
-- Rodar uma vez em tabela vazia (ai_services tem guard por (task,priority); model_prices não).

-- ai_services — escadas de fallback (priority 0 = padrão; ascendente)
insert into ai_services (task, provider, model, key_env, base_url, priority, account_tier, limitation, config) values
('transcription','groq','whisper-large-v3-turbo','GROQ_LEARION','https://api.groq.com/openai/v1',0,'free','{"free":{"file_mb":25,"rpm":20,"rpd":2000,"audio_sec_hora":7200,"audio_sec_dia":28800}}','{"language":"pt","response_format":"verbose_json"}'),
('transcription','groq','whisper-large-v3-turbo','GROQ_GERALDO','https://api.groq.com/openai/v1',1,'free','{"free":{"file_mb":25,"rpm":20,"rpd":2000,"audio_sec_hora":7200,"audio_sec_dia":28800}}','{"language":"pt","response_format":"verbose_json"}'),
('transcription','groq','whisper-large-v3-turbo','GROQ_LENDARIO','https://api.groq.com/openai/v1',2,'free','{"free":{"file_mb":25,"rpm":20,"rpd":2000,"audio_sec_hora":7200,"audio_sec_dia":28800}}','{"language":"pt","response_format":"verbose_json"}'),
('transcription','groq','whisper-large-v3-turbo','GROQ_MARCIO','https://api.groq.com/openai/v1',3,'free','{"free":{"file_mb":25,"rpm":20,"rpd":2000,"audio_sec_hora":7200,"audio_sec_dia":28800}}','{"language":"pt","response_format":"verbose_json"}'),
('transcription','openai','whisper-1','OPENAI_EVERTON','https://api.openai.com/v1',4,'paid','{"paid":{"file_mb":25}}','{"language":"pt","response_format":"verbose_json"}'),
('report','openai','gpt-5-mini','OPENAI_EVERTON','https://api.openai.com/v1',0,'paid',null,'{"temperature":0.3}'),
('report','google','gemini-2.5-flash','GOOGLE_EVERTON','https://generativelanguage.googleapis.com/v1beta/openai/',1,'paid',null,'{"temperature":0.3}'),
('report','kie','gemini-3-flash-openai','KIE_LEARION','https://api.kie.ai/api/v1',2,'paid',null,'{"temperature":0.3}')
on conflict (task, priority) do nothing;

-- model_prices — rate card modular por kind (preços conferidos pelo dono 2026-06-30)
insert into model_prices (provider, model, pricing) values
('groq','whisper-large-v3-turbo','{"kind":"per_audio_minute","rate":0.000667}'),
('openai','whisper-1','{"kind":"per_audio_minute","rate":0.006}'),
('openai','gpt-5-mini','{"kind":"per_1m_tokens","input":0.25,"output":2.00}'),
('google','gemini-2.5-flash','{"kind":"per_1m_tokens","input":0.30,"output":2.50}'),
('kie','gemini-3-flash-openai','{"kind":"per_1m_tokens","input":0.15,"output":0.90}');

-- NOTA: a 1ª versão dos PROMPTS (tabela prompts) é escrita no início da Etapa 5 (dev),
-- junto da implementação da análise (DEC-025). Não seedada aqui de propósito.
