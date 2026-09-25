import os

from agents import set_tracing_disabled

from app.config.settings import settings


def get_ai_provider():
    return settings.AI_PROVIDER.strip().lower()


def configure_ai_provider():
    provider = get_ai_provider()

    if provider != "litellm":
        raise RuntimeError(
            "Este servicio esta configurado exclusivamente para Gemini mediante LiteLLM"
        )

    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY no esta configurada en el archivo .env")

    os.environ.setdefault("GEMINI_API_KEY", settings.GEMINI_API_KEY)
    os.environ.setdefault("GOOGLE_API_KEY", settings.GEMINI_API_KEY)
    os.environ.setdefault("OPENAI_AGENTS_ENABLE_LITELLM_SERIALIZER_PATCH", "true")

    # OpenAI Agents se usa como orquestador; las inferencias se envian a Gemini.
    set_tracing_disabled(True)
