import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

try:
    from .auth_agent import router as auth_router
    from .context_agent import router as context_router
    from .governance_agent import router as gov_router
    from .incident_agent import router as incident_router
except ImportError:
    from auth_agent import router as auth_router
    from context_agent import router as context_router
    from governance_agent import router as gov_router
    from incident_agent import router as incident_router

API_PREFIX = "/api/v1"
DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://yourapp.vercel.app",
]


def _normalize_origin(origin: str) -> str:
    return origin.strip().rstrip("/")


def _get_allowed_origins() -> list[str]:
    configured = os.getenv("FRONTEND_ORIGINS", "")
    extra_origins = [_normalize_origin(origin) for origin in configured.split(",") if origin.strip()]
    vercel_frontend = _normalize_origin(os.getenv("VERCEL_FRONTEND_URL", ""))

    vercel_runtime_url = _normalize_origin(os.getenv("VERCEL_URL", ""))
    if vercel_runtime_url and not vercel_runtime_url.startswith(("http://", "https://")):
        vercel_runtime_url = f"https://{vercel_runtime_url}"

    origins: list[str] = []
    for origin in [*DEFAULT_ALLOWED_ORIGINS, *extra_origins, vercel_frontend, vercel_runtime_url]:
        origin = _normalize_origin(origin)
        if not origin:
            continue
        if origin not in origins:
            origins.append(origin)

    return origins

app = FastAPI(title="DevContextIQ API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(context_router, prefix=API_PREFIX)
app.include_router(gov_router, prefix=API_PREFIX)
app.include_router(incident_router, prefix=API_PREFIX)
app.include_router(auth_router, prefix=API_PREFIX)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": f"Internal server error: {exc}"})


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "DevContextIQ API", "version": "2.0.0"}


@app.get("/health")
def root_health():
    return {"status": "ok"}

@app.get("/api/v1/health")
def api_health():
    return {"status": "ok", "version": "2.0.0"}
