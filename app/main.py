import json
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from app.config import settings
from app.database import check_db_connection, get_session, engine
from app.logging_config import setup_logging, get_logger
from app.models.lti_launch import Base
from app.models.submission import Submission  # noqa: F401 - registers model with Base
from app.routers import lti, grades, submission

# Load JWKS once at module load
_jwks_path = Path(__file__).parent / "static" / "jwks.json"
_jwks = json.loads(_jwks_path.read_text())

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info(f"Starting {settings.APP_NAME}")

    # Check database connection
    if not await check_db_connection():
        logger.warning("App starting without database connection")
    else:
        # Create tables if they don't exist
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified")

    yield

    logger.info("Shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
)

# Mount routers
app.include_router(lti.router)
app.include_router(grades.router)
app.include_router(submission.router)


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    db_ok = False
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
    }


@app.get("/.well-known/jwks.json", response_class=JSONResponse)
async def jwks():
    """Serve the tool's public key for JWT signature verification."""
    return _jwks
