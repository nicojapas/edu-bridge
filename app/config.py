import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME: str = "EduBridge LTI"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    @property
    def async_database_url(self) -> str:
        """Ensure URL uses asyncpg driver."""
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


settings = Settings()
