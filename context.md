# DevContextIQ - Project Overview

## 1. Project Summary

DevContextIQ is an AI-powered engineering intelligence platform that:

- Stores engineering knowledge from repositories and events
- Answers project questions using memory
- Analyzes pull request merge risk
- Analyzes incidents and outages
- Shows workspace integration health
- Uses FastAPI, Supabase, embeddings, and frontend UI

It can be described as:

**ChatGPT + GitHub Memory + DevOps Copilot**

---

## 2. Core Architecture

## Frontend

Currently running locally on:

http://localhost:5173

Likely built with:

- React
- Vite
- TypeScript

Frontend responsibilities:

- UI pages
- User inputs
- API calls
- Status checks
- Result rendering

## Backend

Backend is deployed and healthy.

Version shown:

- v2.0.0

API Base:

http://127.0.0.1:8001/api/v1

Likely backend stack:

- FastAPI
- REST APIs
- OpenAI / Hugging Face model calls
- Supabase database access

## Database

Using Supabase.

Main tables:

- nodes
- edges
- node_embeddings

---

## 3. Data Model Explanation

## nodes Table

Stores important entities.

Examples:

- Repo
- Author
- Decision
- Service
- Incident

Example:

| Type     | Label                |
|----------|----------------------|
| repo     | Dinol-ino/DevContext |
| author   | Dinol-ino            |
| decision | approved             |

## edges Table

Stores relationships between nodes.

Examples:

- belongs_to_repo
- owned_by_author
- related_to_incident

Example:

| From     | To     | Relation         |
|----------|--------|------------------|
| decision | repo   | belongs_to_repo  |
| decision | author | owned_by_author  |

## node_embeddings Table

Stores vector embeddings of engineering memory chunks.

Used for:

- Semantic search
- Retrieval-Augmented Generation (RAG)
- Context retrieval

---

## 4. Main Features

## 4.1 Chat Assistant

Allows users to ask questions about engineering memory.

Examples:

- Explain auth architecture
- What changed recently?
- Who approved PR?
- Show backend decisions

### How It Works

1. Frontend sends question
2. API call to `/api/v1/ask`
3. Backend searches embeddings
4. Fetches relevant nodes
5. Builds context
6. Sends to LLM
7. Returns final answer

This is a **RAG system**.

---

## 4.2 Governance Check

PR merge risk analyzer.

Inputs:

- PR URL
- Diff text

Outputs:

- Safe to merge or not
- Risk level
- Conflicts
- Review recommendation

Endpoint:

`POST /api/v1/governance/check`

### Use Cases

- Reviewers
- Engineering managers
- CI gatekeeping

---

## 4.3 Incident Analysis

Analyzes production alerts and failures.

Inputs:

- Alert title
- Service name
- Error snippet

Outputs:

- Likely cause
- Severity
- Suggested actions
- Warnings

Endpoint:

`POST /api/v1/incident`

Example:

Input:

Too many DB connections

Possible Output:

- Connection leak
- Pool saturation
- Restart workers
- Inspect ORM sessions

---

## 4.4 Workspace Settings

Shows integration health.

Current examples:

- Repo selected
- Backend healthy
- Auth config
- API base

Future additions:

- GitHub Connect
- Billing
- Slack Bot
- Organization Memory

---

## 5. API Endpoints

## Health Check

`GET /api/v1/health`

Example Response:

```json
{
  "status": "healthy",
  "version": "2.0.0"
}