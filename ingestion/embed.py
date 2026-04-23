from __future__ import annotations

import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from .utils import clean_text, log_error, log_warning

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=False)

OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 768
MAX_TEXT_LENGTH = 6000
TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 2


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

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        log_warning("OPENAI_API_KEY not configured; embedding skipped.")
        return []

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": EMBEDDING_MODEL,
        "input": cleaned,
        "dimensions": EMBEDDING_DIMENSIONS,
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                OPENAI_EMBEDDINGS_URL,
                headers=headers,
                json=payload,
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            embedding = data.get("data", [{}])[0].get("embedding", [])
            if not isinstance(embedding, list) or not embedding:
                return []
            return [float(value) for value in embedding]
        except Exception as exc:
            if attempt >= MAX_ATTEMPTS:
                log_error(f"OpenAI embedding request failed: {exc}")
                return []
            time.sleep(1)

    return []
