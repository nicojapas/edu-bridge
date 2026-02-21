from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from app.config import settings
from app.database import check_db_connection, get_session
from app.logging_config import setup_logging, get_logger
from app.routers import lti

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info(f"Starting {settings.APP_NAME}")

    if not await check_db_connection():
        logger.warning("App starting without database connection")

    yield

    logger.info("Shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
)

# Mount LTI router
app.include_router(lti.router)


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
