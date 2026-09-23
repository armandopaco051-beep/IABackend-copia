from typing import Any

from app.schemas.chat import PlannerAction
from app.schemas.diagram_execution import DiagramActionResult
from app.services.backend_client import (
    create_class,
    create_relation,
    delete_class,
    delete_relation,
    get_diagrama,
    move_class,
    update_class,
    update_relation,
)

#va ser el conjunto de herramientas que se pueden usar en el diagrama
SUPPORTED_TOOLS_V1 = {
    "create_class",
    "update_class",
    "delete_class",
    "move_class",
    "create_relation",
    "update_relation",
    "delete_relation",
    "ask_user",
}


VALID_RELATION_TYPES = {
    "association",
    "generalization",
    "composition",
    "aggregation",
    "associationClass",
    "realization",
    "templateBinding",
}


VALID_CARDINALITIES = {
    "1",
    "0..1",
    "0..*",
    "1..*",
}

RELATION_TYPES_WITHOUT_CARDINALITY = {"generalization"}

# hace la extraccion de los nodos del diagrama
def get_nodes(diagrama: dict[str, Any]):
    contenido = diagrama.get("contenido") or {}
    nodes = contenido.get("nodes") or []
    return nodes if isinstance(nodes, list) else []


def get_edges(diagrama: dict[str, Any]):
    contenido = diagrama.get("contenido") or {}
    edges = contenido.get("edges") or []
    return edges if isinstance(edges, list) else []


# hace la busqueda de una clase por nombre
def find_class_by_name(diagrama: dict[str, Any], class_name: str):
    expected = class_name.strip().lower()

    for node in get_nodes(diagrama):
        data = node.get("data") or {}
        name = str(data.get("name") or "").strip().lower()

        if name == expected:
            return node

    return None


def find_class_by_id(diagrama: dict[str, Any], class_id: str):
    for node in get_nodes(diagrama):
        if str(node.get("id") or "") == class_id:
            return node

    return None


def resolve_class_id(arguments: dict[str, Any], diagrama: dict[str, Any]):
    class_id = (
        arguments.get("classId")
        or arguments.get("clase_id")
        or arguments.get("claseId")
        or arguments.get("nodeId")
        or arguments.get("id")
    )

    if class_id:
        class_id = str(class_id)

        if find_class_by_id(diagrama, class_id) is None:
            raise ValueError(f"No se encontro la clase con id: {class_id}")

        return class_id

    class_name = (
        arguments.get("className")
        or arguments.get("currentName")
        or arguments.get("oldName")
        or arguments.get("targetName")
        or arguments.get("name")
    )

    if not class_name:
        raise ValueError("La accion necesita classId o className")

    node = find_class_by_name(diagrama, str(class_name))

    if node is None:
        raise ValueError(f"No se encontro la clase: {class_name}")

    return str(node["id"])


def find_relation_by_id(diagrama: dict[str, Any], relation_id: str):
    for edge in get_edges(diagrama):
        if str(edge.get("id") or "") == relation_id:
            return edge

    return None


def find_relation_by_names(
    diagrama: dict[str, Any],
    source_name: str,
    target_name: str,
    relation_type: str | None = None,
):
    source_node = find_class_by_name(diagrama, source_name)
    target_node = find_class_by_name(diagrama, target_name)

    if source_node is None:
        raise ValueError(f"No se encontro la clase origen: {source_name}")

    if target_node is None:
        raise ValueError(f"No se encontro la clase destino: {target_name}")

    source_id = str(source_node["id"])
    target_id = str(target_node["id"])

    for edge in get_edges(diagrama):
        data = edge.get("data") or {}
        edge_relation_type = data.get("relationType")

        if edge.get("source") != source_id or edge.get("target") != target_id:
            continue

        if relation_type and edge_relation_type != relation_type:
            continue

        return edge

    return None


def resolve_relation_id(arguments: dict[str, Any], diagrama: dict[str, Any]):
    relation_id = (
        arguments.get("relationId")
        or arguments.get("relacion_id")
        or arguments.get("edgeId")
        or arguments.get("id")
    )

    if relation_id:
        relation_id = str(relation_id)

        if find_relation_by_id(diagrama, relation_id) is None:
            raise ValueError(f"No se encontro la relacion con id: {relation_id}")

        return relation_id

    source_name = arguments.get("sourceName")
    target_name = arguments.get("targetName")
    relation_type = arguments.get("relationType")

    if not source_name or not target_name:
        raise ValueError("La accion necesita relationId o sourceName/targetName")

    edge = find_relation_by_names(
        diagrama,
        str(source_name),
        str(target_name),
        str(relation_type) if relation_type else None,
    )

    if edge is None:
        raise ValueError(
            f"No se encontro la relacion entre {source_name} y {target_name}"
        )

    return str(edge["id"])


# hace la normalizacion de los atributos
def normalize_attributes(arguments: dict[str, Any]):
    attributes = arguments.get("attributes", [])
    return attributes if isinstance(attributes, list) else []


# hace la normalizacion de los metodos
def normalize_methods(arguments: dict[str, Any]):
    methods = arguments.get("methods", [])
    return methods if isinstance(methods, list) else []


# hace la construccion del body para crear una clase
def build_create_class_body(arguments: dict[str, Any], autor_codigo: str):
    name = str(arguments.get("name") or "").strip()

    if not name:
        raise ValueError("create_class necesita arguments.name")

    return {
        "id": arguments.get("id"),
        "name": name,
        "x": arguments.get("x", 100),
        "y": arguments.get("y", 100),
        "attributes": normalize_attributes(arguments),
        "methods": normalize_methods(arguments),
        "kind": arguments.get("kind", "class"),
        "templateParameters": arguments.get("templateParameters", []),
        "autor_codigo": autor_codigo,
    }


def build_update_class_body(arguments: dict[str, Any], autor_codigo: str):
    body: dict[str, Any] = {
        "autor_codigo": autor_codigo,
    }

    new_name = arguments.get("newName")

    if new_name is None and "name" in arguments:
        new_name = arguments.get("name")

    if new_name is not None:
        body["name"] = str(new_name).strip()

        if not body["name"]:
            raise ValueError("update_class recibio un name vacio")

    if "attributes" in arguments:
        body["attributes"] = normalize_attributes(arguments)

    if "methods" in arguments:
        body["methods"] = normalize_methods(arguments)

    if "kind" in arguments:
        body["kind"] = arguments["kind"]

    if "templateParameters" in arguments:
        body["templateParameters"] = arguments["templateParameters"]

    if len(body) == 1:
        raise ValueError(
            "update_class necesita name, attributes, methods, kind o templateParameters"
        )

    return body


def build_move_class_body(arguments: dict[str, Any], autor_codigo: str):
    x = arguments.get("x")
    y = arguments.get("y")

    if x is None or y is None:
        position = arguments.get("position") or {}
        x = position.get("x")
        y = position.get("y")

    if x is None or y is None:
        raise ValueError("move_class necesita x/y o position.x/position.y")

    return {
        "x": float(x),
        "y": float(y),
        "autor_codigo": autor_codigo,
    }


# hace la construccion del body para crear una relacion
def build_create_relation_body(
    arguments: dict[str, Any],
    diagrama: dict[str, Any],
    autor_codigo: str,
):
    relation_type = arguments.get("relationType", "association")

    if relation_type not in VALID_RELATION_TYPES:
        raise ValueError(f"Tipo de relacion no permitido: {relation_type}")

    source_id = arguments.get("source") or arguments.get("sourceClassId")
    target_id = arguments.get("target") or arguments.get("targetClassId")

    if not source_id and arguments.get("sourceName"):
        source_node = find_class_by_name(diagrama, str(arguments["sourceName"]))

        if source_node is None:
            raise ValueError(f"No se encontro la clase origen: {arguments['sourceName']}")

        source_id = source_node["id"]

    if not target_id and arguments.get("targetName"):
        target_node = find_class_by_name(diagrama, str(arguments["targetName"]))

        if target_node is None:
            raise ValueError(f"No se encontro la clase destino: {arguments['targetName']}")

        target_id = target_node["id"]

    if not source_id or not target_id:
        raise ValueError("create_relation necesita source/target o sourceName/targetName")

    data = {
        "relationType": relation_type,
        "sourceClassId": source_id,
        "targetClassId": target_id,
    }

    if relation_type not in RELATION_TYPES_WITHOUT_CARDINALITY:
        source_cardinality = arguments.get("sourceCardinality", "1")
        target_cardinality = arguments.get("targetCardinality", "0..*")

        if source_cardinality not in VALID_CARDINALITIES:
            raise ValueError(f"Cardinalidad origen no permitida: {source_cardinality}")

        if target_cardinality not in VALID_CARDINALITIES:
            raise ValueError(f"Cardinalidad destino no permitida: {target_cardinality}")

        if relation_type == "composition" and source_cardinality not in {"1", "0..1"}:
            raise ValueError(
                "En composition, sourceCardinality debe ser 1 o 0..1 porque una Parte "
                "solo puede pertenecer a un Todo"
            )

        data["sourceCardinality"] = source_cardinality
        data["targetCardinality"] = target_cardinality

    if relation_type == "generalization":
        data["childClassId"] = source_id
        data["parentClassId"] = target_id

    if relation_type in {"composition", "aggregation"}:
        data["wholeClassId"] = source_id
        data["partClassId"] = target_id

    association_class_id = arguments.get("associationClassId")
    association_class_name = arguments.get("associationClassName")
    if not association_class_id and association_class_name:
        association_node = find_class_by_name(diagrama, str(association_class_name))
        if association_node is None:
            raise ValueError(
                f"No se encontro la clase de asociacion: {association_class_name}"
            )
        association_class_id = association_node["id"]
    if relation_type == "associationClass" and not association_class_id:
        raise ValueError("associationClass necesita associationClassId o associationClassName")
    if association_class_id:
        data["associationClassId"] = association_class_id

    for optional_key in (
        "sourceRole",
        "targetRole",
        "templateBindings",
        "name",
    ):
        if optional_key in arguments:
            data[optional_key] = arguments[optional_key]

    return {
        "id": arguments.get("id"),
        "source": source_id,
        "target": target_id,
        "type": "umlRelation",
        "data": data,
        "autor_codigo": autor_codigo,
    }


def build_update_relation_body(
    arguments: dict[str, Any],
    diagrama: dict[str, Any],
    relation_id: str,
    autor_codigo: str,
):
    edge = find_relation_by_id(diagrama, relation_id)

    if edge is None:
        raise ValueError(f"No se encontro la relacion con id: {relation_id}")

    source_id = arguments.get("source") or arguments.get("sourceClassId")
    target_id = arguments.get("target") or arguments.get("targetClassId")

    if not source_id and arguments.get("sourceName"):
        source_node = find_class_by_name(diagrama, str(arguments["sourceName"]))

        if source_node is None:
            raise ValueError(f"No se encontro la clase origen: {arguments['sourceName']}")

        source_id = source_node["id"]

    if not target_id and arguments.get("targetName"):
        target_node = find_class_by_name(diagrama, str(arguments["targetName"]))

        if target_node is None:
            raise ValueError(f"No se encontro la clase destino: {arguments['targetName']}")

        target_id = target_node["id"]

    source_id = str(source_id or edge.get("source"))
    target_id = str(target_id or edge.get("target"))
    relation_type = arguments.get("relationType")

    if relation_type is None:
        relation_type = (edge.get("data") or {}).get("relationType", "association")

    if relation_type not in VALID_RELATION_TYPES:
        raise ValueError(f"Tipo de relacion no permitido: {relation_type}")

    data = {
        **(edge.get("data") or {}),
        "relationType": relation_type,
        "sourceClassId": source_id,
        "targetClassId": target_id,
    }

    if relation_type in RELATION_TYPES_WITHOUT_CARDINALITY:
        data.pop("sourceCardinality", None)
        data.pop("targetCardinality", None)
        data.pop("cardinality", None)
    else:
        source_cardinality = arguments.get("sourceCardinality")
        if source_cardinality is None:
            source_cardinality = (edge.get("data") or {}).get("sourceCardinality", "1")

        target_cardinality = arguments.get("targetCardinality")
        if target_cardinality is None:
            target_cardinality = (edge.get("data") or {}).get("targetCardinality", "0..*")

        if source_cardinality not in VALID_CARDINALITIES:
            raise ValueError(f"Cardinalidad origen no permitida: {source_cardinality}")

        if target_cardinality not in VALID_CARDINALITIES:
            raise ValueError(f"Cardinalidad destino no permitida: {target_cardinality}")

        if relation_type == "composition" and source_cardinality not in {"1", "0..1"}:
            raise ValueError(
                "En composition, sourceCardinality debe ser 1 o 0..1 porque una Parte "
                "solo puede pertenecer a un Todo"
            )

        data["sourceCardinality"] = source_cardinality
        data["targetCardinality"] = target_cardinality

    association_class_id = arguments.get("associationClassId")
    association_class_name = arguments.get("associationClassName")
    if not association_class_id and association_class_name:
        association_node = find_class_by_name(diagrama, str(association_class_name))
        if association_node is None:
            raise ValueError(
                f"No se encontro la clase de asociacion: {association_class_name}"
            )
        association_class_id = association_node["id"]
    if association_class_id:
        data["associationClassId"] = association_class_id

    if relation_type == "generalization":
        data["childClassId"] = source_id
        data["parentClassId"] = target_id

    if relation_type in {"composition", "aggregation"}:
        data["wholeClassId"] = source_id
        data["partClassId"] = target_id

    for optional_key in (
        "sourceRole",
        "targetRole",
        "templateBindings",
        "name",
    ):
        if optional_key in arguments:
            data[optional_key] = arguments[optional_key]

    return {
        "source": source_id,
        "target": target_id,
        "type": arguments.get("type", edge.get("type", "umlRelation")),
        "data": data,
        "autor_codigo": autor_codigo,
    }


# hace la ejecucion de la accion en el diagrama
async def execute_diagram_action(
    diagrama_id: int,
    autor_codigo: str,
    action: PlannerAction,
    current_diagrama: dict[str, Any],
    token: str | None,
):
    if action.tool not in SUPPORTED_TOOLS_V1:
        raise ValueError(f"Tool no soportada en Diagram Agent V1: {action.tool}")

    if action.tool == "create_class":
        body = build_create_class_body(action.arguments, autor_codigo)
        diagrama = await create_class(diagrama_id, body, token)

        return diagrama, DiagramActionResult(
            order=action.order,
            tool=action.tool,
            success=True,
            message=f"Clase creada: {body['name']}",
            data={"className": body["name"]},
        )

    if action.tool == "update_class":
        clase_id = resolve_class_id(action.arguments, current_diagrama)
        body = build_update_class_body(action.arguments, autor_codigo)
        diagrama = await update_class(diagrama_id, clase_id, body, token)

        return diagrama, DiagramActionResult(
            order=action.order,
            tool=action.tool,
            success=True,
            message=f"Clase actualizada: {clase_id}",
            data={"classId": clase_id},
        )

    if action.tool == "delete_class":
        clase_id = resolve_class_id(action.arguments, current_diagrama)
        diagrama = await delete_class(diagrama_id, clase_id, autor_codigo, token)

        return diagrama, DiagramActionResult(
            order=action.order,
            tool=action.tool,
            success=True,
            message=f"Clase eliminada: {clase_id}",
            data={"classId": clase_id},
        )

    if action.tool == "move_class":
        clase_id = resolve_class_id(action.arguments, current_diagrama)
        body = build_move_class_body(action.arguments, autor_codigo)
        diagrama = await move_class(diagrama_id, clase_id, body, token)

        return diagrama, DiagramActionResult(
            order=action.order,
            tool=action.tool,
            success=True,
            message=f"Clase movida: {clase_id}",
            data={"classId": clase_id, "x": body["x"], "y": body["y"]},
        )

    if action.tool == "create_relation":
        body = build_create_relation_body(action.arguments, current_diagrama, autor_codigo)
        diagrama = await create_relation(diagrama_id, body, token)

        return diagrama, DiagramActionResult(
            order=action.order,
            tool=action.tool,
            success=True,
            message=f"Relacion creada: {body['source']} -> {body['target']}",
            data={
                "source": body["source"],
                "target": body["target"],
                "relationType": body["data"]["relationType"],
            },
        )

    if action.tool == "update_relation":
        relation_id = resolve_relation_id(action.arguments, current_diagrama)
        body = build_update_relation_body(
            action.arguments,
            current_diagrama,
            relation_id,
            autor_codigo,
        )
        diagrama = await update_relation(diagrama_id, relation_id, body, token)

        return diagrama, DiagramActionResult(
            order=action.order,
            tool=action.tool,
            success=True,
            message=f"Relacion actualizada: {relation_id}",
            data={
                "relationId": relation_id,
                "source": body["source"],
                "target": body["target"],
                "relationType": body["data"]["relationType"],
            },
        )

    if action.tool == "delete_relation":
        relation_id = resolve_relation_id(action.arguments, current_diagrama)
        diagrama = await delete_relation(diagrama_id, relation_id, autor_codigo, token)

        return diagrama, DiagramActionResult(
            order=action.order,
            tool=action.tool,
            success=True,
            message=f"Relacion eliminada: {relation_id}",
            data={"relationId": relation_id},
        )

    if action.tool == "ask_user":
        question = (
            action.arguments.get("question")
            or action.arguments.get("message")
            or action.description
        )

        return current_diagrama, DiagramActionResult(
            order=action.order,
            tool=action.tool,
            success=True,
            message=f"Pregunta para el usuario: {question}",
            data={"question": question},
        )

    raise ValueError(f"Tool no implementada: {action.tool}")


async def load_diagram_context(diagrama_id: int, token: str | None):
    return await get_diagrama(diagrama_id, token)
