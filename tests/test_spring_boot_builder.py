import json
import re
import unittest

from app.services.spring_boot_builder import build_spring_boot_project


class SpringBootBuilderMetadataTest(unittest.TestCase):
    def test_generates_mobile_discovery_contract(self):
        context = {
            "diagrama": {
                "contenido": {
                    "nodes": [
                        {
                            "data": {
                                "name": "Producto",
                                "attributes": [
                                    {
                                        "name": "id",
                                        "type": "BIGINT",
                                        "primaryKey": True,
                                        "nullable": False,
                                    },
                                    {
                                        "name": "nombre",
                                        "type": "VARCHAR",
                                        "nullable": False,
                                    },
                                ],
                            }
                        }
                    ]
                }
            }
        }

        files, _ = build_spring_boot_project(
            context,
            "restaurante-api",
            "com.drawschema.generated",
            "restaurante",
        )
        by_path = {generated.path: generated.content for generated in files}
        controller = by_path[
            "src/main/java/com/drawschema/generated/controllers/BackendMetadataController.java"
        ]
        properties = by_path["src/main/resources/application.properties"]
        pom = by_path["pom.xml"]
        mdns_publisher = by_path[
            "src/main/java/com/drawschema/generated/config/MdnsServicePublisher.java"
        ]
        producto_model = by_path[
            "src/main/java/com/drawschema/generated/models/Producto.java"
        ]
        producto_request = by_path[
            "src/main/java/com/drawschema/generated/dto/ProductoRequest.java"
        ]
        readme = by_path["README.md"]

        match = re.search(r'SCHEMA_JSON = """\n(.*?)\n\s*""";', controller, re.S)
        self.assertIsNotNone(match)
        schema = json.loads(match.group(1))

        self.assertEqual(schema["proyecto"], "restaurante-api")
        self.assertEqual(schema["entidades"][0]["endpoint"], "/api/productos")
        self.assertTrue(schema["entidades"][0]["atributos"]["nombre"]["required"])
        self.assertIn("server.address=0.0.0.0", properties)
        self.assertIn("server.port=${SERVER_PORT:8086}", properties)
        self.assertIn("drawschema.discovery.enabled=true", properties)
        self.assertIn("<artifactId>jmdns</artifactId>", pom)
        self.assertIn('SERVICE_TYPE = "_drawschema._tcp.local."', mdns_publisher)
        self.assertIn('properties.put("project", "restaurante-api")', mdns_publisher)
        self.assertIn("@GeneratedValue(strategy = GenerationType.IDENTITY)", producto_model)
        self.assertNotIn("private Long id;", producto_request)
        self.assertIn("| GET | `/api/productos` | Listar Producto |", readme)
        self.assertIn("| POST | `/api/productos` | Crear Producto |", readme)
        self.assertIn('"nombre": "ejemplo"', readme)
        self.assertNotIn('"id":', readme)
        self.assertIn("$env:DB_PASSWORD=\"tu_password\"", readme)

    def test_generates_composition_with_cardinality_and_lifecycle(self):
        context = {
            "diagrama": {
                "contenido": {
                    "nodes": [
                        {"id": "order", "data": {"name": "Pedido", "attributes": []}},
                        {"id": "item", "data": {"name": "DetallePedido", "attributes": []}},
                    ],
                    "edges": [
                        {
                            "id": "composition-1",
                            "source": "order",
                            "target": "item",
                            "data": {
                                "relationType": "composition",
                                "sourceClassId": "order",
                                "targetClassId": "item",
                                "sourceCardinality": "1",
                                "targetCardinality": "1..*",
                            },
                        }
                    ],
                }
            }
        }

        files, _ = build_spring_boot_project(
            context, "pedidos-api", "com.drawschema.generated", "pedidos"
        )
        by_path = {generated.path: generated.content for generated in files}
        pedido = by_path["src/main/java/com/drawschema/generated/models/Pedido.java"]

        self.assertIn(
            "@OneToMany(cascade = CascadeType.ALL, orphanRemoval = true)", pedido
        )
        self.assertIn("private List<DetallePedido> detallePedidos", pedido)

    def test_generates_aggregation_without_delete_cascade(self):
        context = {
            "diagrama": {
                "contenido": {
                    "nodes": [
                        {"id": "team", "data": {"name": "Equipo", "attributes": []}},
                        {"id": "player", "data": {"name": "Jugador", "attributes": []}},
                    ],
                    "edges": [
                        {
                            "id": "aggregation-1",
                            "source": "team",
                            "target": "player",
                            "data": {
                                "relationType": "aggregation",
                                "sourceClassId": "team",
                                "targetClassId": "player",
                                "sourceCardinality": "0..*",
                                "targetCardinality": "0..*",
                            },
                        }
                    ],
                }
            }
        }

        files, _ = build_spring_boot_project(
            context, "equipos-api", "com.drawschema.generated", "equipos"
        )
        by_path = {generated.path: generated.content for generated in files}
        equipo = by_path["src/main/java/com/drawschema/generated/models/Equipo.java"]

        self.assertIn("@ManyToMany", equipo)
        self.assertNotIn("orphanRemoval", equipo)
        self.assertNotIn("CascadeType.ALL", equipo)

    def test_generates_generalization_as_joined_inheritance_without_multiplicity(self):
        context = {
            "diagrama": {
                "contenido": {
                    "nodes": [
                        {
                            "id": "user",
                            "data": {
                                "name": "Usuario",
                                "attributes": [
                                    {"name": "id", "type": "BIGINT", "primaryKey": True}
                                ],
                            },
                        },
                        {
                            "id": "admin",
                            "data": {"name": "Administrador", "attributes": []},
                        },
                    ],
                    "edges": [
                        {
                            "id": "generalization-1",
                            "source": "admin",
                            "target": "user",
                            "data": {
                                "relationType": "generalization",
                                "sourceClassId": "admin",
                                "targetClassId": "user",
                                "sourceCardinality": "1",
                                "targetCardinality": "0..*",
                            },
                        }
                    ],
                }
            }
        }

        files, _ = build_spring_boot_project(
            context, "usuarios-api", "com.drawschema.generated", "usuarios"
        )
        by_path = {generated.path: generated.content for generated in files}
        usuario = by_path["src/main/java/com/drawschema/generated/models/Usuario.java"]
        administrador = by_path[
            "src/main/java/com/drawschema/generated/models/Administrador.java"
        ]

        self.assertIn("@Inheritance(strategy = InheritanceType.JOINED)", usuario)
        self.assertIn("public class Administrador extends Usuario", administrador)
        self.assertNotIn("@OneToMany", administrador)

    def test_generates_association_class_with_embedded_id_and_maps_id(self):
        context = {
            "diagrama": {
                "contenido": {
                    "nodes": [
                        {
                            "id": "user",
                            "data": {
                                "name": "Usuario",
                                "attributes": [
                                    {"name": "id", "type": "BIGINT", "primaryKey": True}
                                ],
                            },
                        },
                        {
                            "id": "project",
                            "data": {
                                "name": "Proyecto",
                                "attributes": [
                                    {"name": "id", "type": "BIGINT", "primaryKey": True}
                                ],
                            },
                        },
                        {
                            "id": "membership",
                            "data": {
                                "name": "ProyectoUsuario",
                                "attributes": [
                                    {
                                        "name": "id_usuario",
                                        "type": "BIGINT",
                                        "primaryKey": True,
                                        "foreignKey": True,
                                        "nullable": False,
                                    },
                                    {
                                        "name": "id_proyecto",
                                        "type": "BIGINT",
                                        "primaryKey": True,
                                        "foreignKey": True,
                                        "nullable": False,
                                    },
                                    {"name": "rol", "type": "VARCHAR", "nullable": False},
                                ],
                            },
                        },
                    ],
                    "edges": [
                        {
                            "id": "association-class-1",
                            "source": "user",
                            "target": "project",
                            "data": {
                                "relationType": "associationClass",
                                "sourceClassId": "user",
                                "targetClassId": "project",
                                "associationClassId": "membership",
                                "sourceCardinality": "0..*",
                                "targetCardinality": "0..*",
                            },
                        }
                    ],
                }
            }
        }

        files, warnings = build_spring_boot_project(
            context, "proyectos-api", "com.drawschema.generated", "proyectos"
        )
        by_path = {generated.path: generated.content for generated in files}
        base = "src/main/java/com/drawschema/generated"
        embedded_id = by_path[f"{base}/models/ProyectoUsuarioId.java"]
        model = by_path[f"{base}/models/ProyectoUsuario.java"]
        request = by_path[f"{base}/dto/ProyectoUsuarioRequest.java"]
        repository = by_path[f"{base}/repositories/ProyectoUsuarioRepository.java"]
        service = by_path[f"{base}/services/ProyectoUsuarioService.java"]
        controller = by_path[f"{base}/controllers/ProyectoUsuarioController.java"]
        metadata = by_path[f"{base}/controllers/BackendMetadataController.java"]
        readme = by_path["README.md"]

        self.assertIn('@Column(name = "id_usuario")', embedded_id)
        self.assertIn('@Column(name = "id_proyecto")', embedded_id)
        self.assertIn("@EmbeddedId", model)
        self.assertIn('@MapsId("idUsuario")', model)
        self.assertIn('@MapsId("idProyecto")', model)
        self.assertEqual(model.count("@ManyToOne(optional = false)"), 2)
        self.assertIn('private Long idUsuario;', request)
        self.assertIn('private Long idProyecto;', request)
        self.assertIn(
            "import com.drawschema.generated.models.ProyectoUsuarioId;",
            repository,
        )
        self.assertIn(
            "setId(new ProyectoUsuarioId(request.getIdUsuario(), request.getIdProyecto()))",
            service,
        )
        self.assertIn("usuarioRepository.findById(request.getIdUsuario())", service)
        self.assertIn("proyectoRepository.findById(request.getIdProyecto())", service)
        self.assertIn('@GetMapping("/{idUsuario}/{idProyecto}")', controller)
        match = re.search(r'SCHEMA_JSON = """\n(.*?)\n\s*""";', metadata, re.S)
        self.assertIsNotNone(match)
        schema = json.loads(match.group(1))
        membership_schema = next(
            item for item in schema["entidades"] if item["nombre"] == "ProyectoUsuario"
        )
        self.assertEqual(
            membership_schema["rutaDetalle"],
            "/api/proyecto-usuarios/{idUsuario}/{idProyecto}",
        )
        self.assertEqual(
            [item["nombre"] for item in membership_schema["id"]["campos"]],
            ["idUsuario", "idProyecto"],
        )
        self.assertFalse(any("revision manual" in warning for warning in warnings))
        self.assertIn(
            "`/api/proyecto-usuarios/{idUsuario}/{idProyecto}`",
            readme,
        )
        self.assertIn('"idUsuario": 1', readme)
        self.assertIn('"idProyecto": 1', readme)

    def test_natural_primary_key_is_received_in_request(self):
        context = {
            "diagrama": {
                "contenido": {
                    "nodes": [
                        {
                            "id": "user",
                            "data": {
                                "name": "Usuario",
                                "attributes": [
                                    {
                                        "name": "codigo",
                                        "type": "VARCHAR",
                                        "primaryKey": True,
                                        "nullable": False,
                                    }
                                ],
                            },
                        }
                    ],
                    "edges": [],
                }
            }
        }

        files, _ = build_spring_boot_project(
            context, "usuarios-api", "com.drawschema.generated", "usuarios"
        )
        by_path = {generated.path: generated.content for generated in files}
        base = "src/main/java/com/drawschema/generated"

        self.assertNotIn(
            "@GeneratedValue",
            by_path[f"{base}/models/Usuario.java"],
        )
        self.assertIn(
            "private String codigo;",
            by_path[f"{base}/dto/UsuarioRequest.java"],
        )
        self.assertIn(
            "usuario.setCodigo(request.getCodigo());",
            by_path[f"{base}/services/UsuarioService.java"],
        )


if __name__ == "__main__":
    unittest.main()
