from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://orchestrator:orchestrator@localhost:5432/orchestrator"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    max_retries: int = 4
    retry_base_seconds: int = 2
    session_secret: str | None = None
    session_cookie_secure: bool = False
    session_ttl_seconds: int = 28800

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
