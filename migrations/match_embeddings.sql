-- Migration: Create match_embeddings RPC function for native pgvector HNSW search with optional repo filtering

CREATE OR REPLACE FUNCTION match_embeddings(
  query_embedding vector(384),
  match_limit int DEFAULT 5,
  filter_repo_id text DEFAULT NULL
)
RETURNS TABLE (
  node_id uuid,
  chunk text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  IF filter_repo_id IS NOT NULL AND filter_repo_id != '' THEN
    RETURN QUERY
    SELECT ne.node_id, ne.chunk,
           1 - (ne.embedding <=> query_embedding) AS similarity
    FROM node_embeddings ne
    JOIN nodes n ON n.id = ne.node_id
    WHERE n.label = filter_repo_id
       OR n.metadata->>'repo' = filter_repo_id
       OR (n.metadata->>'owner' || '/' || n.metadata->>'name') = filter_repo_id
    ORDER BY ne.embedding <=> query_embedding
    LIMIT match_limit;
  ELSE
    RETURN QUERY
    SELECT ne.node_id, ne.chunk,
           1 - (ne.embedding <=> query_embedding) AS similarity
    FROM node_embeddings ne
    ORDER BY ne.embedding <=> query_embedding
    LIMIT match_limit;
  END IF;
END;
$$;
