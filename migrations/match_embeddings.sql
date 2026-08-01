-- Migration: Create match_embeddings RPC function for native pgvector HNSW search with optional repo filtering

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
