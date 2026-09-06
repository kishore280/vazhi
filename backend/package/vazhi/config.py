from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    dev_api_key: str = "vazhi-dev-key"
    dev_uid: str = "dev-user"
    postgres_dsn: str = "postgresql+asyncpg://vazhi:vazhi_dev_password@postgres:5432/vazhi"
    redis_url: str = "redis://redis:6379"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    run_lease_ttl_seconds: int = 60


settings = Settings()
