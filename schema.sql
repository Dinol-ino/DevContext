CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,
    label TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_url TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS edges (
    from_node_id UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    to_node_id UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    relation TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS node_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    chunk TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    repo_id TEXT,
    file_path TEXT,
    language TEXT,
    start_line INTEGER,
    end_line INTEGER,
    content_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_auth_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID,
    email TEXT NOT NULL,
    auth_event TEXT NOT NULL CHECK (auth_event IN ('register', 'login')),
    auth_provider TEXT NOT NULL DEFAULT 'email',
    auth_source TEXT NOT NULL DEFAULT 'frontend',
    ip_address TEXT,
    user_agent TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    repo_id TEXT,
    title TEXT NOT NULL DEFAULT 'New Conversation',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    confidence FLOAT,
    sources JSONB DEFAULT '[]'::jsonb,
    used_model TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nodes_label ON nodes(label);
CREATE INDEX IF NOT EXISTS idx_nodes_type  ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_edges ON edges(from_node_id, to_node_id, relation);
CREATE INDEX IF NOT EXISTS idx_node_embeddings_hnsw ON node_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_node_embeddings_node_id ON node_embeddings(node_id);
CREATE INDEX IF NOT EXISTS idx_node_embeddings_repo_id ON node_embeddings(repo_id);
CREATE INDEX IF NOT EXISTS idx_node_embeddings_file_path ON node_embeddings(file_path);
CREATE INDEX IF NOT EXISTS idx_node_embeddings_content_hash ON node_embeddings(content_hash);
CREATE INDEX IF NOT EXISTS idx_user_auth_events_user_id ON user_auth_events(user_id);
CREATE INDEX IF NOT EXISTS idx_user_auth_events_email ON user_auth_events(email);
CREATE INDEX IF NOT EXISTS idx_user_auth_events_created_at ON user_auth_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_threads_user_id ON chat_threads(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_threads_repo_id ON chat_threads(repo_id);
CREATE INDEX IF NOT EXISTS idx_chat_threads_updated_at ON chat_threads(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_id ON chat_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages(created_at ASC);

CREATE OR REPLACE FUNCTION match_embeddings(
  query_embedding vector(384),
  match_limit int DEFAULT 5,
  filter_repo_id text DEFAULT NULL
)
RETURNS TABLE (
  id uuid,
  node_id uuid,
  chunk text,
  repo_id text,
  file_path text,
  language text,
  start_line integer,
  end_line integer,
  content_hash text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT ne.id,
         ne.node_id,
         ne.chunk,
         ne.repo_id,
         ne.file_path,
         ne.language,
         ne.start_line,
         ne.end_line,
         ne.content_hash,
         1 - (ne.embedding <=> query_embedding) AS similarity
  FROM node_embeddings ne
  JOIN nodes n ON n.id = ne.node_id
  WHERE filter_repo_id IS NULL
     OR filter_repo_id = ''
     OR ne.repo_id = filter_repo_id
     OR n.label = filter_repo_id
     OR n.metadata->>'repo' = filter_repo_id
     OR (n.metadata->>'owner' || '/' || n.metadata->>'name') = filter_repo_id
  ORDER BY ne.embedding <=> query_embedding
  LIMIT match_limit;
END;
$$;

GRANT EXECUTE ON FUNCTION match_embeddings(vector, int, text) TO anon, authenticated, service_role;
