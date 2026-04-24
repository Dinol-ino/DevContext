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

HF_EMBEDDINGS_URL = "https://router.huggingface.co/hf-inference/models/sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384
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

    hf_token = os.getenv("HF_TOKEN", "").strip()
    if not hf_token:
        log_warning("HF_TOKEN not configured; embedding skipped.")
        return []

    headers = {
        "Authorization": f"Bearer {hf_token}",
        "Content-Type": "application/json",
    }
    payload = {"inputs": cleaned}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                HF_EMBEDDINGS_URL,
                headers=headers,
                json=payload,
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            embedding: list[float] = []
            if isinstance(data, list) and data and all(isinstance(value, (float, int)) for value in data):
                embedding = [float(value) for value in data]
            elif (
                isinstance(data, list)
                and data
                and isinstance(data[0], list)
                and data[0]
                and all(isinstance(value, (float, int)) for value in data[0])
            ):
                embedding = [float(value) for value in data[0]]

            if not embedding:
                return []
            return embedding
        except Exception as exc:
            if attempt >= MAX_ATTEMPTS:
                log_error(f"Hugging Face embedding request failed: {exc}")
                return []
            time.sleep(1)

    return []
