# BookTranslate AI Lab

A production-oriented AI translation lab for technical books, combining document ingestion, chapter segmentation, AI translation pipelines, QA evaluation, and background processing.

## Overview

This project is designed to support a complete workflow:

- upload DOCX and EPUB documents
- parse and segment chapter content
- translate text through multiple AI providers
- score output quality with QA checks
- manage translation jobs in Redis/async workers
- persist all metadata in PostgreSQL

## AI Translation Layer

PR #5 adds a durable translation job orchestration layer on top of the provider abstraction from PR #4. The queue is intentionally lightweight: PostgreSQL owns the job state, while Redis Streams carries only the minimal work payload for async execution.

### Supported providers
- OpenAI via async client with optional `OPENAI_BASE_URL` override for OpenAI-compatible APIs
- Anthropic via async Messages API
- DeepL via HTTPX with free/pro endpoint selection

### Core rules
- One common `TranslationRequest` and `TranslationResult` contract
- Shared prompt builder with injection-safe instructions
- Provider selection is explicit and lazy
- No automatic fallback across paid providers
- Timeout and retry are handled centrally in `TranslationService`
- PostgreSQL keeps the source-of-truth job status and denies duplicate active jobs per segment
- Redis Streams provides a consumer-group queue with DLQ-friendly handling for retries and poison messages
- API keys remain environment-only values and are never logged or exposed in errors

## Architecture

### Backend
- FastAPI
- PostgreSQL + SQLAlchemy
- Redis for job queue and cache
- Async workers for processing translation jobs

### Frontend
- Next.js
- React
- TypeScript

### AI layer
- OpenAI
- Anthropic
- DeepL
- provider abstraction layer

## Repository structure

```text
BookTranslate-AI-Lab/
├── backend/
│   ├── app/
│   │   ├── ai/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── services/
│   │   ├── workers/
│   │   ├── __init__.py
│   │   ├── db.py
│   │   ├── main.py
│   │   └── redis_client.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── tests/
├── frontend/
│   ├── app/
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   └── next-env.d.ts
├── .env.example
├── docker-compose.yml
├── .gitignore
├── README.md
└── LICENSE
```

## Quick start

### 1. Configure environment

Copy the example environment file:

```bash
cp .env.example .env
```

Update API keys as needed for your chosen providers.

### 2. Start the stack

```bash
docker compose up --build
```

This starts:
- frontend on http://localhost:3000
- backend on http://localhost:8000
- PostgreSQL on localhost:5432
- Redis on localhost:6379

### 3. Verify backend health

```bash
curl http://localhost:8000/health
```

## Development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Environment variables

See [.env.example](.env.example) for the supported settings.

Key AI settings:

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o
OPENAI_BASE_URL=
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-3-5-sonnet-20240620
DEEPL_API_KEY=
DEEPL_USE_PRO=false
DEFAULT_AI_PROVIDER=openai
DEFAULT_AI_MODEL=gpt-4o
TRANSLATION_TIMEOUT=30
MAX_RETRIES=3
```

PR #5 implements the queue orchestration layer: segment translation jobs are persisted in PostgreSQL, queued to a Redis Streams consumer group, and processed by the async translator worker. The worker records durable job status and updates segment translation fields only after provider success.

## Implementation Status

### ✅ Translation workspace and operational platform

#### Implemented
- **FastAPI CRUD API** for books, chapters, segments, translation jobs, and quality reports
- **DOCX and EPUB ingestion** with validation, parsing, deterministic segmentation, and PostgreSQL persistence
- **Provider abstraction** for OpenAI, Anthropic, and DeepL
- **Durable translation job orchestration** backed by PostgreSQL and Redis Streams
- **Async worker processing** with retry, idempotency, reclaim, and stale-response protection
- **Canonical QA evaluation** and quality reporting with deterministic/full evaluation modes
- **Benchmark execution engine** for dry-run provider comparison
- **Frontend operational workspace** for Books, Translation Jobs, Quality, and Benchmarks
- **Translation Editor workflow** for manual segment translation review and save
- **Health check and deployment-safe operational endpoints** for database and Redis status
- **Testing framework** with async and frontend coverage

#### Current positioning
This project is a production-oriented advanced MVP / pre-production platform for technical book translation. It includes the major operational and AI orchestration layers, but deployment hardening, production observability, auth, backup strategy, and full production-grade operational validation remain follow-up work outside this scope.

## API usage

### Upload a document

```bash
curl -X POST "http://localhost:8000/api/v1/books/upload" \
  -F "file=@/path/to/chapter.docx" \
  -F "title=Example Book" \
  -F "author=Jane Author" \
  -F "language=en" \
  -F "description=Example description"
```

Supported extensions:
- `.docx`
- `.epub`

Maximum upload size: 25 MB

Success response example:

```json
{
  "book": {
    "id": 1,
    "title": "Example Book",
    "author": "Jane Author",
    "file_path": "9f1d1a6b6d514c45af4d2f8d4fdbaf18.docx",
    "file_type": "docx",
    "language": "en",
    "status": "parsed"
  },
  "chapters_count": 2,
  "segments_count": 12
}
```

Possible error responses:
- `413` payload_too_large for oversized uploads
- `415` unsupported_media_type for unsupported extensions
- `422` validation_error for empty or invalid files, traversal issues, or unreadable documents

### 🚀 Quick Start - Development

#### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Start development server
uvicorn app.main:app --reload
```

#### Frontend

```bash
cd frontend
npm install
npm run dev
```

#### Testing

```bash
cd backend
pytest tests/ -v
```

### 🐳 Docker Compose

```bash
# Copy environment template
cp .env.example .env

# Start all services
docker compose up --build

# Verify health
curl http://localhost:8000/health
```

## Architecture Notes

### Current Implementation
- **Backend**: FastAPI with SQLAlchemy async ORM
- **Database**: PostgreSQL with Alembic migrations
- **Cache/Queue**: Redis (via async Python client and RQ)
- **Frontend**: Next.js 15 with React 19 and TypeScript
- **Workers**: Async background workers for job processing

### Design Decisions
- Async/await throughout for non-blocking I/O
- SQLAlchemy 2.0 with type hints for model safety
- Pydantic v2 for configuration validation
- Separate worker process for long-running jobs
- Database migrations versioned with Alembic for team collaboration

## Roadmap

- Stage 1: document management and parsing
- Stage 2: translation engine and QA flow
- Stage 3: professional translation platform

## License

MIT
