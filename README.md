# api-processamento (back-p)

Back de processamento do **Gravador** — API standalone (FastAPI, Python) no **Google Cloud Run**.
Lê gravações pendentes no **mesmo Supabase** do front (service_role), **transcreve** (Groq/Whisper)
e **analisa** (LLM) gerando relatório/título/resumo/tags, e atualiza o `status`.

> Conceito e decisões: `../../.projeto/conceitual/back-processamento.md` + `decisoes/` **DEC-019..026**.
> Raciocínio das escolhas: `../../.projeto/discussions/2026-06-30-stack-infra-gatilho-back-p.md`.

## Estado
**Etapa 4 (deploy inicial) — esqueleto mínimo.** Prova o mecanismo *webhook → Cloud Run → DB*.
O processamento real (transcrição/análise/fallback) está **stubado** com `TODO(Etapa 5)`.

## Mecanismo (DEC-020)
Supabase dispara um **Database Webhook no INSERT de `recordings`** → `POST /process`. O back-p
garante a task durável (`processing_tasks`, idempotente) e **drena tudo que está pendente**.
**Sem scheduler/poll**; retry é **in-process**; só acorda quando há trabalho.

## Estrutura
```
src/
  main.py        FastAPI: /health, /process (webhook)
  config.py      env (DB url, webhook secret, concorrência)
  db.py          Postgres async (psycopg3 + pool; prepare_threshold off p/ o pooler)
  worker.py      drena processing_tasks (claim/dispatch = Etapa 5)
  ai_client.py   cliente OpenAI-compat uniforme (Etapa 5)
  fallback.py    escada ai_services: Nível 1 (gate tamanho) + Nível 2 (Etapa 5)
  tasks/transcription.py · tasks/analysis.py   (Etapa 5)
supabase/migrations/0001_backp_init.sql   schema do back-p (aplicado)
Dockerfile · requirements.txt · .env.example
```

## Rodar local
```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # preencher SUPABASE_DB_URL (pooler) + WEBHOOK_SECRET
uvicorn src.main:app --reload --port 8080
# GET http://localhost:8080/health
```

## Deploy (Cloud Run, from source)
```bash
gcloud run deploy api-processamento --source . --region us-central1 \
  --min-instances=0 --max-instances=1 --concurrency=1 \
  --memory=512Mi --timeout=3600 --allow-unauthenticated \
  --set-env-vars=MAX_CONCURRENCY=1   # demais segredos via --set-env-vars / Secret Manager
```
Config alvo (DEC-019): `min=0 / max=1 / concurrency=1 / 512MiB→1GiB / timeout 3600s`.

## Segredos
Nunca no git/DB. `.env` local (ignorado) e env do Cloud Run. Chaves de IA: nomes batem com
`ai_services.key_env` (DEC-021); valores no `chaves.md` do hub (não-git).
