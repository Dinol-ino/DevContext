# DevContextIQ Manual

## A. What Is DevContextIQ
DevContextIQ is an engineering memory platform that ingests GitHub activity into a Supabase graph and answers technical questions through FastAPI agents powered by OpenRouter models.

## B. Problem Solved
Engineering teams lose decision context over time. DevContextIQ preserves architectural decisions, change history, and incident knowledge so teams can retrieve rationale quickly and enforce standards during delivery.

## C. How It Works
1. GitHub repository events are sent to the webhook endpoint.
2. Ingestion normalizes events, extracts decisions and ADRs, and stores nodes, edges, and embeddings in Supabase.
3. Agents retrieve evidence from graph + lexical + vector context.
4. `/api/v1/ask` returns an answer with confidence, sources, and model used.
5. `/api/v1/governance/check` detects change conflicts with stored decisions.
6. `/api/v1/incident` returns structured incident guidance.

## D. User Flow
1. Deploy project services.
2. Connect GitHub webhook to ingestion.
3. Push code or merge PRs.
4. Events are ingested into Supabase graph memory.
5. Ask architectural questions via API.
6. Governance checks run on PR changes.
7. Incident analysis uses historical graph evidence.

## E. Architecture Diagram 
```text
+------------------+       webhook        +-------------------------+
|   GitHub Repo    | -------------------> | Ingestion (FastAPI)     |
| push / PR / ADR  |                      | /github-webhook         |
+------------------+                      +-----------+-------------+
                                                      |
                                                      | nodes, edges, embeddings
                                                      v
                                         +---------------------------+
                                         | Supabase Graph + pgvector |
                                         +------------+--------------+
                                                      |
                                                      | retrieval
                                                      v
                                  +------------------------------------------+
                                  | Agents API (FastAPI)                     |
                                  | /api/v1/ask                              |
                                  | /api/v1/governance/check                 |
                                  | /api/v1/incident                         |
                                  +-------------------+----------------------+
                                                      |
                                                      v
                                           Answers + confidence + sources
```

## F. API Endpoints

### Ingestion
- `POST /github-webhook`
- `GET /health`

### Agents
- `POST /api/v1/ask`
- `POST /api/v1/governance/check`
- `POST /api/v1/incident`

## G. Environment Variables
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `OPENROUTER_API_KEY`
- `GITHUB_WEBHOOK_SECRET`
- `FRONTEND_ORIGINS` (optional, comma-separated CORS overrides)
- `MODEL_NAME` (optional OpenRouter model override)

## H. Future Improvements
- Slack bot integration
- Jira integration
- Code diff embeddings
- PR auto reviewer
- Multi-repo organization memory




