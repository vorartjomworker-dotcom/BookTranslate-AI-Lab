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

## Roadmap

- Stage 1: document management and parsing
- Stage 2: translation engine and QA flow
- Stage 3: professional translation platform

## License

MIT
