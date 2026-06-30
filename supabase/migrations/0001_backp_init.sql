-- ============================================================================
-- Back de processamento (app/api-processamento) — migration inicial
-- Aplicada de forma ADITIVA ao MESMO projeto Supabase do front (DEC-019).
-- O back-p é DONO destas mudanças (convenção de setup, 2026-06-30): todas tocam
-- tabelas que o FRONT NÃO usa (novas: ai_services/processing_tasks/prompts;
-- alteradas: model_prices/ai_usage/processing_jobs — o front nunca as lê).
-- Tabelas VAZIAS → drops de coluna são seguros (sem perda de dado).
-- Compila: DEC-021 (ai_services/fallback), DEC-022 (processing_tasks/estado),
--          DEC-024 (custos jsonb), DEC-025 (prompts).
-- Posture de segurança = igual ao front: RLS habilitada, SEM policies → acesso
-- só por service_role (o back-p usa service_role).
-- ============================================================================

-- ---------------------------------------------------------------------------
-- ai_services — registry de serviços de IA chamáveis (DEC-021)
-- 1 linha = (task, provider, model, key_env) numa priority. A identidade inclui
-- a CHAVE (key_env): fallback pode ser provedor OU chave diferente.
-- ---------------------------------------------------------------------------
create table ai_services (
  id            uuid primary key default gen_random_uuid(),
  task          text not null check (task in ('transcription','report')),
  provider      text not null,
  model         text not null,
  key_env       text not null,              -- NOME da var de env da chave (nunca o valor)
  base_url      text,
  priority      integer not null,           -- 0 = padrão; fallback ascendente; escopado por task
  enabled       boolean not null default true,
  account_tier  text not null check (account_tier in ('free','paid')),
  limitation    jsonb,                       -- limites por tier: { free:{file_mb,rpm,...}, paid:{...} }
  config        jsonb,                       -- params do body (language/response_format/temperature/json_schema...)
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (task, priority)                    -- 1 serviço por (task, priority)
);
alter table ai_services enable row level security;

-- ---------------------------------------------------------------------------
-- processing_tasks — registro de atividades / máquina de estados (DEC-022)
-- "A fila é uma QUERY": WHERE state='pending' AND next_attempt_at<=now() ORDER BY next_attempt_at.
-- 1 linha por (recording, task). current_priority é PERSISTIDO (crash-resumível).
-- ---------------------------------------------------------------------------
create table processing_tasks (
  id               uuid primary key default gen_random_uuid(),
  recording_id     uuid not null references recordings(id) on delete cascade,
  workspace_id     uuid not null references workspaces(id) on delete cascade,
  task             text not null check (task in ('transcription','report')),
  state            text not null default 'pending' check (state in ('pending','running','done','failed')),
  attempt_count    integer not null default 0,
  next_attempt_at  timestamptz not null default now(),
  current_priority integer not null default 0,  -- ponteiro na escada do ai_services daquela task
  last_error       text,
  claimed_at       timestamptz,                 -- claim/lock (anti-duplo-processamento)
  claimed_by       text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (recording_id, task)                   -- 1 task por (gravação, tipo)
);
-- índice da "fila": pega o que está pronto pra rodar, mais antigo primeiro
create index processing_tasks_queue_idx on processing_tasks (state, next_attempt_at);
alter table processing_tasks enable row level security;

-- ---------------------------------------------------------------------------
-- prompts — prompts como DADO versionado no DB (DEC-025)
-- 1 ativo por task garantido pelo banco (índice único parcial). Estrutura = array
-- ordenado de blocos {key,text,when?} em jsonb; o back-p monta o prompt a partir deles.
-- ---------------------------------------------------------------------------
create table prompts (
  id          uuid primary key default gen_random_uuid(),
  task        text not null check (task in ('transcription','report')),
  name        text,                            -- rótulo/versão legível (ex.: "analise-v2")
  blocks      jsonb not null,                  -- [{ key, text, when? }, ...] na ordem de montagem
  active      boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
-- no máximo 1 ativo por task
create unique index prompts_one_active_per_task on prompts (task) where active;
alter table prompts enable row level security;

-- ---------------------------------------------------------------------------
-- model_prices — rate card modular por kind (DEC-024)
-- pricing jsonb SUBSTITUI price_in/price_out. (tabela vazia → drop seguro)
-- ---------------------------------------------------------------------------
alter table model_prices add column pricing jsonb;  -- { "kind":"per_1m_tokens", "input":..., "output":... } | { "kind":"per_audio_minute", "rate":... }
alter table model_prices drop column price_in;
alter table model_prices drop column price_out;

-- ---------------------------------------------------------------------------
-- ai_usage — snapshot CONGELADO (DEC-024)
-- usage (quantidades) e pricing_snapshot (cópia da pricing usada) viram jsonb;
-- as colunas escalares antigas saem. cost_total/currency permanecem (estruturados p/ agregar).
-- ---------------------------------------------------------------------------
alter table ai_usage add column usage           jsonb;  -- análise:{input_tokens_estimated,input_tokens_real,output_tokens,cached_input_tokens} | transcrição:{audio_seconds}
alter table ai_usage add column pricing_snapshot jsonb;  -- cópia da model_prices.pricing usada no momento
alter table ai_usage drop column input_tokens_estimated;
alter table ai_usage drop column input_tokens_real;
alter table ai_usage drop column output_tokens;
alter table ai_usage drop column price_in;
alter table ai_usage drop column price_out;

-- ---------------------------------------------------------------------------
-- processing_jobs — detalhe da tentativa por CHAMADA (DEC-022/DEC-025)
-- ganha error/raw da tentativa, vínculo com a task, e o prompt usado (auditoria).
-- ---------------------------------------------------------------------------
alter table processing_jobs add column error     text;
alter table processing_jobs add column raw       jsonb;                                        -- raw de FALHA/malformado mora aqui (sucesso vai p/ reports.raw_response)
alter table processing_jobs add column task_id   uuid references processing_tasks(id) on delete set null;
alter table processing_jobs add column prompt_id uuid references prompts(id) on delete set null;  -- versão do prompt usada (null em transcription)
