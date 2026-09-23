import base64
import json
import re
from typing import Any

from litellm import acompletion

from app.config.agents_models import (
    get_agent_model_name,
    get_litellm_api_key,
    normalize_litellm_model,
)
from app.config.settings import settings
from app.providers.ai_provider import configure_ai_provider
from app.schemas.chat import PlannerAction
from app.schemas.image_diagram import (
    ImageAttribute,
    ImageClass,
    ImageDiagramResponse,
    ImageMethod,
    ImageParameter,
    ImageRelation,
)


IMAGE_AGENT_INSTRUCTIONS = """
Eres el Image Agent de DrawSchema. Analiza una imagen de un diagrama UML de
clases, un diagrama entidad-relacion o un esquema de tablas dibujado a mano.

Debes transcribir solamente lo que sea visible. No inventes tablas, clases,
atributos, metodos, relaciones ni multiplicidades.

La imagen es la unica fuente de verdad para los elementos extraidos. El
contexto del diagrama actual sirve solamente para decidir posteriormente si
una clase se crea o se actualiza. Nunca agregues al resultado una clase o una
relacion solo porque aparezca en ese contexto.

Reglas obligatorias:
- Devuelve exclusivamente un objeto JSON valido, sin Markdown.
- Extrae clases o tablas, atributos/columnas, metodos y parametros visibles.
- Usa kind: class, abstractClass o interface.
- relationType solo puede ser: association, generalization, composition,
  aggregation, associationClass, realization o templateBinding.
- sourceName y targetName deben coincidir exactamente con nombres extraidos.
- En generalization: sourceName es la hija y targetName es la padre.
- En composition/aggregation: sourceName es el todo y targetName es la parte.
- Interpreta cuidadosamente simbolos UML y notacion pata de gallo.
- Generalization representa herencia, no una asociacion entre instancias: usa
  sourceCardinality=null y targetCardinality=null aunque la imagen tenga texto
  cercano. No le asignes multiplicidades.
- Association, associationClass, aggregation y composition si pueden tener
  multiplicidad en cada extremo: 1, 0..1, 0..* o 1..*.
- En composition, la multiplicidad del extremo del Todo (sourceCardinality)
  solo puede ser 1 o 0..1 porque una Parte pertenece como maximo a un Todo.
- Si una multiplicidad aplicable no es visible o no puede determinarse, usa
  null. Nunca adivines. Explica la duda en ambiguities.
- Si una linea no tiene tipo reconocible, usa association solamente cuando la
  conexion sea clara.
- No conviertas una asociacion en aggregation/composition por criterio propio:
  conserva exactamente el simbolo visible (linea, rombo vacio, rombo lleno,
  triangulo o linea discontinua).
- Regla critica para associationClass: si dos clases estan unidas por una
  asociacion principal y una tercera clase o tabla se conecta mediante una
  linea discontinua al centro de esa asociacion, la tercera es una clase de
  asociacion. Devuelve UNA sola relacion con relationType associationClass,
  sourceName y targetName iguales a los extremos de la asociacion principal,
  y associationClassName igual al nombre de la tercera clase.
- La linea discontinua de una clase de asociacion NO es una relacion adicional
  entre la tabla intermedia y una de las tablas extremas. No generes edges
  separados para esa linea auxiliar.
- Una tabla intermedia conectada directamente a ambas tablas mediante dos
  asociaciones normales no debe convertirse en associationClass; respeta lo
  que realmente muestre la imagen.
- Conserva PK, FK, nulabilidad, tipos y metodos cuando sean legibles.
- Usa confidence entre 0 y 1 para cada clase y relacion.

Formato exacto:
{
  "summary": "resumen corto",
  "classes": [
    {
      "name": "Cliente",
      "kind": "class",
      "attributes": [
        {
          "name": "id",
          "type": "BIGINT",
          "primaryKey": true,
          "foreignKey": false,
          "nullable": false
        }
      ],
      "methods": [
        {
          "name": "registrar",
          "returnType": "void",
          "parameters": [{"name": "nombre", "type": "String"}]
        }
      ],
      "templateParameters": [],
      "confidence": 0.98
    }
  ],
  "relations": [
    {
      "sourceName": "Cliente",
      "targetName": "Pedido",
      "relationType": "association",
      "sourceCardinality": "1",
      "targetCardinality": "0..*",
      "associationClassName": null,
      "sourceRole": null,
      "targetRole": null,
      "confidence": 0.95
    }
  ],
  "warnings": [],
  "ambiguities": []
}
"""


RELATION_TYPE_ALIASES = {
    "association": "association",
    "asociacion": "association",
    "generalization": "generalization",
    "generalizacion": "generalization",
    "inheritance": "generalization",
    "herencia": "generalization",
    "composition": "composition",
    "composicion": "composition",
    "aggregation": "aggregation",
    "agregacion": "aggregation",
    "associationclass": "associationClass",
    "association_class": "associationClass",
    "clasedeasociacion": "associationClass",
    "realization": "realization",
    "realizacion": "realization",
    "templatebinding": "templateBinding",
    "template_binding": "templateBinding",
}

CARDINALITY_ALIASES = {
    "1": "1",
    "1..1": "1",
    "one": "1",
    "uno": "1",
    "0..1": "0..1",
    "0...1": "0..1",
    "zeroorone": "0..1",
    "ceroouno": "0..1",
    "0..*": "0..*",
    "0...*": "0..*",
    "0..n": "0..*",
    "zeroormany": "0..*",
    "ceroomuchos": "0..*",
    "1..*": "1..*",
    "1...*": "1..*",
    "1..n": "1..*",
    "oneormany": "1..*",
    "unoamuchos": "1..*",
}

VALID_CLASS_KINDS = {"class", "abstractClass", "interface"}
EDIT_ROLES = {"PROPIETARIO", "ADMINISTRADOR", "ADMIN", "OWNER", "EDITOR", "DESIGNER", "DISEÑADOR"}
RELATION_TYPES_WITHOUT_CARDINALITY = {"generalization"}


def detect_image_mime(image_bytes: bytes, declared_mime: str | None) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"

    raise ValueError(
        f"Formato de imagen no permitido: {declared_mime or 'desconocido'}. "
        "Usa PNG, JPEG o WebP."
    )


def normalize_cardinality(value: Any) -> str | None:
    if value is None:
        return None
    clean = str(value).strip().lower()
    clean = clean.replace(" ", "").replace("–", "..").replace("—", "..")
    return CARDINALITY_ALIASES.get(clean)


def normalize_relation_type(value: Any) -> str | None:
    clean = re.sub(r"[\s-]+", "", str(value or "").strip().lower())
    return RELATION_TYPE_ALIASES.get(clean)


def _clean_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 1.0


def _extract_json(content: Any) -> dict[str, Any]:
    if isinstance(content, list):
        content = "".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )

    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("El proveedor IA no devolvio un JSON reconocible")
        parsed = json.loads(text[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("La respuesta visual debe ser un objeto JSON")
    return parsed


def _normalize_attribute(raw: dict[str, Any]) -> ImageAttribute | None:
    name = _clean_name(raw.get("name") or raw.get("nombre"))
    if not name:
        return None
    return ImageAttribute(
        name=name,
        type=_clean_name(raw.get("type") or raw.get("tipo") or "VARCHAR"),
        primaryKey=bool(raw.get("primaryKey", raw.get("pk", False))),
        foreignKey=bool(raw.get("foreignKey", raw.get("fk", False))),
        nullable=bool(raw.get("nullable", True)),
    )


def _normalize_method(raw: dict[str, Any]) -> ImageMethod | None:
    name = _clean_name(raw.get("name") or raw.get("nombre"))
    if not name:
        return None

    parameters: list[ImageParameter] = []
    for raw_parameter in _as_list(raw.get("parameters") or raw.get("parametros")):
        if not isinstance(raw_parameter, dict):
            continue
        parameter_name = _clean_name(raw_parameter.get("name") or raw_parameter.get("nombre"))
        if parameter_name:
            parameters.append(
                ImageParameter(
                    name=parameter_name,
                    type=_clean_name(raw_parameter.get("type") or raw_parameter.get("tipo") or "Object"),
                )
            )

    return ImageMethod(
        name=name,
        returnType=_clean_name(raw.get("returnType") or raw.get("retorno") or "void"),
        parameters=parameters,
    )


def _normalize_classes(payload: dict[str, Any], warnings: list[str]) -> list[ImageClass]:
    classes: list[ImageClass] = []
    seen_names: set[str] = set()
    raw_classes = payload.get("classes") or payload.get("tables") or payload.get("tablas")

    for raw in _as_list(raw_classes):
        if not isinstance(raw, dict):
            continue
        name = _clean_name(raw.get("name") or raw.get("nombre"))
        if not name:
            warnings.append("Se omitio una clase sin nombre legible.")
            continue
        name_key = name.casefold()
        if name_key in seen_names:
            warnings.append(f"Se omitio la clase duplicada '{name}'.")
            continue

        attributes = [
            attribute
            for item in _as_list(raw.get("attributes") or raw.get("columns") or raw.get("atributos"))
            if isinstance(item, dict)
            if (attribute := _normalize_attribute(item)) is not None
        ]
        methods = [
            method
            for item in _as_list(raw.get("methods") or raw.get("operations") or raw.get("metodos"))
            if isinstance(item, dict)
            if (method := _normalize_method(item)) is not None
        ]
        kind = str(raw.get("kind") or "class")
        if kind not in VALID_CLASS_KINDS:
            kind = "class"

        classes.append(
            ImageClass(
                name=name,
                kind=kind,
                attributes=attributes,
                methods=methods,
                templateParameters=[
                    _clean_name(item)
                    for item in _as_list(raw.get("templateParameters"))
                    if _clean_name(item)
                ],
                confidence=_confidence(raw.get("confidence")),
            )
        )
        seen_names.add(name_key)

    return classes


def _known_class_names(classes: list[ImageClass]) -> dict[str, str]:
    # Una relacion visual solo es valida si ambos extremos fueron leidos en la imagen.
    return {item.name.casefold(): item.name for item in classes}


def _normalize_relations(
    payload: dict[str, Any],
    classes: list[ImageClass],
    context: dict[str, Any],
    warnings: list[str],
    questions: list[str],
) -> list[ImageRelation]:
    relations: list[ImageRelation] = []
    seen: set[tuple[str, str, str]] = set()
    known_names = _known_class_names(classes)
    raw_relations = payload.get("relations") or payload.get("relationships") or payload.get("relaciones")

    for index, raw in enumerate(_as_list(raw_relations), start=1):
        if not isinstance(raw, dict):
            continue
        raw_source = _clean_name(raw.get("sourceName") or raw.get("source") or raw.get("origen"))
        raw_target = _clean_name(raw.get("targetName") or raw.get("target") or raw.get("destino"))
        source = known_names.get(raw_source.casefold())
        target = known_names.get(raw_target.casefold())
        relation_type = normalize_relation_type(raw.get("relationType") or raw.get("type") or raw.get("tipo"))

        if not source or not target:
            warnings.append(
                f"Relacion {index} omitida: su origen o destino no coincide con una clase reconocida."
            )
            continue
        if relation_type is None:
            questions.append(f"Que tipo de relacion existe entre {source} y {target}?")
            continue
        if source == target and relation_type not in {"association", "associationClass"}:
            warnings.append(
                f"Se omitio {relation_type} recursiva en {source}; ese tipo no permite autorrelacion."
            )
            continue

        duplicate_key = tuple(sorted((source.casefold(), target.casefold()))) + (relation_type,)
        if duplicate_key in seen:
            warnings.append(
                f"Se omitio una relacion {relation_type} duplicada entre {source} y {target}."
            )
            continue

        source_cardinality = None
        target_cardinality = None
        if relation_type not in RELATION_TYPES_WITHOUT_CARDINALITY:
            source_cardinality = normalize_cardinality(
                raw.get("sourceCardinality") or raw.get("sourceMultiplicity")
            )
            target_cardinality = normalize_cardinality(
                raw.get("targetCardinality") or raw.get("targetMultiplicity")
            )
            if source_cardinality is None:
                questions.append(f"Cual es la multiplicidad del extremo {source} en {source} - {target}?")
            if target_cardinality is None:
                questions.append(f"Cual es la multiplicidad del extremo {target} en {source} - {target}?")
            if relation_type == "composition" and source_cardinality not in {None, "1", "0..1"}:
                questions.append(
                    f"La composicion {source} - {target} muestra mas de un Todo por Parte; "
                    "confirma si el simbolo o la multiplicidad fueron interpretados correctamente."
                )
                source_cardinality = None

        association_class_name = _clean_name(raw.get("associationClassName")) or None
        if relation_type == "associationClass":
            if not association_class_name:
                questions.append(
                    f"Que clase de asociacion corresponde al vinculo entre {source} y {target}?"
                )
            else:
                resolved_association_class = known_names.get(association_class_name.casefold())
                if resolved_association_class is None:
                    questions.append(
                        f"La clase de asociacion '{association_class_name}' no fue reconocida en la imagen."
                    )
                elif resolved_association_class in {source, target}:
                    questions.append(
                        "La clase de asociacion debe ser distinta de las clases origen y destino."
                    )
                else:
                    association_class_name = resolved_association_class
        else:
            association_class_name = None

        relations.append(
            ImageRelation(
                sourceName=source,
                targetName=target,
                relationType=relation_type,
                sourceCardinality=source_cardinality,
                targetCardinality=target_cardinality,
                associationClassName=association_class_name,
                sourceRole=_clean_name(raw.get("sourceRole")) or None,
                targetRole=_clean_name(raw.get("targetRole")) or None,
                confidence=_confidence(raw.get("confidence")),
            )
        )
        seen.add(duplicate_key)

    return relations


def _existing_diagram_maps(context: dict[str, Any]):
    diagram = context.get("diagrama") or {}
    content = diagram.get("contenido") or {}
    nodes = [item for item in _as_list(content.get("nodes")) if isinstance(item, dict)]
    edges = [item for item in _as_list(content.get("edges")) if isinstance(item, dict)]
    by_name: dict[str, dict[str, Any]] = {}
    by_id: dict[str, str] = {}

    for node in nodes:
        name = _clean_name((node.get("data") or {}).get("name"))
        if name:
            by_name[name.casefold()] = node
            by_id[str(node.get("id"))] = name
    return by_name, by_id, edges


def _relation_action_needed(
    relation: ImageRelation,
    by_id: dict[str, str],
    edges: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]] | None:
    for edge in edges:
        data = edge.get("data") or {}
        source_name = by_id.get(str(edge.get("source")))
        target_name = by_id.get(str(edge.get("target")))
        if not source_name or not target_name:
            continue
        if source_name.casefold() != relation.sourceName.casefold():
            continue
        if target_name.casefold() != relation.targetName.casefold():
            continue
        if data.get("relationType") != relation.relationType:
            continue

        if relation.relationType in RELATION_TYPES_WITHOUT_CARDINALITY:
            if any(key in data for key in ("sourceCardinality", "targetCardinality", "cardinality")):
                return "update_relation", {"relationId": str(edge.get("id"))}
            return None

        if (
            data.get("sourceCardinality") == relation.sourceCardinality
            and data.get("targetCardinality") == relation.targetCardinality
        ):
            return None
        return "update_relation", {"relationId": str(edge.get("id"))}

    return "create_relation", {}


def build_image_plan(
    classes: list[ImageClass],
    relations: list[ImageRelation],
    context: dict[str, Any],
) -> list[PlannerAction]:
    actions: list[PlannerAction] = []
    by_name, by_id, edges = _existing_diagram_maps(context)
    order = 1

    for index, image_class in enumerate(classes):
        exists = image_class.name.casefold() in by_name
        arguments: dict[str, Any] = {
            "name": image_class.name,
            "kind": image_class.kind,
            "attributes": [item.model_dump() for item in image_class.attributes],
            "methods": [item.model_dump() for item in image_class.methods],
            "templateParameters": image_class.templateParameters,
        }
        if exists:
            arguments["className"] = image_class.name
            tool = "update_class"
            description = f"Actualizar la clase {image_class.name} desde la imagen"
        else:
            arguments["x"] = 100 + (index % 3) * 300
            arguments["y"] = 100 + (index // 3) * 220
            tool = "create_class"
            description = f"Crear la clase {image_class.name} extraida de la imagen"

        actions.append(
            PlannerAction(
                order=order,
                tool=tool,
                description=description,
                arguments=arguments,
                requires_confirmation=False,
            )
        )
        order += 1

    for relation in relations:
        uses_cardinality = relation.relationType not in RELATION_TYPES_WITHOUT_CARDINALITY
        if uses_cardinality and (
            relation.sourceCardinality is None or relation.targetCardinality is None
        ):
            continue
        action_info = _relation_action_needed(relation, by_id, edges)
        if action_info is None:
            continue
        tool, extra_arguments = action_info
        arguments = {
            **extra_arguments,
            "sourceName": relation.sourceName,
            "targetName": relation.targetName,
            "relationType": relation.relationType,
        }
        if uses_cardinality:
            arguments["sourceCardinality"] = relation.sourceCardinality
            arguments["targetCardinality"] = relation.targetCardinality
        for key, value in (
            ("associationClassName", relation.associationClassName),
            ("sourceRole", relation.sourceRole),
            ("targetRole", relation.targetRole),
        ):
            if value:
                arguments[key] = value

        cardinality_description = (
            f" ({relation.sourceCardinality}, {relation.targetCardinality})"
            if uses_cardinality
            else ""
        )
        actions.append(
            PlannerAction(
                order=order,
                tool=tool,
                description=(
                    f"{'Actualizar' if tool == 'update_relation' else 'Crear'} relacion "
                    f"{relation.relationType} {relation.sourceName} -> {relation.targetName}"
                    f"{cardinality_description}"
                ),
                arguments=arguments,
                requires_confirmation=False,
            )
        )
        order += 1

    return actions


async def run_image_agent(
    image_bytes: bytes,
    mime_type: str,
    message: str,
    context: dict[str, Any],
    filename: str | None = None,
) -> ImageDiagramResponse:
    configure_ai_provider()
    primary_model = normalize_litellm_model(get_agent_model_name("image"))
    fallback_models = [
        normalize_litellm_model(item.strip())
        for item in settings.IMAGE_FALLBACK_MODELS.split(",")
        if item.strip()
    ]
    model_candidates = list(dict.fromkeys([primary_model, *fallback_models]))
    image_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    user_prompt = (
        f"Peticion adicional del usuario: {message or 'Extrae fielmente el diagrama.'}\n\n"
        f"Contexto actual del proyecto y diagrama: {json.dumps(context, ensure_ascii=False)}"
    )
    messages = [
        {"role": "system", "content": IMAGE_AGENT_INSTRUCTIONS},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": image_url, "format": mime_type},
                },
            ],
        },
    ]
    response = None
    model_name = primary_model
    last_error: Exception | None = None
    for candidate in model_candidates:
        completion_kwargs: dict[str, Any] = {
            "model": candidate,
            "api_key": get_litellm_api_key(candidate),
            "messages": messages,
            "response_format": {"type": "json_object"},
            "num_retries": 1,
            "timeout": 90,
        }
        if settings.LITELLM_API_BASE:
            completion_kwargs["api_base"] = settings.LITELLM_API_BASE
        try:
            response = await acompletion(**completion_kwargs)
            model_name = candidate
            break
        except Exception as exc:
            last_error = exc

    if response is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("No hay un modelo visual configurado")

    payload = _extract_json(response.choices[0].message.content)
    warnings = [str(item) for item in _as_list(payload.get("warnings")) if str(item).strip()]
    questions = [
        str(item) for item in _as_list(payload.get("ambiguities")) if str(item).strip()
    ]
    classes = _normalize_classes(payload, warnings)
    relations = _normalize_relations(payload, classes, context, warnings, questions)
    actions = build_image_plan(classes, relations, context)
    role = str(context.get("user_role") or "").upper()
    can_edit = role in EDIT_ROLES

    if not can_edit:
        warnings.append(
            f"El rol {role or 'DESCONOCIDO'} puede analizar la imagen, pero no modificar el diagrama."
        )
    if not classes:
        questions.append("No se reconocieron clases o tablas. Sube una imagen mas clara.")

    return ImageDiagramResponse(
        summary=_clean_name(payload.get("summary"))
        or f"Se reconocieron {len(classes)} clases y {len(relations)} relaciones.",
        classes=classes,
        relations=relations,
        actions=actions,
        warnings=list(dict.fromkeys(warnings)),
        questions=list(dict.fromkeys(questions)),
        can_execute=bool(actions) and not questions and can_edit,
        image_metadata={
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": len(image_bytes),
            "model": model_name,
        },
    )
