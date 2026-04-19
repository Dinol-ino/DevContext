from fastapi import FastAPI

try:
    from .context_agent import router as context_router
    from .governance_agent import router as gov_router
    from .incident_agent import router as incident_router
except ImportError:
    from context_agent import router as context_router
    from governance_agent import router as gov_router
    from incident_agent import router as incident_router

app = FastAPI(title="DevContextIQ API", version="1.0.0")

app.include_router(context_router)
app.include_router(gov_router)
app.include_router(incident_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "1.0"}
