import unittest

from app.agents.image_agent import (
    _normalize_classes,
    _normalize_relations,
    build_image_plan,
    detect_image_mime,
    normalize_cardinality,
)


class ImageAgentTest(unittest.TestCase):
    def test_detects_real_image_signature(self):
        png = b"\x89PNG\r\n\x1a\n" + b"content"
        self.assertEqual(detect_image_mime(png, "application/octet-stream"), "image/png")

        with self.assertRaises(ValueError):
            detect_image_mime(b"not-an-image", "image/png")

    def test_only_accepts_unambiguous_cardinalities(self):
        self.assertEqual(normalize_cardinality("0..*"), "0..*")
        self.assertEqual(normalize_cardinality("uno a muchos"), "1..*")
        self.assertIsNone(normalize_cardinality("*"))
        self.assertIsNone(normalize_cardinality("N"))

    def test_marks_missing_multiplicity_as_a_question(self):
        payload = {
            "classes": [{"name": "Cliente"}, {"name": "Pedido"}],
            "relations": [
                {
                    "sourceName": "Cliente",
                    "targetName": "Pedido",
                    "relationType": "association",
                    "sourceCardinality": "1",
                    "targetCardinality": "*",
                }
            ],
        }
        warnings: list[str] = []
        questions: list[str] = []
        classes = _normalize_classes(payload, warnings)
        relations = _normalize_relations(payload, classes, {}, warnings, questions)

        self.assertEqual(len(relations), 1)
        self.assertIsNone(relations[0].targetCardinality)
        self.assertTrue(any("Pedido" in question for question in questions))
        actions = build_image_plan(classes, relations, {})
        self.assertEqual([action.tool for action in actions], ["create_class", "create_class"])

    def test_updates_existing_class_and_creates_complete_relation(self):
        payload = {
            "classes": [
                {"name": "Cliente", "attributes": [{"name": "id", "primaryKey": True}]},
                {"name": "Pedido"},
            ],
            "relations": [
                {
                    "sourceName": "Cliente",
                    "targetName": "Pedido",
                    "relationType": "association",
                    "sourceCardinality": "1",
                    "targetCardinality": "0..*",
                }
            ],
        }
        context = {
            "diagrama": {
                "contenido": {
                    "nodes": [
                        {
                            "id": "class-cliente",
                            "data": {"name": "Cliente", "attributes": [], "methods": []},
                        }
                    ],
                    "edges": [],
                }
            }
        }
        warnings: list[str] = []
        questions: list[str] = []
        classes = _normalize_classes(payload, warnings)
        relations = _normalize_relations(payload, classes, context, warnings, questions)
        actions = build_image_plan(classes, relations, context)

        self.assertEqual([action.tool for action in actions], [
            "update_class",
            "create_class",
            "create_relation",
        ])
        self.assertEqual(actions[-1].arguments["sourceCardinality"], "1")
        self.assertEqual(actions[-1].arguments["targetCardinality"], "0..*")

    def test_does_not_use_context_classes_as_if_they_were_visible_in_image(self):
        payload = {
            "classes": [{"name": "Cliente"}],
            "relations": [
                {
                    "sourceName": "Cliente",
                    "targetName": "Pedido",
                    "relationType": "association",
                    "sourceCardinality": "1",
                    "targetCardinality": "0..*",
                }
            ],
        }
        context = {
            "diagrama": {
                "contenido": {
                    "nodes": [{"id": "pedido", "data": {"name": "Pedido"}}],
                    "edges": [],
                }
            }
        }
        warnings: list[str] = []
        questions: list[str] = []
        classes = _normalize_classes(payload, warnings)
        relations = _normalize_relations(payload, classes, context, warnings, questions)

        self.assertEqual(relations, [])
        self.assertTrue(any("omitida" in warning for warning in warnings))

    def test_builds_association_class_without_auxiliary_relations(self):
        payload = {
            "classes": [
                {"name": "Usuario"},
                {"name": "Proyecto"},
                {"name": "ProyectoUsuario"},
            ],
            "relations": [
                {
                    "sourceName": "Usuario",
                    "targetName": "Proyecto",
                    "relationType": "associationClass",
                    "associationClassName": "ProyectoUsuario",
                    "sourceCardinality": "1..*",
                    "targetCardinality": "1..*",
                }
            ],
        }
        warnings: list[str] = []
        questions: list[str] = []
        classes = _normalize_classes(payload, warnings)
        relations = _normalize_relations(payload, classes, {}, warnings, questions)
        actions = build_image_plan(classes, relations, {})

        relation_actions = [action for action in actions if action.tool == "create_relation"]
        self.assertEqual(len(relation_actions), 1)
        self.assertEqual(relation_actions[0].arguments["relationType"], "associationClass")
        self.assertEqual(
            relation_actions[0].arguments["associationClassName"],
            "ProyectoUsuario",
        )
        self.assertTrue(all(not action.requires_confirmation for action in actions))
        self.assertEqual(questions, [])

    def test_rejects_association_class_not_visible_as_a_class(self):
        payload = {
            "classes": [{"name": "Usuario"}, {"name": "Proyecto"}],
            "relations": [
                {
                    "sourceName": "Usuario",
                    "targetName": "Proyecto",
                    "relationType": "associationClass",
                    "associationClassName": "ProyectoUsuario",
                    "sourceCardinality": "1",
                    "targetCardinality": "0..*",
                }
            ],
        }
        warnings: list[str] = []
        questions: list[str] = []
        classes = _normalize_classes(payload, warnings)
        _normalize_relations(payload, classes, {}, warnings, questions)

        self.assertTrue(any("ProyectoUsuario" in question for question in questions))

    def test_generalization_ignores_multiplicities(self):
        payload = {
            "classes": [{"name": "Usuario"}, {"name": "Administrador"}],
            "relations": [
                {
                    "sourceName": "Administrador",
                    "targetName": "Usuario",
                    "relationType": "generalization",
                    "sourceCardinality": "1",
                    "targetCardinality": "0..*",
                }
            ],
        }
        warnings: list[str] = []
        questions: list[str] = []
        classes = _normalize_classes(payload, warnings)
        relations = _normalize_relations(payload, classes, {}, warnings, questions)
        actions = build_image_plan(classes, relations, {})

        self.assertIsNone(relations[0].sourceCardinality)
        self.assertIsNone(relations[0].targetCardinality)
        self.assertEqual(questions, [])
        relation_action = actions[-1]
        self.assertEqual(relation_action.arguments["relationType"], "generalization")
        self.assertNotIn("sourceCardinality", relation_action.arguments)
        self.assertNotIn("targetCardinality", relation_action.arguments)


if __name__ == "__main__":
    unittest.main()
