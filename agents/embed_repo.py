from __future__ import annotations

import logging
from typing import Any

try:
    from .chunker import chunk_repository
    from .db import get_client
    from .tools import _generate_query_embedding
except ImportError:
    from chunker import chunk_repository
    from db import get_client
    from tools import _generate_query_embedding

logger = logging.getLogger("devcontextiq.embed_repo")


def embed_repository_chunks(repo_node_id: str, repo_dir: str, batch_size: int = 20) -> dict[str, Any]:
    """Chunk source files in repo_dir, generate embeddings, and insert into node_embeddings linked to repo_node_id."""
    client = get_client()
    if client is None:
        logger.error("Supabase client not initialized. Cannot embed repository.")
        return {"success": False, "error": "Database not initialized", "embedded_count": 0}

    logger.info(f"Chunking repository at {repo_dir} for node_id={repo_node_id}...")
    chunks = chunk_repository(repo_dir)
    if not chunks:
        logger.info("No text chunks found in repository.")
        return {"success": True, "embedded_count": 0, "message": "No chunks found to embed."}

    logger.info(f"Generated {len(chunks)} chunks. Generating embeddings...")
    inserted_count = 0
    batch_rows: list[dict[str, Any]] = []

    for chunk in chunks:
        vector = _generate_query_embedding(chunk.content)
        if not vector:
            continue

        row = {
            "node_id": repo_node_id,
            "chunk": chunk.content[:4000],
            "embedding": vector,
        }
        batch_rows.append(row)

        if len(batch_rows) >= batch_size:
            try:
                client.table("node_embeddings").insert(batch_rows).execute()
                inserted_count += len(batch_rows)
                logger.info(f"Embedded {inserted_count}/{len(chunks)} chunks...")
            except Exception as exc:
                logger.warning(f"Batch embedding insert failed: {exc}")
            batch_rows = []

    if batch_rows:
        try:
            client.table("node_embeddings").insert(batch_rows).execute()
            inserted_count += len(batch_rows)
        except Exception as exc:
            logger.warning(f"Final batch embedding insert failed: {exc}")

    logger.info(f"Successfully embedded {inserted_count} repository code chunks.")
    return {
        "success": True,
        "total_chunks": len(chunks),
        "embedded_count": inserted_count,
    }
