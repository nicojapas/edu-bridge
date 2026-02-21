import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME: str = "EduBridge LTI"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # LTI 1.3 Configuration
    LTI_CLIENT_ID: str = os.getenv("LTI_CLIENT_ID", "")
    LTI_ISSUER: str = os.getenv("LTI_ISSUER", "")
    LTI_AUTHORIZATION_ENDPOINT: str = os.getenv("LTI_AUTHORIZATION_ENDPOINT", "")
    LTI_JWKS_URL: str = os.getenv("LTI_JWKS_URL", "")
    LTI_DEPLOYMENT_ID: str = os.getenv("LTI_DEPLOYMENT_ID", "")

    # AGS / OAuth 2.0
    ACCESS_TOKEN_URL: str = os.getenv("ACCESS_TOKEN_URL", "")
    # Private key may have escaped newlines (\n) in env var - convert to actual newlines
    LTI_PRIVATE_KEY: str = os.getenv("LTI_PRIVATE_KEY", "").replace("\\n", "\n")

    # App URL (for redirect_uri construction)
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000")

    @property
    def async_database_url(self) -> str:
        """Ensure URL uses asyncpg driver."""
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def lti_redirect_uri(self) -> str:
        """The redirect URI for LTI launch (OIDC callback)."""
        return f"{self.APP_BASE_URL}/lti/launch"

    @property
    def lti_login_url(self) -> str:
        """The login initiation URL."""
        return f"{self.APP_BASE_URL}/lti/login"


settings = Settings()
