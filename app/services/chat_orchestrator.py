import re
import unicodedata

from app.agents.planner_agent import run_planner
from app.agents.suggestion_agent import run_suggestion
from app.agents.validation_agent import run_validation
from app.services.diagram_summary import requests_diagram_summary, summarize_diagram
from app.schemas.chat import PlannerResponse


def review_intent(message: str, context: dict):
    text = ''.join(
        char for char in unicodedata.normalize('NFKD', message.casefold())
        if not unicodedata.combining(char)
    )
    # Leave explicit diagram edits and conceptual questions to the planner.
    if re.search(r'\b(?:crea|agrega|anade|incorpora|elimina|borra|quita|modifica|actualiza|'
                 r'cambia|relaciona|conecta|une|enlaza|asocia|vincula|desvincula|desconecta|aplica|renombra|corrige|arregla)\b', text):
        return None
    if re.search(r'\b(?:que es|que significa|cuando se usa|como funciona)\b', text):
        return None

    mentions_model = re.search(r'\b(?:diagrama|modelo|diseno|clases|tablas|atributos|relaciones|multiplicidades)\b', text)
    if not (context.get('diagrama') or mentions_model):
        return None

    asks_review = re.search(r'\b(?:valida(?:me)?|revisa(?:me)?|verifica(?:me)?|comprueba|'
                            r'detecta|encuentra)\b', text)
    asks_correctness = re.search(
        r'\b(?:inconsistencias?|incoherencias?|errores?|algo raro|algo mal|'
        r'esta(?:n)? bien|(?:es|son) correct[oa]s?|tiene sentido)\b', text,
    )
    if (asks_review and mentions_model) or asks_correctness:
        return 'validate_model'
    if re.search(r'\b(?:sugiere(?:me)?|recomienda(?:me)?|sugerencias|recomendaciones|'
                 r'que (?:le )?falta(?:n)?|que (?:mas )?(?:puedo|podria|conviene) agregar|'
                 r'como (?:puedo |podria )?mejorar|que (?:mejorarias|anadirias|agregarias)|'
                 r'que (?:clases|tablas|atributos|relaciones) (?:le )?faltan)\b', text):
        return 'suggest_model'
    return None


def specialist_summary(summary: str, details: list[str], context: dict):
    result = "\n".join([summary, *details])
    conversation = context.get("conversacion") or {}
    requester = context.get("solicitante") or conversation.get("solicitante") or {}
    if conversation.get("tipo") == "grupal" and requester.get("nombre"):
        result = f"{requester['nombre']}, {result}"
    return result


async def run_chat(message: str, context: dict):
    """Dispatch by the planner's intent, retaining each specialist's contract."""
    review = review_intent(message, context)
    if review is None and requests_diagram_summary(message):
        summary = summarize_diagram(context)
        return summary.model_copy(update={"summary": specialist_summary(summary.summary, [], context)})

    plan = PlannerResponse(intent=review, summary='') if review else await run_planner(message, context)
    if plan.intent == "validate_model" and not plan.actions:
        validation = await run_validation(message, context)
        details = [f"{issue.title}: {issue.message}" for issue in validation.issues]
        return plan.model_copy(update={
            "summary": specialist_summary(validation.summary, details, context),
            "actions": [], "questions": [], "can_execute": False,
        })
    if plan.intent == "suggest_model" and not plan.actions:
        suggestion = await run_suggestion(message, context)
        details = [f"{item.title}: {item.message}" for item in suggestion.suggestions]
        return plan.model_copy(update={
            "summary": specialist_summary(suggestion.summary, details, context),
            "actions": [], "questions": [], "can_execute": False,
        })
    return plan
