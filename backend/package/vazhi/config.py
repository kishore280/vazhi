from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    dev_api_key: str = "vazhi-dev-key"
    dev_uid: str = "dev-user"


settings = Settings()
