import os
import time
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("devcontextiq.agents")

try:
    from .auth_agent import router as auth_router
    from .commit_agent import router as commit_router
    from .context_agent import router as context_router
    from .governance_agent import router as gov_router
    from .incident_agent import router as incident_router
    from .memory_agent import router as memory_router
    from .onboarding_agent import router as onboarding_router
    from .repository_agent import router as repo_router
    from .timeline_agent import router as timeline_router
except ImportError:
    from auth_agent import router as auth_router
    from commit_agent import router as commit_router
    from context_agent import router as context_router
    from governance_agent import router as gov_router
    from incident_agent import router as incident_router
    from memory_agent import router as memory_router
    from onboarding_agent import router as onboarding_router
    from repository_agent import router as repo_router
    from timeline_agent import router as timeline_router

API_PREFIX = "/api/v1"
DEFAULT_ALLOWED_ORIGINS = [
    "https://dev-context.vercel.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def _normalize_origin(origin: str) -> str:
    return origin.strip().rstrip("/")


def _get_allowed_origins() -> list[str]:
    configured = os.getenv("FRONTEND_ORIGINS", "")
    extra_origins = [_normalize_origin(origin) for origin in configured.split(",") if origin.strip()]

    origins: list[str] = []
    for origin in [*DEFAULT_ALLOWED_ORIGINS, *extra_origins]:
        origin = _normalize_origin(origin)
        if not origin:
            continue
        if origin not in origins:
            origins.append(origin)

    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Verifying configuration and environment variables...")
    required = ["SUPABASE_URL", "OPENROUTER_API_KEY"]
    missing = [var for var in required if not os.getenv(var)]

    # Check either SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY is present
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not supabase_key:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")

    if missing:
        msg = f"Critical Startup Error: Missing required env vars: {', '.join(missing)}"
        logger.error(msg)
        raise RuntimeError(msg)
    logger.info("All required environment variables verified successfully.")
    yield


app = FastAPI(title="DevContextIQ API", version="2.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)



@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(
        f"Request: {request.method} {request.url.path} - Status: {response.status_code} - Duration: {duration:.4f}s"
    )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(context_router, prefix=API_PREFIX)
app.include_router(gov_router, prefix=API_PREFIX)
app.include_router(incident_router, prefix=API_PREFIX)
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(repo_router, prefix=API_PREFIX)
app.include_router(memory_router, prefix=API_PREFIX)
app.include_router(commit_router, prefix=API_PREFIX)
app.include_router(onboarding_router, prefix=API_PREFIX)
app.include_router(timeline_router, prefix=API_PREFIX)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "An internal server error occurred."})


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "DevContextIQ API", "version": "2.0.0"}


@app.get("/health")
def root_health():
    return {"status": "ok"}


@app.get("/api/v1/health")
def api_health():
    return {"status": "ok", "version": "2.0.0"}
