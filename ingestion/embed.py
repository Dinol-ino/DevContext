from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from .utils import clean_text, log_error, log_warning

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=False)

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384
MAX_TEXT_LENGTH = 6000


@lru_cache(maxsize=1)
def _get_model():
    """Load the local sentence-transformer model once and cache it."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        return SentenceTransformer(EMBEDDING_MODEL)
    except Exception as exc:
        log_error(f"Failed to load local embedding model: {exc}")
        return None


def _trim_text(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    if len(cleaned) > MAX_TEXT_LENGTH:
        return cleaned[:MAX_TEXT_LENGTH].strip()
    return cleaned


def generate_embedding(text: str) -> list[float]:
    cleaned = _trim_text(text)
    if not cleaned:
        return []

    model = _get_model()
    if model is None:
        log_warning("Embedding model not available; embedding skipped.")
        return []

    try:
        vector = model.encode(cleaned, normalize_embeddings=True)
        return [float(v) for v in vector]
    except Exception as exc:
        log_error(f"Local embedding generation failed: {exc}")
        return []

