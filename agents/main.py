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
]


def _get_allowed_origins() -> list[str]:
    configured = os.getenv("FRONTEND_ORIGINS", "")
    extra_origins = [origin.strip() for origin in configured.split(",") if origin.strip()]

    origins: list[str] = []
    for origin in [*DEFAULT_ALLOWED_ORIGINS, *extra_origins]:
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
