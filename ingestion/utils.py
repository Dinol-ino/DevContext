import json
import logging
import os
import re
from typing import Any


def clean_text(text: str) -> str:
    if text is None:
        return ""
    value = str(text).replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def safe_json(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        candidates = [raw]
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidates.append(raw[start : end + 1])

        loaded = None
        for candidate in candidates:
            try:
                loaded = json.loads(candidate)
                break
            except (TypeError, ValueError):
                continue
        if loaded is None:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def make_pr_text(
    repo: str,
    title: str,
    body: str,
    url: str,
    author: str,
    event_type: str,
) -> str:
    lines = [
        f"Repo: {clean_text(repo)}",
        f"Author: {clean_text(author)}",
        f"Event: {clean_text(event_type)}",
        f"Title: {clean_text(title)}",
        f"Body: {clean_text(body)}",
        f"URL: {clean_text(url)}",
    ]
    return "\n".join(lines)


def slugify(value: str) -> str:
    cleaned = clean_text(value).lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("devcontextiq.ingestion")
    if logger.handlers:
        return logger

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    level_name = clean_text(os.getenv("LOG_LEVEL", "INFO")).upper() or "INFO"
    level_value = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level_value)
    logger.propagate = False
    return logger


def log_info(msg: str) -> None:
    _get_logger().info(clean_text(msg))


def log_warning(msg: str) -> None:
    _get_logger().warning(clean_text(msg))


def log_error(msg: str) -> None:
    _get_logger().error(clean_text(msg))


def log_step(msg: str) -> None:
    _get_logger().info(clean_text(msg))
