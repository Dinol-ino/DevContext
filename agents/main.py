from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

try:
    from .context_agent import router as context_router
    from .governance_agent import router as gov_router
    from .incident_agent import router as incident_router
except ImportError:
    from context_agent import router as context_router
    from governance_agent import router as gov_router
    from incident_agent import router as incident_router

API_PREFIX = "/api/v1"

app = FastAPI(title="DevContextIQ API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(context_router, prefix=API_PREFIX)
app.include_router(gov_router, prefix=API_PREFIX)
app.include_router(incident_router, prefix=API_PREFIX)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": f"Internal server error: {exc}"})


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "DevContextIQ API", "version": "2.0.0"}


@app.get(f"{API_PREFIX}/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "2.0.0"}
