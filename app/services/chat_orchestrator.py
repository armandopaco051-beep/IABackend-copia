from app.agents.planner_agent import run_planner
from app.agents.suggestion_agent import run_suggestion
from app.agents.validation_agent import run_validation
from app.services.diagram_summary import requests_diagram_summary, summarize_diagram


def specialist_summary(summary: str, details: list[str], context: dict):
    result = "\n".join([summary, *details])
    conversation = context.get("conversacion") or {}
    requester = context.get("solicitante") or conversation.get("solicitante") or {}
    if conversation.get("tipo") == "grupal" and requester.get("nombre"):
        result = f"{requester['nombre']}, {result}"
    return result


async def run_chat(message: str, context: dict):
    """Dispatch by the planner's intent, retaining each specialist's contract."""
    if requests_diagram_summary(message):
        summary = summarize_diagram(context)
        return summary.model_copy(update={"summary": specialist_summary(summary.summary, [], context)})

    plan = await run_planner(message, context)
    if plan.intent == "validate_model" and not plan.actions:
        validation = await run_validation(message, context)
        details = [f"{issue.title}: {issue.message}" for issue in validation.issues]
        return plan.model_copy(update={
            "summary": specialist_summary(validation.summary, details, context),
            "actions": [], "can_execute": False,
        })
    if plan.intent == "suggest_model" and not plan.actions:
        suggestion = await run_suggestion(message, context)
        details = [f"{item.title}: {item.message}" for item in suggestion.suggestions]
        return plan.model_copy(update={
            "summary": specialist_summary(suggestion.summary, details, context),
            "actions": [], "can_execute": False,
        })
    return plan
