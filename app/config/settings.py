from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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

    BACKEND_API_URL: str = "https://backendcopia-software.onrender.com/docs"
    FRONTEND_URL: str = "https://frontend-copia-software.vercel.app"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
