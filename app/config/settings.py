from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    LITELLM_API_BASE: str | None = None

    AI_PROVIDER: str = "litellm"

    PLANNER_MODEL: str = "gemini/gemini-3.6-flash"
    DIAGRAM_MODEL: str = "gemini/gemini-3.6-flash"
    SUGGESTION_MODEL: str = "gemini/gemini-3.6-flash"
    VALIDATION_MODEL: str = "gemini/gemini-3.6-flash"
    CODEGEN_MODEL: str = "gemini/gemini-3.6-flash"
    IMAGE_MODEL: str = "gemini/gemini-3.5-flash"
    IMAGE_FALLBACK_MODELS: str = "gemini/gemini-3.6-flash"

    IMAGE_MAX_BYTES: int = 10 * 1024 * 1024

    BACKEND_API_URL: str = "http://127.0.0.1:8001"
    FRONTEND_URL: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
