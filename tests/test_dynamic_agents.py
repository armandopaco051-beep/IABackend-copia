import unittest
from unittest.mock import AsyncMock, patch

from app.schemas.chat import PlannerAction, PlannerResponse
from app.schemas.suggestion import SuggestionResponse
from app.schemas.validation import ValidationResponse
from app.services.plan_grounding import grounding_issues
from app.services.chat_orchestrator import run_chat


def plan(name):
    return PlannerResponse(intent="modify_diagram", summary="Propuesta", can_execute=True,
        actions=[PlannerAction(order=1, tool="create_class", description="Crear entidad", arguments={"name": name})])


class DynamicGroundingTest(unittest.TestCase):
    def test_conceptual_example_does_not_require_matching_diagram_classes(self):
        explanation = PlannerResponse(intent="explain_diagram", summary="Una entidad representa un concepto del dominio.")
        self.assertEqual(grounding_issues("Qué es una clase Cliente en UML", explanation, {}), [])

    def test_accepts_arbitrary_requested_names(self):
        for name in ("Reserva", "Mascota", "Proveedor", "SensorTemperatura"):
            self.assertEqual(grounding_issues(f"agrega una clase {name}", plan(name), {}), [])

    def test_rejects_repeating_previous_example_for_new_subject(self):
        self.assertTrue(grounding_issues("pero y la clase venta?", plan("Cliente"), {}))
        self.assertFalse(grounding_issues("pero y la clase venta?", plan("Venta"), {}))

    def test_named_class_uses_name_after_introducer(self):
        requests = (
            "@ia crea una clase llamada users, que contenga los atributos: id como pk, nombre como string, aplliido como string",
            "Crea una tabla con el nombre de «users»",
        )
        for request in requests:
            with self.subTest(request=request):
                self.assertEqual(grounding_issues(request, plan("users"), {}), [])
                self.assertTrue(grounding_issues(request, plan("Cliente"), {}))

    def test_empty_answer_about_old_class_is_not_a_valid_followup(self):
        stale = PlannerResponse(intent="modify_diagram", summary="Revisar la clase Cliente", can_execute=True)
        self.assertTrue(grounding_issues("pero y la clase venta?", stale, {}))

    def test_rejects_duplicate_class_from_actual_diagram(self):
        context = {"diagrama": {"contenido": {"nodes": [{"id": "x", "data": {"name": "Reserva"}}]}}}
        self.assertTrue(grounding_issues("agrega clase Reserva", plan("Reserva"), context))

    def test_quoted_multiword_names_and_exact_existing_targets(self):
        request = 'Incorpora una entidad de nombre «Detalle Venta»'
        self.assertFalse(grounding_issues(request, plan("Detalle Venta"), {}))
        self.assertTrue(grounding_issues(request, plan("Detalle Compra"), {}))
        context = {"diagrama": {"contenido": {"nodes": [
            {"id": "a", "data": {"name": "Cliente"}},
            {"id": "b", "data": {"name": "Cliente Premium"}},
        ]}}}
        wrong = PlannerResponse(intent="modify_diagram", summary="Propuesta", actions=[
            PlannerAction(order=1, tool="delete_class", description="Eliminar", arguments={"classId": "b"}),
        ])
        self.assertTrue(grounding_issues("Suprime la tabla Cliente", wrong, context))


class OrchestrationTest(unittest.IsolatedAsyncioTestCase):
    @patch("app.services.chat_orchestrator.run_validation", new_callable=AsyncMock)
    @patch("app.services.chat_orchestrator.run_suggestion", new_callable=AsyncMock)
    @patch("app.services.chat_orchestrator.run_planner", new_callable=AsyncMock)
    async def test_general_database_question_keeps_explanation_without_modifications(self, planner, suggestion, validation):
        planner.return_value = PlannerResponse(intent="explain_diagram", summary="Una clave foránea referencia una clave de otra tabla.")
        result = await run_chat("Qué es una clave foránea y cuándo se usa", {"diagrama": {"contenido": {"nodes": [], "edges": []}}})
        self.assertEqual(result.intent, "explain_diagram")
        self.assertFalse(result.can_execute)
        self.assertEqual(result.actions, [])
        suggestion.assert_not_awaited()
        validation.assert_not_awaited()

    @patch("app.services.chat_orchestrator.run_validation", new_callable=AsyncMock)
    @patch("app.services.chat_orchestrator.run_suggestion", new_callable=AsyncMock)
    @patch("app.services.chat_orchestrator.run_planner", new_callable=AsyncMock)
    async def test_suggestion_calls_its_specialist_only(self, planner, suggestion, validation):
        planner.return_value = PlannerResponse(intent="suggest_model", summary="Analizar")
        suggestion.return_value = SuggestionResponse(summary="Mejora de las entidades actuales")
        result = await run_chat("Sugiere mejoras", {"diagrama": {"id": 8}})
        suggestion.assert_awaited_once()
        validation.assert_not_awaited()
        self.assertEqual(result.summary, "Mejora de las entidades actuales")

    @patch("app.services.chat_orchestrator.run_validation", new_callable=AsyncMock)
    @patch("app.services.chat_orchestrator.run_suggestion", new_callable=AsyncMock)
    @patch("app.services.chat_orchestrator.run_planner", new_callable=AsyncMock)
    async def test_validation_calls_its_specialist_only(self, planner, suggestion, validation):
        planner.return_value = PlannerResponse(intent="validate_model", summary="Analizar")
        validation.return_value = ValidationResponse(summary="Diagrama correcto", valid=True, score=90)
        await run_chat("Valida el diagrama", {})
        validation.assert_awaited_once()
        suggestion.assert_not_awaited()

    @patch("app.services.chat_orchestrator.run_validation", new_callable=AsyncMock)
    @patch("app.services.chat_orchestrator.run_suggestion", new_callable=AsyncMock)
    @patch("app.services.chat_orchestrator.run_planner", new_callable=AsyncMock)
    async def test_colloquial_review_and_suggestions_reach_specialists(self, planner, suggestion, validation):
        context = {"diagrama": {"id": 8}}
        validation.return_value = ValidationResponse(summary="Revisión", valid=True, score=90)
        suggestion.return_value = SuggestionResponse(summary="Mejoras")
        for message, intent in (
            ("@IA ¿Ves algo raro en mi diagrama?", "validate_model"),
            ("¿Están bien estas relaciones?", "validate_model"),
            ("¿Qué le falta a este modelo?", "suggest_model"),
            ("¿Cómo podría mejorar mi diseño?", "suggest_model"),
        ):
            with self.subTest(message=message):
                result = await run_chat(message, context)
                self.assertEqual(result.intent, intent)
                self.assertFalse(result.can_execute)
                self.assertEqual(result.actions, [])
        self.assertEqual(validation.await_count, 2)
        self.assertEqual(suggestion.await_count, 2)
        planner.assert_not_awaited()

        planner.return_value = plan("Pedido")
        result = await run_chat("Revisa mi diagrama y agrega la clase Pedido", context)
        self.assertEqual(result.actions[0].tool, "create_class")
        planner.assert_awaited_once()
