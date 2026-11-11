import unittest
from unittest.mock import AsyncMock, patch

from app.config.agents_models import select_text_provider
from app.services.chat_orchestrator import run_chat
from app.services.diagram_summary import requests_diagram_summary


class DiagramSummaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_summary_uses_active_diagram_for_both_providers(self):
        context = {
            'proyecto': {'nombre': 'Restaurante', 'descripcion': 'Gestionar pedidos de clientes.'},
            'diagrama': {'nombre': 'Pedidos', 'contenido': {
                'nodes': [{'id': 'c', 'data': {'name': 'Cliente'}}, {'id': 'p', 'data': {'name': 'Pedido'}}],
                'edges': [{'source': 'c', 'target': 'p', 'data': {
                    'relationType': 'association', 'sourceCardinality': '1', 'targetCardinality': '1..*',
                }}],
            }},
            'conversacion': {'tipo': 'grupal', 'solicitante': {'nombre': 'Armando'}},
        }
        with patch('app.services.chat_orchestrator.run_planner', new_callable=AsyncMock) as planner:
            for provider in ('gemini', 'local'):
                with self.subTest(provider=provider), select_text_provider(provider):
                    result = await run_chat('dame contexto de este diagrama para que funciona', context)
                    self.assertEqual(result.intent, 'explain_diagram')
                    self.assertTrue(result.summary.startswith('Armando,'))
                    self.assertIn('Gestionar pedidos', result.summary)
                    self.assertIn('Cliente → Pedido', result.summary)
                    self.assertFalse(result.can_execute)
                    self.assertEqual(result.actions, [])
                    self.assertEqual(result.questions, [])
            planner.assert_not_awaited()

    def test_explicit_edit_keeps_normal_planner_flow(self):
        self.assertFalse(requests_diagram_summary('Resume el diagrama y agrega la clase Cliente'))
        self.assertTrue(requests_diagram_summary('¿Para qué sirve este diagrama?'))
