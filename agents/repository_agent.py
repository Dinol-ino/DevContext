import os
import re
import shutil
import stat
import logging
import threading
import uuid
import gc
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import git
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

try:
    from .auth_utils import get_current_user
    from .db import get_client
    from .embed_repo import embed_repository_chunks
except ImportError:
    from auth_utils import get_current_user
    from db import get_client
    from embed_repo import embed_repository_chunks

# Configure logging
logger = logging.getLogger("devcontextiq.repository")

router = APIRouter(tags=["Repository"])

# Create workspace base path inside project directory (ignored by git)
CLONED_REPOS_DIR = Path(__file__).resolve().parents[1] / "cloned_repos"


class RepositoryLockManager:
    """Thread-safe per-repository lock manager preventing concurrent imports of the same repository."""
    def __init__(self):
        self._active_imports: set[str] = set()
        self._lock = threading.Lock()

    def acquire(self, repo_key: str) -> bool:
        """Attempt to acquire import lock for repo_key. Returns True if acquired, False if already active."""
        with self._lock:
            if repo_key in self._active_imports:
                return False
            self._active_imports.add(repo_key)
            return True

    def release(self, repo_key: str) -> None:
        """Release import lock for repo_key."""
        with self._lock:
            self._active_imports.discard(repo_key)


_repository_lock_manager = RepositoryLockManager()

EXTENSION_TO_LANGUAGE = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".sh": "Shell",
    ".html": "HTML",
    ".css": "CSS",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".scala": "Scala",
    ".tf": "Terraform",
    ".sql": "SQL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".md": "Markdown",
}


class RepoImportRequest(BaseModel):
    repo_url: str = Field(..., examples=["https://github.com/Dinol-ino/DevContext"])
    branch: Optional[str] = Field(default=None, examples=["main"])


class RepoResponse(BaseModel):
    id: str
    type: str
    label: str
    source_url: str
    metadata: Dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers for cleanup and parsing
# ---------------------------------------------------------------------------

def _onerror(func, path, exc_info):
    """Clear read-only attribute on file and retry deletion on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def safe_rmtree(dir_path: Path) -> None:
    """Safely delete a directory tree, handling Windows read-only files and open handles."""
    if not dir_path.exists():
        return

    import gc
    import time
    gc.collect()

    for attempt in range(3):
        try:
            shutil.rmtree(dir_path, onerror=_onerror)
            break
        except Exception:
            time.sleep(0.3)
            gc.collect()


def parse_github_url(url: str) -> tuple[str, str, str]:
    """Parse owner, name, and full_name from a Git URL."""
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    
    match = re.search(r'github\.com[:/]([^/]+)/([^/]+)', cleaned)
    if match:
        owner = match.group(1)
        repo = match.group(2)
        return owner, repo, f"{owner}/{repo}"
    
    parts = [p for p in cleaned.split("/") if p]
    if len(parts) >= 2:
        owner = parts[-2]
        repo = parts[-1]
        return owner, repo, f"{owner}/{repo}"
    
    raise ValueError("Invalid Git repository URL format.")


# ---------------------------------------------------------------------------
# Ignore and Gitignore Handling
# ---------------------------------------------------------------------------

def is_ignored(path: Path, root_path: Path) -> bool:
    """Check if file or directory should be ignored in the repository tree."""
    try:
        rel_path = path.relative_to(root_path)
    except ValueError:
        return True
    parts = rel_path.parts
    ignored_names = {
        "node_modules", "venv", "env", ".git", ".github", ".vscode", ".idea",
        "__pycache__", "dist", "build", "out", ".next", "target", "bin", "obj",
        "cache", ".pytest_cache", ".cache", "cloned_repos"
    }
    for part in parts:
        if part in ignored_names:
            return True
        if part.startswith(".") and part not in (".env", ".gitignore"):
            return True
    return False


def parse_gitignore(gitignore_path: Path) -> List[str]:
    """Parse gitignore patterns from file."""
    patterns = []
    if gitignore_path.exists():
        with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
    return patterns


def matches_gitignore(path: Path, root_path: Path, patterns: List[str]) -> bool:
    """Check if a path matches simple gitignore patterns."""
    try:
        rel_path = str(path.relative_to(root_path)).replace("\\", "/")
    except ValueError:
        return True
    import fnmatch
    for pattern in patterns:
        pat = pattern.rstrip("/")
        if pattern.endswith("/"):
            if rel_path.startswith(pat) or f"/{pat}" in rel_path:
                return True
        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(rel_path, f"*{pattern}*"):
            return True
    return False


# ---------------------------------------------------------------------------
# Dependency Parsers
# ---------------------------------------------------------------------------

def parse_requirements_txt(content: str) -> Dict[str, str]:
    deps = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-r"):
            continue
        parts = re.split(r'==|>=|<=|~=|>|<', line, maxsplit=1)
        if parts:
            name = parts[0].strip()
            version = parts[1].strip() if len(parts) > 1 else "any"
            name = name.split("[")[0].strip()
            version = version.split(";")[0].split("#")[0].strip()
            if name:
                deps[name] = version
    return deps


def parse_package_json(content: str) -> Dict[str, str]:
    deps = {}
    try:
        import json
        data = json.loads(content)
        for key in ("dependencies", "devDependencies"):
            if key in data and isinstance(data[key], dict):
                for name, version in data[key].items():
                    deps[name] = str(version)
    except Exception:
        pass
    return deps


def parse_pyproject_toml(content: str) -> Dict[str, str]:
    deps = {}
    in_deps_section = False
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if section in ("tool.poetry.dependencies", "project.dependencies", "tool.poetry.dev-dependencies", "project.optional-dependencies"):
                in_deps_section = True
            else:
                in_deps_section = False
            continue
        if in_deps_section:
            match = re.match(r'^([a-zA-Z0-9_\-]+)\s*=\s*(.*)$', line)
            if match:
                name = match.group(1).strip()
                val = match.group(2).strip().strip('"\'')
                if val.startswith("{"):
                    v_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', val)
                    val = v_match.group(1) if v_match else "unknown"
                deps[name] = val
    return deps


def parse_go_mod(content: str) -> Dict[str, str]:
    deps = {}
    in_require = False
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("require ("):
            in_require = True
            continue
        if line.startswith(")") and in_require:
            in_require = False
            continue
        if line.startswith("require "):
            parts = line.split()
            if len(parts) >= 3:
                deps[parts[1]] = parts[2]
            continue
        if in_require:
            parts = line.split()
            if len(parts) >= 2:
                deps[parts[0]] = parts[1]
    return deps


def parse_cargo_toml(content: str) -> Dict[str, str]:
    deps = {}
    in_deps = False
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if section in ("dependencies", "dev-dependencies", "build-dependencies"):
                in_deps = True
            else:
                in_deps = False
            continue
        if in_deps:
            match = re.match(r'^([a-zA-Z0-9_\-]+)\s*=\s*(.*)$', line)
            if match:
                name = match.group(1).strip()
                val = match.group(2).strip().strip('"\'')
                if val.startswith("{"):
                    v_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', val)
                    val = v_match.group(1) if v_match else "unknown"
                deps[name] = val
    return deps


# ---------------------------------------------------------------------------
# Tree Builder & Stats Collector
# ---------------------------------------------------------------------------

def traverse_repo(root_path: Path, gitignore_patterns: List[str]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    file_count = 0
    dir_count = 0
    total_size = 0
    language_sizes = {}
    frameworks = set()
    dependencies = {}
    config_files = []
    entry_points = []
    
    def visit(path: Path) -> Dict[str, Any]:
        nonlocal file_count, dir_count, total_size
        name = path.name
        rel_path = str(path.relative_to(root_path)).replace("\\", "/")
        
        config_names = {
            "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
            "requirements.txt", "pyproject.toml", "cargo.toml", "cargo.lock",
            "go.mod", "go.sum", "tsconfig.json", "jsconfig.json", ".gitignore",
            ".env", ".env.example", "vite.config.ts", "vite.config.js",
            "webpack.config.js", "next.config.js", "next.config.mjs",
            "docker-compose.yml", "docker-compose.yaml", "dockerfile", "Dockerfile",
            "pom.xml", "build.gradle"
        }
        if name.lower() in config_names:
            config_files.append(rel_path)
            
        entry_names = {
            "main.py", "app.py", "wsgi.py", "asgi.py", "manage.py",
            "index.js", "server.js", "app.js", "main.ts", "index.ts",
            "main.go", "main.rs", "lib.rs"
        }
        if name.lower() in entry_names or rel_path in ("src/index.ts", "src/main.ts", "src/main.go", "src/main.rs"):
            entry_points.append(rel_path)
            
        if path.is_dir():
            dir_count += 1
            children = []
            try:
                for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                    if not is_ignored(item, root_path) and not matches_gitignore(item, root_path, gitignore_patterns):
                        children.append(visit(item))
            except Exception:
                pass
            return {
                "name": name,
                "path": rel_path,
                "type": "directory",
                "children": children
            }
        else:
            file_count += 1
            size = path.stat().st_size
            total_size += size
            
            ext = path.suffix.lower()
            lang = EXTENSION_TO_LANGUAGE.get(ext)
            if lang:
                language_sizes[lang] = language_sizes.get(lang, 0) + size
                
            if name == "package.json":
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    pkg_deps = parse_package_json(content)
                    dependencies.update(pkg_deps)
                    for fw, dep_name in [("React", "react"), ("Next.js", "next"), ("Vue", "vue"), ("Angular", "@angular/core"), ("Express", "express")]:
                        if dep_name in pkg_deps:
                            frameworks.add(fw)
                except Exception:
                    pass
            elif name == "requirements.txt":
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    req_deps = parse_requirements_txt(content)
                    dependencies.update(req_deps)
                    for fw, dep_name in [("FastAPI", "fastapi"), ("Flask", "flask"), ("Django", "django")]:
                        if dep_name in req_deps:
                            frameworks.add(fw)
                except Exception:
                    pass
            elif name == "pyproject.toml":
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    toml_deps = parse_pyproject_toml(content)
                    dependencies.update(toml_deps)
                    for fw, dep_name in [("FastAPI", "fastapi"), ("Flask", "flask"), ("Django", "django")]:
                        if dep_name in toml_deps:
                            frameworks.add(fw)
                except Exception:
                    pass
            elif name == "go.mod":
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    go_deps = parse_go_mod(content)
                    dependencies.update(go_deps)
                    for fw, dep_name in [("Gin", "github.com/gin-gonic/gin"), ("Fiber", "github.com/gofiber/fiber"), ("Echo", "github.com/labstack/echo")]:
                        if dep_name in go_deps:
                            frameworks.add(fw)
                except Exception:
                    pass
            elif name == "Cargo.toml":
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    cargo_deps = parse_cargo_toml(content)
                    dependencies.update(cargo_deps)
                except Exception:
                    pass
            
            if ext == ".py":
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")[:2000]
                    if "import fastapi" in content or "from fastapi" in content:
                        frameworks.add("FastAPI")
                    if "import flask" in content or "from flask" in content:
                        frameworks.add("Flask")
                    if "django" in content:
                        frameworks.add("Django")
                except Exception:
                    pass
            elif ext == ".java":
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")[:2000]
                    if "SpringBootApplication" in content or "spring" in content:
                        frameworks.add("Spring")
                except Exception:
                    pass
            
            return {
                "name": name,
                "path": rel_path,
                "type": "file",
                "size": size
            }
            
    tree = visit(root_path)
    
    total_lang_size = sum(language_sizes.values())
    languages = {}
    if total_lang_size > 0:
        for lang, size in language_sizes.items():
            languages[lang] = round((size / total_lang_size) * 100, 2)
            
    stats = {
        "file_count": file_count,
        "directory_count": dir_count,
        "repository_size": total_size,
        "languages": languages,
        "frameworks": list(frameworks),
        "dependencies": dependencies,
        "config_files": config_files,
        "entry_points": entry_points,
        "technology_stack": list(set(languages.keys()) | frameworks)
    }
    
    return tree, stats


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.post("/repo/import", response_model=RepoResponse)
def import_repository(payload: RepoImportRequest, current_user: dict = Depends(get_current_user)) -> RepoResponse:
    repo_url = payload.repo_url.strip()
    if not repo_url:
        raise HTTPException(status_code=400, detail="Repository URL cannot be empty.")
    
    try:
        owner, repo_name, full_name = parse_github_url(repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    branch = payload.branch.strip() if payload.branch else None
    repo_key = f"{full_name}:{branch or 'default'}"

    # 1. Acquire thread-safe lock for repository
    if not _repository_lock_manager.acquire(repo_key):
        logger.warning(f"[LOCK CONFLICT] Import skipped: already running for repository '{repo_key}'")
        raise HTTPException(
            status_code=409,
            detail=f"Import is already in progress for repository '{full_name}'. Please wait for it to complete."
        )

    logger.info(f"[LOCK ACQUIRED] Acquired import lock for repository '{repo_key}'")

    folder_name = f"{owner}_{repo_name}" + (f"_{branch}" if branch else "")
    clone_path = CLONED_REPOS_DIR / folder_name
    tmp_clone_dir = CLONED_REPOS_DIR / f"tmp_{uuid.uuid4().hex}"

    CLONED_REPOS_DIR.mkdir(parents=True, exist_ok=True)
    repo_obj = None

    try:
        # 2. Atomic clone into isolated temporary directory
        logger.info(f"[CLONE START] Atomic cloning repo '{full_name}' into temporary directory '{tmp_clone_dir}'...")
        clone_kwargs = {"depth": 1, "single_branch": True}
        if branch:
            clone_kwargs["branch"] = branch

        repo_obj = git.Repo.clone_from(repo_url, str(tmp_clone_dir), **clone_kwargs)
        try:
            branch = repo_obj.active_branch.name
        except Exception:
            branch = branch or "main"

        # Close git handles immediately after cloning
        if repo_obj:
            try:
                repo_obj.close()
                repo_obj = None
            except Exception:
                pass
        gc.collect()

        logger.info(f"[CLONE SUCCESS] Successfully cloned '{full_name}'. Swapping temporary directory into workspace...")

        # Clean old workspace target if exists
        if clone_path.exists():
            logger.info(f"[CLEANUP] Cleaning up previous workspace directory '{clone_path}'")
            safe_rmtree(clone_path)

        # Atomic move into final workspace path
        shutil.move(str(tmp_clone_dir), str(clone_path))

    except HTTPException:
        safe_rmtree(tmp_clone_dir)
        _repository_lock_manager.release(repo_key)
        raise
    except Exception as exc:
        logger.error(f"[CLONE FAILURE] Failed to clone repository {repo_url}: {exc}")
        if repo_obj:
            try:
                repo_obj.close()
            except Exception:
                pass
        gc.collect()
        safe_rmtree(tmp_clone_dir)
        _repository_lock_manager.release(repo_key)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to clone repository. Ensure the URL and branch are correct and public. Error: {exc}"
        )

    try:
        # Load gitignore if exists
        gitignore_path = clone_path / ".gitignore"
        gitignore_patterns = parse_gitignore(gitignore_path)
        
        # Traverse the repository tree and gather metadata
        tree, stats = traverse_repo(clone_path, gitignore_patterns)
        
        # Package metadata
        repo_metadata = {
            "name": repo_name,
            "owner": owner,
            "default_branch": branch,
            "languages": stats["languages"],
            "frameworks": stats["frameworks"],
            "dependencies": stats["dependencies"],
            "repository_size": stats["repository_size"],
            "file_count": stats["file_count"],
            "directory_count": stats["directory_count"],
            "entry_points": stats["entry_points"],
            "config_files": stats["config_files"],
            "technology_stack": stats["technology_stack"],
            "tree": tree
        }
        
        # Supabase connectivity and storage
        client = get_client()
        if client is None:
            raise HTTPException(status_code=500, detail="Database client is not initialized.")
            
        # Check if repository already exists in database
        existing = client.table("nodes").select("id").eq("type", "repo").eq("label", full_name).execute()
        existing_rows = existing.data or []
        
        if existing_rows:
            node_id = existing_rows[0]["id"]
            logger.info(f"Repository {full_name} exists (id={node_id}). Updating...")
            result = client.table("nodes").update({
                "metadata": repo_metadata,
                "source_url": repo_url,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", node_id).execute()
        else:
            logger.info(f"Inserting new repository node for {full_name}...")
            result = client.table("nodes").insert({
                "type": "repo",
                "label": full_name,
                "metadata": repo_metadata,
                "source_url": repo_url
            }).execute()
            
        rows = result.data or []
        if not rows:
            raise HTTPException(status_code=500, detail="Database insert/update returned no data.")
            
        stored = rows[0]
        node_id = str(stored["id"])

        # Code chunking and file-level embeddings
        try:
            logger.info(f"Initiating code embedding for repo {full_name} (id={node_id})...")
            embed_result = embed_repository_chunks(node_id, str(clone_path))
            logger.info(f"Code embedding result: {embed_result}")
        except Exception as embed_exc:
            logger.warning(f"Code embedding failed (repo metadata stored): {embed_exc}")

        return RepoResponse(
            id=node_id,
            type=str(stored["type"]),
            label=str(stored["label"]),
            source_url=str(stored.get("source_url", repo_url)),
            metadata=stored.get("metadata", {})
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error processing repository metadata: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to process repository metadata: {exc}")
    finally:
        # Perform cleanup and release lock
        if repo_obj is not None:
            try:
                repo_obj.close()
            except Exception:
                pass
        gc.collect()
        safe_rmtree(clone_path)

        _repository_lock_manager.release(repo_key)
        logger.info(f"[LOCK RELEASED] Released import lock for repository '{repo_key}'")


@router.get("/repo/list", response_model=List[RepoResponse])
def list_repositories(current_user: dict = Depends(get_current_user)) -> List[RepoResponse]:
    client = get_client()
    if client is None:
        raise HTTPException(status_code=500, detail="Database client is not initialized.")
        
    try:
        response = client.table("nodes").select("*").eq("type", "repo").order("created_at", desc=True).execute()
        rows = response.data or []
        repos = []
        for row in rows:
            repos.append(RepoResponse(
                id=str(row["id"]),
                type=str(row["type"]),
                label=str(row["label"]),
                source_url=str(row.get("source_url", "")),
                metadata=row.get("metadata", {})
            ))
        return repos
    except Exception as exc:
        logger.error(f"Failed to fetch repositories: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch repositories: {exc}")


@router.delete("/repo/{repo_id}")
def delete_repository(repo_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    client = get_client()
    if client is None:
        raise HTTPException(status_code=500, detail="Database client is not initialized.")
        
    try:
        response = client.table("nodes").delete().eq("type", "repo").eq("id", repo_id).execute()
        rows = response.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="Repository not found.")
        return {"status": "deleted", "id": repo_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to delete repository {repo_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to delete repository: {exc}")
