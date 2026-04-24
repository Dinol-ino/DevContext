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
    node_id UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    chunk TEXT NOT NULL,
    embedding vector(768) NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_nodes_label ON nodes(label);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_edges ON edges(from_node_id, to_node_id, relation);
CREATE INDEX IF NOT EXISTS idx_node_embeddings_hnsw ON node_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_user_auth_events_user_id ON user_auth_events(user_id);
CREATE INDEX IF NOT EXISTS idx_user_auth_events_email ON user_auth_events(email);
CREATE INDEX IF NOT EXISTS idx_user_auth_events_created_at ON user_auth_events(created_at DESC);
