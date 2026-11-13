import unittest

from app.services.spring_boot_builder import parse_entities, generate_model, generate_request_dto, generate_service


class DerivedKeyCodegenTest(unittest.TestCase):
    def test_generated_fk_is_one_jpa_join_column_not_duplicate_scalar(self):
        context = {"diagrama": {"contenido": {"nodes": [
            {"id": "c", "data": {"name": "Cliente", "attributes": [{"name": "id", "type": "BIGINT", "primaryKey": True}]}},
            {"id": "v", "data": {"name": "Venta", "attributes": [
                {"name": "id", "type": "BIGINT", "primaryKey": True},
                {"name": "id_cliente", "type": "BIGINT", "foreignKey": True, "primaryKey": False,
                 "_relationshipKey": {"role": "many", "edgeId": "r", "reference": {"nodeId": "c", "attribute": "id"}}},
            ]}},
        ], "edges": [{"id": "r", "source": "c", "target": "v", "data": {
            "relationType": "association", "sourceCardinality": "1", "targetCardinality": "1..*"}}]}}}
        entities, _ = parse_entities(context)
        cliente, venta = [generate_model("com.test", e).content for e in entities]
        self.assertIn('@OneToMany(mappedBy = "cliente")', cliente)
        self.assertIn('@ManyToOne(optional = false)', venta)
        self.assertIn('@JoinColumn(name = "id_cliente", referencedColumnName = "id", nullable = false)', venta)
        self.assertNotIn("private Long idCliente;", venta)
        self.assertIn("private Long id;", venta)
        self.assertIn("@NotNull\n    private Long idCliente;", generate_request_dto("com.test", entities[1]).content)
        self.assertIn("clienteRepository.findById(request.getIdCliente())", generate_service("com.test", entities[1]).content)
