from app.config.settings import settings


def get_agent_model_name(agent_name: str):
    models = {
        "planner": settings.PLANNER_MODEL,
        "diagram": settings.DIAGRAM_MODEL,
        "suggestion": settings.SUGGESTION_MODEL,
        "validation": settings.VALIDATION_MODEL,
        "codegen": settings.CODEGEN_MODEL,
        "image": settings.IMAGE_MODEL,
    }

    try:
        return models[agent_name]
    except KeyError as exc:
        valid_agents = ", ".join(models.keys())
        raise ValueError(f"Agente no configurado: {agent_name}. Agentes validos: {valid_agents}") from exc


def normalize_litellm_model(model_name: str):
    if model_name.startswith("litellm/"):
        return model_name.removeprefix("litellm/")

    return model_name


def get_litellm_api_key(model_name: str):
    if model_name.startswith("gemini/"):
        return settings.GEMINI_API_KEY

    raise ValueError(
        f"Modelo no soportado: {model_name}. Configura un modelo con prefijo gemini/"
    )


def get_agent_model(agent_name: str):
    provider = settings.AI_PROVIDER.strip().lower()
    model_name = get_agent_model_name(agent_name)

    if provider == "litellm":
        from agents.extensions.models.litellm_model import LitellmModel

        litellm_model_name = normalize_litellm_model(model_name)

        return LitellmModel(
            model=litellm_model_name,
            api_key=get_litellm_api_key(litellm_model_name),
            base_url=settings.LITELLM_API_BASE,
        )

    raise ValueError(
        "Este servicio solo admite AI_PROVIDER=litellm para utilizar Gemini"
    )
