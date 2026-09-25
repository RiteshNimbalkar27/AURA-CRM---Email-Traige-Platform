"""
AURA FastAPI Application Entry Point
"""
import sys

# Windows: psycopg async requires SelectorEventLoop, not ProactorEventLoop
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine

# Import all models to ensure they are registered with SQLAlchemy Base
import app.models  # noqa: F401

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown handlers."""
    # Startup
    logger.info(f"AURA starting up — environment: {settings.environment}")
    logger.info(f"Synthetic data only: {settings.synthetic_data_only}")
    if not settings.synthetic_data_only:
        logger.warning(
            "SYNTHETIC_DATA_ONLY is False! Real customer data must NOT be "
            "sent to Gemini. Ensure this is intentional."
        )
    yield
    # Shutdown
    logger.info("AURA shutting down — disposing database engine")
    await engine.dispose()


app = FastAPI(
    title="AURA — Agentic CRM Intelligence Platform",
    description="Supervised RAG-grounded email triage system. Synthetic data only.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS middleware (allow local frontend dev server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers (registered as they are built) ---
from app.api.auth import router as auth_router  # noqa: E402
from app.api.ingest import router as ingest_router  # noqa: E402

app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(ingest_router, prefix="/api", tags=["Ingestion"])

from app.api.rag_api import router as rag_router  # noqa: E402
app.include_router(rag_router, prefix="/api", tags=["RAG"])

from app.api.inbox import router as inbox_router  # noqa: E402
app.include_router(inbox_router, prefix="/api", tags=["Inbox"])

from app.api.agent_api import router as agent_router  # noqa: E402
app.include_router(agent_router, prefix="/api", tags=["Agent"])


@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "synthetic_data_only": settings.synthetic_data_only,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
