-- Add chunk-level identity/metadata and expose the pgvector RPC used by the API.

ALTER TABLE node_embeddings
  ADD COLUMN IF NOT EXISTS id UUID DEFAULT gen_random_uuid(),
  ADD COLUMN IF NOT EXISTS repo_id TEXT,
  ADD COLUMN IF NOT EXISTS file_path TEXT,
  ADD COLUMN IF NOT EXISTS language TEXT,
  ADD COLUMN IF NOT EXISTS start_line INTEGER,
  ADD COLUMN IF NOT EXISTS end_line INTEGER,
  ADD COLUMN IF NOT EXISTS content_hash TEXT;

UPDATE node_embeddings
SET id = gen_random_uuid()
WHERE id IS NULL;

ALTER TABLE node_embeddings
  ALTER COLUMN id SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'node_embeddings'::regclass
      AND contype = 'p'
  ) THEN
    ALTER TABLE node_embeddings ADD CONSTRAINT node_embeddings_pkey PRIMARY KEY (id);
  END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_node_embeddings_node_id ON node_embeddings(node_id);
CREATE INDEX IF NOT EXISTS idx_node_embeddings_repo_id ON node_embeddings(repo_id);
CREATE INDEX IF NOT EXISTS idx_node_embeddings_file_path ON node_embeddings(file_path);
CREATE INDEX IF NOT EXISTS idx_node_embeddings_content_hash ON node_embeddings(content_hash);

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

NOTIFY pgrst, 'reload schema';
