import unittest

from app.tools.diagram_tools import (
    build_create_relation_body,
    build_update_relation_body,
)


DIAGRAM = {
    "contenido": {
        "nodes": [
            {"id": "child", "data": {"name": "Administrador"}},
            {"id": "parent", "data": {"name": "Usuario"}},
        ],
        "edges": [
            {
                "id": "inheritance-1",
                "source": "child",
                "target": "parent",
                "type": "umlRelation",
                "data": {
                    "relationType": "generalization",
                    "sourceClassId": "child",
                    "targetClassId": "parent",
                    "sourceCardinality": "1",
                    "targetCardinality": "0..*",
                },
            }
        ],
    }
}


class DiagramToolsCardinalityTest(unittest.TestCase):
    def test_create_generalization_does_not_send_cardinality(self):
        body = build_create_relation_body(
            {
                "sourceName": "Administrador",
                "targetName": "Usuario",
                "relationType": "generalization",
                "sourceCardinality": "1",
                "targetCardinality": "0..*",
            },
            DIAGRAM,
            "13078084",
        )

        self.assertNotIn("sourceCardinality", body["data"])
        self.assertNotIn("targetCardinality", body["data"])
        self.assertEqual(body["data"]["childClassId"], "child")
        self.assertEqual(body["data"]["parentClassId"], "parent")

    def test_update_generalization_cleans_legacy_cardinality(self):
        body = build_update_relation_body(
            {"relationType": "generalization"},
            DIAGRAM,
            "inheritance-1",
            "13078084",
        )

        self.assertNotIn("sourceCardinality", body["data"])
        self.assertNotIn("targetCardinality", body["data"])

    def test_rejects_composition_with_multiple_wholes(self):
        with self.assertRaisesRegex(ValueError, "solo puede pertenecer a un Todo"):
            build_create_relation_body(
                {
                    "sourceName": "Usuario",
                    "targetName": "Administrador",
                    "relationType": "composition",
                    "sourceCardinality": "0..*",
                    "targetCardinality": "1..*",
                },
                DIAGRAM,
                "13078084",
            )


if __name__ == "__main__":
    unittest.main()
