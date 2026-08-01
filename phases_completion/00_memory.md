# DevContextIQ — Project Memory

## Project Overview
- **Project Name:** DevContextIQ
- **Purpose:** Engineering Context & Repository RAG Memory System
- **Problem Statement:** Engineering knowledge (ADRs, design decisions, incident postmortems, commit rationale, developer onboarding steps, historical timelines) gets lost across commits, PRs, and team turnover.
- **Core Vision:** A developer intelligence platform that indexes code, PR decisions, ADRs, commit intelligence, onboarding guides, timelines, and incidents into a queryable graph + vector memory layer with persistent conversation history.
- **Target Users:** Developers, Tech Leads, Engineering Managers, DevSecOps, New Hires.

## Technical Architecture Stack
- **Backend Framework:** FastAPI (Python 3.10+) running on Render / localhost
- **Frontend Stack:** React 18 + TypeScript + Vite + Vanilla CSS (Dark theme with glassmorphism)
- **Database:** Supabase PostgreSQL with `pgvector` extension & HNSW vector indexing (`vector(384)`)
- **Authentication:** Supabase Auth (JWT email/password, OAuth support) + backend JWT verification middleware
- **Embedding Model:** Local `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions)
- **LLM Provider:** OpenRouter API (`deepseek/deepseek-chat`)
- **Ingestion & Agents:** GitHub Webhooks + Code Chunker AST parser + Commit Agent + Onboarding Agent + Timeline Agent + GitHub Actions workflows

## Database Schema & Models
- `nodes`: UUID primary key, type (repo, decision, adr, service, author, event, commit), label, metadata JSONB, source_url, created_at, updated_at
- `edges`: from_node_id, to_node_id, relation (belongs_to_repo, owned_by_author, affects_service, contains_adr, authored_commit)
- `node_embeddings`: node_id (FK), chunk TEXT, embedding vector(384) with HNSW cosine index (`idx_node_embeddings_hnsw`)
- `user_auth_events`: audit trail for user registration and login events
- `chat_threads`: persistent conversation threads (`id`, `user_id`, `repo_id`, `title`, `created_at`, `updated_at`)
- `chat_messages`: thread message store (`id`, `thread_id`, `role`, `content`, `confidence`, `sources`, `used_model`, `created_at`)

## Completed Roadmap Progress (8 / 8 Phases Complete — 100%)
- **Phase 1 (Repository Stabilization):** 100% Complete — Webhook HMAC verification, vector dimension alignment (384), JWT auth middleware.
- **Phase 2 (Repository Intelligence):** 100% Complete — Repository cloning, tree traversal, technology/framework stack detection, metadata storage.
- **Phase 3 (Repository Understanding):** 100% Complete — Code chunking engine (`chunker.py`), repo-level embeddings (`embed_repo.py`), native `pgvector` HNSW search (`match_embeddings` RPC), `repo_id` multi-repository scoping.
- **Phase 4 (Persistent Memory & Dynamic Intelligence):** 100% Complete — Database-backed multi-thread chat history, thread CRUD API, auto-persistence of Q&A in `context_agent`, dynamic governance rule evaluation, dynamic incident RAG analysis.
- **Phase 5 (Commit Intelligence):** 100% Complete — Commit Intelligence Agent (`agents/commit_agent.py`), commit diff architectural impact analysis (`/api/v1/commit/analyze`), commit history graph node integration (`type='commit'`), author/repo/service edge linking.
- **Phase 6 (Developer Onboarding):** 100% Complete — Developer Onboarding Assistant Agent (`agents/onboarding_agent.py`), role-tailored guide generation (`/api/v1/onboarding/guide`), repository overview & key entry points walkthrough (`/api/v1/onboarding/overview/{repo_id}`).
- **Phase 7 (Context Timeline):** 100% Complete — Context Timeline Agent (`agents/timeline_agent.py`), chronological event aggregation (`/api/v1/timeline/{repo_id}`), microservice event timeline (`/api/v1/timeline/service/{service_name}`).
- **Phase 8 (Final Polish & Production Readiness):** 100% Complete — Automated E2E verification suite (`test_e2e_phase8.py` — 5/5 PASSED), error handling sanitization, engineering memory synchronization across all 8 phases.

## Security & Protection Measures
- `slowapi` rate limiting (60 req/min default per IP)
- Sanitized exception handlers to prevent internal stack trace / credential leakage
- Strict JWT authentication on `/api/v1/auth/log`, commit analysis, onboarding, timeline, and repository/thread management routes
- HMAC SHA-256 webhook signature validation

## Project Status
- **Roadmap Completion:** 100% Complete (0 remaining phases)