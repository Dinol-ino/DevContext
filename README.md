# DevContextIQ

**Unified Engineering Intelligence Platform**

A production-ready system that transforms scattered engineering data—pull requests, incident logs, architecture documents—into a structured knowledge graph, enabling engineers to query institutional knowledge conversationally while automatically enforcing architectural decisions on new code.

## The Problem

Engineering teams face two critical knowledge gaps:

- **Architectural Amnesia**: Design decisions live in old PRs, Slack threads, and senior engineers' heads. New developers repeat mistakes or interrupt seniors for answers.
- **Operational Fragmentation**: Runbooks, alerts, and incident playbooks spread across five tools. On-call engineers context-switch under pressure and miss architectural constraints.

DevContextIQ solves both with a unified system deployable on any GitHub-based engineering team.

## Core Features

| Feature | Benefit |
|---------|---------|
| **Conversational Context Agent** | Query architectural decisions and decisions in natural language—get sources, confidence scores, and related context in seconds |
| **Governance Bot** | Automatically catch architectural violations in PRs before merge—no human review needed |
| **Incident Response Agent** | Structured incident answers: issue summary, root cause hypothesis, numbered fix steps, and architectural warnings |
| **Knowledge Graph** | Nodes (decisions, files, people, incidents) + edges (supports, conflicts, supersedes) enable semantic reasoning |
| **Vector Search** | pgvector semantic search finds relevant decisions even when exact keywords don't match |

## Architecture

Five-layer stack built entirely on free and open-source tools:

```
Layer 5: Frontend (React + Vite on Vercel)
         ↓
Layer 4: Agent Backend (FastAPI on Render)
         ↓
Layer 3: LLM Orchestration (Gemini API)
         ↓
Layer 2: Vector + Graph DB (Supabase + pgvector)
         ↓
Layer 1: Data Ingestion (GitHub Actions)
```

### Tech Stack

- **Database**: Supabase (PostgreSQL) + pgvector (semantic search)
- **Backend**: FastAPI (Python) on Render
- **Frontend**: React with Vite on Vercel
- **LLM**: Google Gemini (text-embedding-004 for vectors, Gemini 2.0 Flash for agents)
- **Ingestion**: GitHub Actions + Python scripts
- **Auth**: Supabase + Google OAuth 2.0

**Zero paid services required.** All tiers are free for development and demo use.

## Quick Start

### Prerequisites

- GitHub repository
- Google account (for AI Studio)
- 30 minutes

### Setup (4 Steps)

#### 1. **Database Schema** (Supabase)

```bash
# Navigate to Supabase dashboard → SQL Editor → New Query
# Paste contents of schema.sql and execute
```

The schema creates:
- `nodes`: knowledge graph entities (decisions, files, people, incidents, ADRs)
- `edges`: relationships (supports, conflicts, caused_by, supersedes)
- `node_embeddings`: 768-dim vectors from Gemini text-embedding-004 with pgvector HNSW index

#### 2. **Environment Configuration**

Create `.env` in the `agents/` directory:

```env
GEMINI_API_KEY=your_key_here
SUPABASE_URL=your_project.supabase.co
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_key
RENDER_DEPLOYMENT_URL=https://your-app.onrender.com
```

#### 3. **Start Backend** (Render)

```bash
cd agents/
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

API available at `http://localhost:8000`

#### 4. **Start Frontend** (Vercel / Local)

```bash
cd frontend/
npm install
npm run dev
```

Visit `http://localhost:5173` to access the chat interface.

## API Endpoints

All responses include `sources` array with links to original PRs, ADRs, and incidents.

### POST /api/v1/ask
**Context Agent** — Answer architectural questions

```bash
curl -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Why is rate limiting at the API gateway?",
    "repo_id": "org/repo-name"
  }'
```

**Response:**
```json
{
  "answer": "Rate limiting is at the API gateway to prevent DB connection saturation — decision made after INC-0089 in August 2025.",
  "sources": [
    { "type": "pr", "label": "PR #245", "url": "github.com/.../pull/245" },
    { "type": "adr", "label": "ADR-003", "url": "..." },
    { "type": "incident", "label": "INC-0089", "url": "..." }
  ],
  "confidence": 0.91
}
```

### POST /api/v1/governance/check
**Governance Bot** — Detect architectural conflicts in PRs

Integrated into GitHub Actions. Automatically runs on new PRs. Returns:
- Conflicting decisions with links
- Suggested comment for PR
- Safe-to-merge boolean

### POST /api/v1/incident
**Incident Agent** — Structured incident response

```bash
curl -X POST http://localhost:8000/api/v1/incident \
  -H "Content-Type: application/json" \
  -d '{
    "alert_title": "Payment service error rate spike",
    "service_name": "payments",
    "error_snippet": "Too many connections to DB pool — max 100 exceeded"
  }'
```

**Response:**
```json
{
  "issue": "DB connection pool exhausted on payment service",
  "likely_cause": "Rate limiting missing on /payments/process endpoint",
  "fix_steps": [
    "1. Enable gateway rate limiting for /payments route",
    "2. Restart payment service pods",
    "3. Monitor DB connection count"
  ],
  "warnings": ["Do NOT move rate limiting into the service — see ADR-003"],
  "runbook_url": "confluence.../runbook-payments"
}
```

### GET /api/v1/health
Health check endpoint.

## Data Ingestion

#### GitHub PR Ingestion (GitHub Actions)

Triggered on PR merge. Workflow file: `.github/workflows/ingest.yml`

```yaml
# Extracts PR diff, title, author, date
# Calls Gemini Flash to extract decisions
# Writes nodes + edges to Supabase
# Generates embeddings via text-embedding-004
```

#### Manual Ingestion

For non-GitHub sources (runbooks, ADRs, incident reports):

```python
from ingestion.embed import ingest_document

ingest_document(
  content="Rate limiting prevents DB saturation...",
  doc_type="adr",
  metadata={
    "adr_id": "ADR-003",
    "date": "2025-08-14",
    "author": "rahul@company.com"
  }
)
```

## Database Schema

### nodes table

```sql
id          UUID           -- primary key
type        TEXT           -- 'decision' | 'file' | 'person' | 'incident' | 'adr'
label       TEXT           -- human-readable label
metadata    JSONB          -- flexible attributes
source_url  TEXT           -- GitHub PR, Confluence link, etc.
created_at  TIMESTAMPTZ    -- auto-populated
```

### edges table

```sql
from_node_id  UUID     -- source node
to_node_id    UUID     -- target node
relation      TEXT     -- 'supports' | 'conflicts' | 'caused_by' | 'supersedes'
created_at    TIMESTAMPTZ
```

### node_embeddings table

```sql
node_id       UUID
chunk         TEXT            -- text passage that was embedded
embedding     vector(768)     -- 768-dim vector from Gemini
```

**Vector Search Example:**

```sql
SELECT n.id, n.label, (1 - (ne.embedding <=> $1::vector)) AS similarity
FROM   node_embeddings ne
JOIN   nodes n ON n.id = ne.node_id
ORDER  BY ne.embedding <=> $1::vector
LIMIT  5;
```

## Project Structure

```
devcontextiq/
├── ingestion/
│   ├── ingest_pr.py              # GitHub PR → Gemini extraction → Supabase
│   ├── embed.py                  # Text → Gemini embeddings → pgvector
│   └── requirements.txt
│
├── agents/
│   ├── main.py                   # FastAPI entry point
│   ├── context_agent.py          # POST /ask handler
│   ├── governance_agent.py       # POST /governance/check handler
│   ├── incident_agent.py         # POST /incident handler
│   ├── tools.py                  # Gemini function-calling tools
│   ├── db.py                     # Supabase queries
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── Chat.tsx              # Chat UI component
│   │   └── api.ts                # API client
│   ├── vite.config.ts
│   └── package.json
│
├── .github/workflows/
│   ├── ingest.yml                # Triggered on PR merge
│   └── governance.yml            # Runs on new PRs
│
├── schema.sql                    # PostgreSQL schema + pgvector setup
├── seed_data.sql                 # Demo data
└── README.md
```

## Deployment

### Backend (Render)

1. Push `agents/` folder to GitHub
2. Create new Web Service on Render
3. Connect GitHub repo
4. Set runtime to Python 3.11
5. Build: `pip install -r requirements.txt`
6. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
7. Add env vars: `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`

**Note**: Free tier spins down after 15 minutes. Use UptimeRobot (free) to keep alive during presentation.

### Frontend (Vercel)

1. Push `frontend/` folder to GitHub
2. Create new Vercel project from GitHub repo
3. Framework preset: Vite
4. Add env vars: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_BASE`
5. Deploy

Auto-deploys on push to main.

## Use Cases

### For New Engineers
Query: *"Why is rate limiting at the gateway?"*
Result: Answer + links to PR #245, ADR-003, and the incident that triggered the decision.

### For Code Review
PR opens with rate limiting changes. GitHub bot comment: *"This conflicts with ADR-003. See PR #245 for the original decision."*

### For On-Call
Alert: Payment service error spike. Query: *"DB connections exhausted—what do I do?"*
Result: Issue summary, likely cause, numbered steps, architectural warnings.

## Performance

- **Semantic search**: <200ms (pgvector HNSW index)
- **Agent response**: 1–3s (Gemini function calling)
- **PR ingestion**: 30–60s (Gemini extraction + embedding)
- **Concurrent users**: 750 hrs/month free Render tier sufficient for 5–10 daily users

## Limitations & Trade-offs

| Feature | Status | Reason |
|---------|--------|--------|
| Temporal reasoning | Not implemented | Scope |
| Multi-repo graphs | Partial | Requires repo_id parameter per query |
| Role-based access control | Not implemented | Supabase RLS can be added |
| Batch PR ingestion | Not implemented | Use GitHub Actions cron job for weekly backfill |
| PII redaction | Not implemented | Add filtering in `embed.py` if needed |

## Contributing

1. Fork repository
2. Create feature branch
3. Test locally with `.env` file
4. Push to GitHub
5. Open PR with description of change

## License

MIT

## Authors

Built for Google Build for AI Hackathon, April 2026.

---

## Troubleshooting

**API returns 401 Unauthorized**
- Check Supabase JWT in Authorization header
- Verify SUPABASE_ANON_KEY matches `.env`

**Vector search returns no results**
- Confirm pgvector extension is enabled: `SELECT extname FROM pg_extension;`
- Check node_embeddings table is populated: `SELECT count(*) FROM node_embeddings;`
- Verify HNSW index exists: `SELECT indexname FROM pg_indexes WHERE tablename = 'node_embeddings';`

**Frontend can't reach backend**
- Confirm Render URL in `VITE_API_BASE` env var
- Check CORS headers in FastAPI: `allow_origins=["*"]` for development

**Render service spins down**
- Free tier auto-hibernates after 15 min of inactivity
- Use UptimeRobot (free) to ping `/health` endpoint every 10 min

**Gemini API returns rate limit error**
- Free tier: 60 requests per minute
- Add exponential backoff retry logic in agents
- For fallback we've used OpenRouter 

## Support

Open an issue on GitHub or email the team.
