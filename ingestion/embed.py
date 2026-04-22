from __future__ import annotations

import math
import threading
from typing import Optional

from sentence_transformers import SentenceTransformer

try:
    from .utils import clean_text, log_error, log_step
except ImportError:
    from utils import clean_text, log_error, log_step

MODEL_NAME = "all-MiniLM-L6-v2"
_model: Optional[SentenceTransformer] = None
_model_lock = threading.Lock()


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                log_step(f"Loading embedding model '{MODEL_NAME}'.")
                _model = SentenceTransformer(MODEL_NAME)
    return _model


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return []
    return [value / norm for value in vector]


def generate_embedding(text: str) -> list[float]:
    cleaned = clean_text(text)
    if not cleaned:
        return []

    try:
        model = _get_model()
        embedding = model.encode(cleaned, normalize_embeddings=True)
        vector = embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)
        if not vector:
            return []
        return _normalize([float(value) for value in vector])
    except Exception as exc:
        log_error(f"Embedding generation failed: {exc}")
        return []
