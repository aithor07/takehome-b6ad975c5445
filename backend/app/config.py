from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    ai_api_url: str = "http://localhost:8080"
    ai_api_key: str = "dev_key"
    database_url: str = "sqlite:///./app.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()