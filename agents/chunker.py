from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

IGNORE_DIRS = {
    "node_modules", ".git", ".idea", ".vscode", "__pycache__", "dist", "build",
    "coverage", ".next", ".cache", "venv", ".venv", "cloned_repos"
}

IGNORE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".zip", ".tar",
    ".gz", ".exe", ".dll", ".so", ".dylib", ".woff", ".woff2", ".ttf", ".eot",
    ".pyc", ".pyo", ".lock", ".min.js", ".min.css", ".map"
}

MAX_FILE_SIZE_BYTES = 100 * 1024  # 100 KB max per file
CHUNK_SIZE_LINES = 60
CHUNK_OVERLAP_LINES = 15


@dataclass
class CodeChunk:
    file_path: str
    language: str
    content: str
    start_line: int
    end_line: int


def detect_language(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".cs": "csharp",
        ".rb": "ruby",
        ".php": "php",
        ".rs": "rust",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".sql": "sql",
        ".sh": "bash",
        ".html": "html",
        ".css": "css",
    }
    return mapping.get(ext, "text")


def chunk_text_by_lines(
    file_path: str,
    language: str,
    text: str,
    chunk_lines: int = CHUNK_SIZE_LINES,
    overlap: int = CHUNK_OVERLAP_LINES,
) -> list[CodeChunk]:
    lines = text.splitlines()
    if not lines:
        return []

    chunks: list[CodeChunk] = []
    total_lines = len(lines)
    step = max(1, chunk_lines - overlap)

    for start_idx in range(0, total_lines, step):
        end_idx = min(start_idx + chunk_lines, total_lines)
        chunk_lines_slice = lines[start_idx:end_idx]
        chunk_content = "\n".join(chunk_lines_slice).strip()

        if chunk_content:
            header = f"File: {file_path} (Lines {start_idx + 1}-{end_idx}, {language})\n"
            chunks.append(
                CodeChunk(
                    file_path=file_path,
                    language=language,
                    content=header + chunk_content,
                    start_line=start_idx + 1,
                    end_line=end_idx,
                )
            )

        if end_idx >= total_lines:
            break

    return chunks


def chunk_python(file_path: str, text: str) -> list[CodeChunk]:
    """Semantic chunking for Python files splitting on class/def boundaries when possible."""
    lines = text.splitlines()
    if not lines:
        return []

    chunks: list[CodeChunk] = []
    current_chunk: list[str] = []
    start_line = 1

    for idx, line in enumerate(lines, start=1):
        # Trigger split on def/class at root or indentation 4
        if current_chunk and (re.match(r"^(def|class)\s+", line) or (len(current_chunk) >= CHUNK_SIZE_LINES)):
            chunk_content = "\n".join(current_chunk).strip()
            if chunk_content:
                header = f"File: {file_path} (Lines {start_line}-{idx - 1}, python)\n"
                chunks.append(
                    CodeChunk(
                        file_path=file_path,
                        language="python",
                        content=header + chunk_content,
                        start_line=start_line,
                        end_line=idx - 1,
                    )
                )
            current_chunk = []
            start_line = idx

        current_chunk.append(line)

    if current_chunk:
        chunk_content = "\n".join(current_chunk).strip()
        if chunk_content:
            header = f"File: {file_path} (Lines {start_line}-{len(lines)}, python)\n"
            chunks.append(
                CodeChunk(
                    file_path=file_path,
                    language="python",
                    content=header + chunk_content,
                    start_line=start_line,
                    end_line=len(lines),
                )
            )

    return chunks if chunks else chunk_text_by_lines(file_path, "python", text)


def chunk_file(file_path: str, repo_root: str) -> list[CodeChunk]:
    path = Path(file_path)
    if not path.is_file() or path.stat().st_size > MAX_FILE_SIZE_BYTES:
        return []

    if path.suffix.lower() in IGNORE_EXTENSIONS:
        return []

    try:
        rel_path = str(path.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        rel_path = path.name

    # Check directory ignores
    parts = set(Path(rel_path).parts)
    if parts.intersection(IGNORE_DIRS):
        return []

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    if not text.strip():
        return []

    lang = detect_language(rel_path)
    if lang == "python":
        return chunk_python(rel_path, text)

    return chunk_text_by_lines(rel_path, lang, text)


def chunk_repository(repo_dir: str) -> list[CodeChunk]:
    root = Path(repo_dir)
    if not root.exists():
        return []

    chunks: list[CodeChunk] = []
    for path in sorted(root.rglob("*"), key=lambda item: str(item).lower()):
        if path.is_file():
            file_chunks = chunk_file(str(path), str(root))
            chunks.extend(file_chunks)

    return chunks
