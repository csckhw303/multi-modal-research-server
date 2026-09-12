# Multi-Modal Research — Server

FastAPI backend for a multi-modal RAG (Retrieval-Augmented Generation) research
tool. A user creates a **project** — a self-contained research domain — and
gathers information into it — uploaded documents, or URLs to scrape (currently
unavailable: the ScrapingBee API key has expired) — as their source material. The server
ingests and chunks that material, generates embeddings, and lets the user
**research over the project** by chatting with it: questions are answered using a
hybrid vector + keyword search pipeline over only that project's documents, with
cited sources pointing back to the original content.

## Architecture

- **API**: FastAPI (`src/server.py`), routes under `/api/user`, `/api/projects`, `/api/chats`.
- **Auth**: Clerk (`src/services/clerkAuth.py`). The frontend attaches a Clerk JWT;
  the server verifies it and creates local user records via a Clerk webhook
  (`POST /api/user/create`) on `user.created` events.
- **Database**: Postgres + pgvector, accessed through PostgREST via the
  `supabase-py` client (`src/services/supabase.py`) — no ORM, calls are
  `supabase.table(...)` / `supabase.rpc(...)`.
- **Async ingestion**: Celery worker (`src/services/celery.py`) backed by Redis,
  runs the document pipeline (partition → chunk → summarize → embed → store) via
  `src/rag/ingestion`.
- **Retrieval**: hybrid vector (pgvector HNSW) + keyword (Postgres full-text search)
  search, merged and reranked (`src/rag/retrieval`), used by an agent
  (`src/agents/supervisor_agent`) that can also call web search (Tavily) when needed.
- **Storage**: uploaded files live in S3; the server generates presigned URLs (or
  proxies uploads, depending on current config) rather than storing files itself.
- **Observability**: structured JSON logging (`structlog`) and LangSmith tracing
  for LLM calls.

## Requirements

- Python 3.11–3.13, [Poetry](https://python-poetry.org/)
- Redis (local via `server/radis/docker-compose.yml`, or hosted)
- A Postgres database with the `vector` and `pgcrypto` extensions and the schema in
  `supabase/migrations/`, fronted by PostgREST (see [Database / PostgREST](#database--postgrest))

## Setup

```bash
cd server
poetry install
cp .env.example .env   # fill in the values below
```

### Environment variables

| Variable | Purpose |
|---|---|
| `SUPABASE_API_URL` | Base URL of the PostgREST instance (Supabase project, or self-hosted) |
| `SUPABASE_SECRET_KEY` | Service-role key/JWT for that PostgREST instance |
| `CLERK_SECRET_KEY` | Clerk backend API key |
| `DOMAIN` | Frontend origin, used as Clerk's `authorized_parties` |
| `REDIS_URL` | Redis connection string (Celery broker) |
| `S3_BUCKET_NAME`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Document storage |
| `OPENAI_API_KEY`, `EMBEDDING_MODEL` | Embeddings + LLM calls |
| `COHERE_API_KEY` | Reranking |
| `SCRAPINGBEE_API_KEY` | Web scraping for URL-sourced documents *(current key has expired — needs renewal)* |
| `LANGSMITH_API_KEY`, `LANGSMITH_TRACING_V2`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` | LLM tracing |
| `TAVILY_API_KEY` *(optional)* | Web search tool for the agent |

### Run locally

Three processes, each in its own terminal (or use the scripts at the repo root):

```bash
./start_redis.sh    # Redis via Docker
./start_server.sh   # FastAPI on :8000 (uvicorn --reload)
./start_worker.sh   # Celery worker
```

API docs are available at `http://localhost:8000/docs` once running.

## Database / PostgREST

The app never opens a raw Postgres connection — every query goes through PostgREST.
Apply the schema in `supabase/migrations/` (tables, `pgvector` HNSW index, and the
`vector_search_document_chunks` / `keyword_search_document_chunks` SQL functions) to
whatever Postgres instance you point `SUPABASE_API_URL` at. If self-hosting
PostgREST (rather than using Supabase directly), you also need the
`anon`/`authenticated`/`service_role`/`authenticator` roles PostgREST expects, and
a thin reverse proxy in front of it that maps `/rest/v1/*` → `/*`, since the
Supabase client library always calls that path prefix.

## Deployment

Currently deployed on Railway as three services from this directory: `api`
(`uvicorn`), `worker` (`celery`), plus a self-hosted Postgres/PostgREST backend
(see above). A legacy AWS ECS/CloudFront setup also exists under
`src/cloudformation/` but is not the active deployment path.
