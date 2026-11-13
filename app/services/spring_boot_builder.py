from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.schemas.codegen import GeneratedFile


@dataclass
class Attribute:
    """Representa un atributo del diagrama ya convertido a datos utiles para Java."""

    name: str
    java_name: str
    java_type: str
    primary_key: bool
    foreign_key: bool
    nullable: bool


@dataclass
class Relationship:
    """Relacion JPA unidireccional calculada desde un edge UML."""

    relation_type: str
    field_name: str
    target_class_name: str
    target_table_name: str
    source_cardinality: str
    target_cardinality: str
    annotation: str
    collection: bool
    required: bool
    cascade_all: bool = False
    orphan_removal: bool = False
    maps_id: str | None = None
    join_column: str | None = None
    target_id_type: str | None = None
    mapped_by: str | None = None
    request_field: str | None = None
    target_id_field: str = "id"
    join_columns: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Entity:
    """Representa una clase UML convertida en entidad candidata para Spring Boot."""

    node_id: str
    name: str
    class_name: str
    variable_name: str
    route_name: str
    table_name: str
    attributes: list[Attribute]
    id_attribute: Attribute
    generated_id: bool
    is_composite_id: bool = False
    composite_id_class_name: str | None = None
    pk_attributes: list[Attribute] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    parent_class_name: str | None = None
    inheritance_parent: bool = False
    abstract: bool = False
    inherited_fields: set[str] = field(default_factory=set)
    interfaces: list[str] = field(default_factory=list)
    contract_methods: dict[str, str] = field(default_factory=dict)



def _clean_words(value: str) -> list[str]:
    """Divide un texto en palabras limpias para construir nombres de clases/campos."""

    words = re.split(r"[^a-zA-Z0-9]+", value.strip())
    return [word for word in words if word]


def to_pascal_case(value: str, fallback: str = "Entity") -> str:
    """Convierte un texto a PascalCase para nombres de clases Java."""

    words = _clean_words(value)

    if not words:
        return fallback

    result = "".join(word[:1].upper() + word[1:] for word in words)

    if result[:1].isdigit():
        result = f"{fallback}{result}"

    return result


def to_camel_case(value: str, fallback: str = "field") -> str:
    """Convierte un texto a camelCase para variables, campos y nombres de objetos."""

    pascal = to_pascal_case(value, fallback.capitalize())
    return pascal[:1].lower() + pascal[1:]


def to_snake_case(value: str) -> str:
    """Convierte un texto a snake_case para nombres de tabla en PostgreSQL."""

    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value)
    return value.strip("_").lower() or "entity"


def pluralize(value: str) -> str:
    """Genera un plural simple para formar rutas REST como /api/clientes."""

    value = to_snake_case(value).replace("_", "-")

    if value.endswith("s"):
        return value

    return f"{value}s"


def map_java_type(raw_type: Any) -> str:
    """Mapea tipos del diagrama o PostgreSQL a tipos Java."""

    normalized = str(raw_type or "String").strip().upper()

    mappings = {
        "BIGINT": "Long",
        "LONG": "Long",
        "INT": "Integer",
        "INTEGER": "Integer",
        "SMALLINT": "Integer",
        "SERIAL": "Integer",
        "VARCHAR": "String",
        "CHAR": "String",
        "TEXT": "String",
        "STRING": "String",
        "DECIMAL": "BigDecimal",
        "NUMERIC": "BigDecimal",
        "DOUBLE": "Double",
        "FLOAT": "Float",
        "DATE": "LocalDate",
        "LOCALDATE": "LocalDate",
        "TIMESTAMP": "LocalDateTime",
        "DATETIME": "LocalDateTime",
        "BOOLEAN": "Boolean",
        "BOOL": "Boolean",
    }

    return mappings.get(normalized, "String")


def map_schema_type(java_type: str) -> str:
    """Convierte tipos Java a los tipos simples que entiende la app movil."""

    mappings = {
        "Long": "int",
        "Integer": "int",
        "Double": "double",
        "Float": "double",
        "BigDecimal": "double",
        "Boolean": "boolean",
        "LocalDate": "date",
        "LocalDateTime": "datetime",
    }
    return mappings.get(java_type, "string")


def cardinality_is_many(value: str) -> bool:
    """Indica si una multiplicidad UML representa una coleccion."""

    return value in {"0..*", "1..*"}


def relationship_annotation(source_cardinality: str, target_cardinality: str) -> str:
    """Mapea las multiplicidades de ambos extremos a una anotacion JPA."""

    source_many = cardinality_is_many(source_cardinality)
    target_many = cardinality_is_many(target_cardinality)
    if source_many and target_many:
        return "ManyToMany"
    if source_many:
        return "ManyToOne"
    if target_many:
        return "OneToMany"
    return "OneToOne"


def unique_relationship_field(entity: Entity, base_name: str) -> str:
    """Evita colisiones entre atributos del diagrama y campos de relacion."""

    used = {attribute.java_name for attribute in entity.attributes}
    used.update(relationship.field_name for relationship in entity.relationships)
    candidate = base_name
    suffix = 2
    while candidate in used:
        candidate = f"{base_name}{suffix}"
        suffix += 1
    return candidate


def find_association_key(
    association_entity: Entity,
    related_entity: Entity,
    excluded: set[str],
) -> Attribute | None:
    """Localiza la PK/FK de la clase intermedia que referencia a una entidad."""

    candidates = [
        attribute
        for attribute in association_entity.pk_attributes
        if attribute.java_name not in excluded
    ]
    related_tokens = {
        to_snake_case(related_entity.name),
        to_snake_case(related_entity.class_name),
        related_entity.table_name,
    }

    for attribute in candidates:
        attribute_name = to_snake_case(attribute.name)
        if attribute.foreign_key and any(token in attribute_name for token in related_tokens):
            return attribute

    for attribute in candidates:
        attribute_name = to_snake_case(attribute.name)
        if any(token in attribute_name for token in related_tokens):
            return attribute

    return next((attribute for attribute in candidates if attribute.foreign_key), None)


def relation_ends(edge):
    data = edge.get("data") or {}
    return tuple(str(data.get(f"{end}ClassId") or edge.get(end) or "") for end in ("source", "target"))


def scalar_java_type(raw_type: str) -> str:
    value = raw_type.strip()
    java_type = map_java_type(value)
    if java_type == "String" and not re.fullmatch(r"(?:string|text|varchar|char)(?:\(\d+\))?", value, re.I):
        raise ValueError(f"Tipo sin mapeo escalar automático: {value}.")
    return java_type


def interface_methods(data):
    signatures = {}
    for method in data.get("methods") or []:
        name = to_camel_case(method.get("name") or "operacion")
        raw_return = str(method.get("returnType") or "void")
        return_type = "void" if raw_return.casefold() == "void" else scalar_java_type(raw_return)
        parameters = []
        types = []
        for index, parameter in enumerate(method.get("parameters") or []):
            if not isinstance(parameter, dict):
                raise ValueError(f"Define nombre y tipo de los parámetros de {name}.")
            java_type = scalar_java_type(str(parameter.get("type") or "String"))
            parameters.append(f"{java_type} {to_camel_case(parameter.get('name') or f'arg{index}')}")
            types.append(java_type)
        key = f"{name}({','.join(types)})"
        if key in signatures:
            raise ValueError(f"Operación duplicada en la interfaz: {key}.")
        signatures[key] = f"{return_type} {name}({', '.join(parameters)})"
    return signatures


def generate_interface(base_package, data):
    name = to_pascal_case(data.get("name") or "Contrato")
    operations = [f"    {signature};" for signature in interface_methods(data).values()]
    return GeneratedFile(
        path=f"src/main/java/{package_path(base_package)}/models/{name}.java",
        language="java",
        content="\n".join([
            f"package {base_package}.models;", "", "import java.math.BigDecimal;",
            "import java.time.LocalDate;", "import java.time.LocalDateTime;", "",
            f"public interface {name} {{", *operations, "}", "",
        ]),
    )


def resolve_generalizations(edges, entities_by_id):
    parents = {}
    for edge in edges:
        if (edge.get("data") or {}).get("relationType") != "generalization":
            continue
        child_id, parent_id = relation_ends(edge)
        if child_id not in entities_by_id or parent_id not in entities_by_id:
            raise ValueError("La generalización persistente requiere dos clases.")
        if child_id in parents and parents[child_id] != parent_id:
            raise ValueError("Java admite una sola clase padre por entidad.")
        parents[child_id] = parent_id

    order = []
    visiting = set()
    resolved = set()

    def visit(child_id):
        if child_id in visiting:
            raise ValueError("Hay un ciclo de generalización en el diagrama.")
        if child_id in resolved or child_id not in parents:
            return
        visiting.add(child_id)
        parent_id = parents[child_id]
        visit(parent_id)
        child, parent = entities_by_id[child_id], entities_by_id[parent_id]
        if child.is_composite_id or parent.is_composite_id:
            raise ValueError("La generalización con clave compuesta requiere mapeo manual.")
        child.parent_class_name = parent.class_name
        parent.inheritance_parent = True
        child.id_attribute = parent.id_attribute
        child.generated_id = parent.generated_id
        child.attributes = [attribute for attribute in child.attributes if not attribute.primary_key]
        order.append((child, parent))
        visiting.remove(child_id)
        resolved.add(child_id)

    for child_id in parents:
        visit(child_id)
    return order


def expand_templates(nodes, edges):
    """Materializa sustituciones de tipos escalares en una clase concreta."""
    templates = {str(n["id"]): n["data"] for n in nodes if (n.get("data") or {}).get("templateParameters")}
    concrete = [deepcopy(n) for n in nodes if str(n.get("id")) not in templates]
    by_id = {str(n.get("id")): n for n in concrete}
    ordinary_edges = []
    bound = set()
    warnings = []
    for edge in edges:
        data = edge.get("data") or {}
        source, target = relation_ends(edge)
        if data.get("relationType") != "templateBinding":
            if source in templates or target in templates:
                raise ValueError("Genera relaciones de persistencia sobre las clases concretas, no sobre la plantilla UML.")
            ordinary_edges.append(edge)
            continue
        template = templates.get(target)
        destination = (by_id.get(source) or {}).get("data")
        if (not template or destination is None or source in bound
                or template.get("kind") == "interface" or destination.get("kind") == "interface"):
            raise ValueError("Template Binding requiere una clase concreta y una plantilla de clase; se admite una plantilla por clase.")
        parameters = set(template["templateParameters"])
        substitutions = data.get("templateBindings") or {}
        if not isinstance(substitutions, dict) or set(substitutions) != parameters:
            raise ValueError("Completa todos los parámetros de Template Binding con tipos escalares Java o SQL admitidos.")
        for value in substitutions.values():
            scalar_java_type(str(value or ""))
        if template.get("methods"):
            raise ValueError("La expansión de plantillas con operaciones requiere implementación manual.")
        own = list(destination.get("attributes") or [])
        own_names = {to_camel_case(a["name"]) for a in own}
        inherited = []
        for attr in template.get("attributes") or []:
            if to_camel_case(attr["name"]) in own_names:
                raise ValueError(f"El atributo {attr['name']} está declarado tanto en la plantilla como en la clase concreta.")
            inherited.append({**attr, "type": substitutions.get(attr.get("type"), attr.get("type"))})
        destination["attributes"] = inherited + own
        bound.add(source)
        warnings.append(f"{destination.get('name')}: plantilla {template.get('name')} materializada con sustituciones escalares.")
    return concrete, ordinary_edges, warnings


def parse_entities(context: dict[str, Any]) -> tuple[list[Entity], list[str]]:
    """Lee nodes y edges del JSONB y los transforma en entidades JPA."""

    warnings: list[str] = []
    diagrama = context.get("diagrama") or {}
    contenido = diagrama.get("contenido") or {}
    nodes, edges, template_warnings = expand_templates(contenido.get("nodes") or [], contenido.get("edges") or [])
    warnings.extend(template_warnings)
    nodes_by_id = {str(node.get("id")): node for node in nodes}
    entities: list[Entity] = []
    entities_by_node_id: dict[str, Entity] = {}
    used_names: set[str] = set()

    for index, node in enumerate(nodes):
        data = node.get("data") or {}
        if data.get("kind") == "interface":
            continue
        raw_name = str(data.get("name") or f"Entidad{index + 1}")
        class_name = to_pascal_case(raw_name, f"Entity{index + 1}")

        if class_name in used_names:
            warnings.append(f"La entidad {class_name} estaba duplicada; se renombro automaticamente.")
            class_name = f"{class_name}{index + 1}"

        used_names.add(class_name)

        attributes: list[Attribute] = []

        for attr_index, attr in enumerate(data.get("attributes") or []):
            # La FK derivada ya se representa mediante la relación JPA;
            # no generar también un campo escalar independiente para esa columna.
            if (attr.get("_relationshipKey") or {}).get("role") == "many" and attr.get("foreignKey"):
                continue
            attr_name = str(attr.get("name") or f"campo{attr_index + 1}")
            java_name = to_camel_case(attr_name, f"field{attr_index + 1}")
            java_type = map_java_type(attr.get("type"))
            primary_key = bool(
                attr.get("primaryKey")
                or attr.get("isPrimaryKey")
                or attr.get("primary_key")
                or attr.get("isPk")
            )
            foreign_key = bool(
                attr.get("foreignKey")
                or attr.get("isForeignKey")
                or attr.get("foreign_key")
                or attr.get("isFk")
            )
            nullable = bool(attr.get("nullable", True))

            attributes.append(
                Attribute(
                    name=attr_name,
                    java_name=java_name,
                    java_type=java_type,
                    primary_key=primary_key,
                    foreign_key=foreign_key,
                    nullable=nullable,
                )
            )

        id_attributes = [attribute for attribute in attributes if attribute.primary_key]
        generated_id = False
        is_composite_id = False
        composite_id_class_name = None
        pk_attributes = []

        if len(id_attributes) > 1:
            is_composite_id = True
            composite_id_class_name = f"{class_name}Id"
            pk_attributes = id_attributes
            id_attribute = Attribute(
                name="id",
                java_name="id",
                java_type=composite_id_class_name,
                primary_key=True,
                foreign_key=False,
                nullable=False,
            )
            warnings.append(
                f"La entidad {class_name} posee clave compuesta con {len(id_attributes)} campos ({[a.name for a in id_attributes]}); "
                f"se generara la clase @Embeddable {composite_id_class_name}."
            )
        elif id_attributes:
            id_attribute = id_attributes[0]
            generated_id = (
                id_attribute.java_name.lower() == "id"
                and id_attribute.java_type in {"Long", "Integer"}
            )
        else:
            generated_id = True
            id_attribute = Attribute(
                name="id",
                java_name="id",
                java_type="Long",
                primary_key=True,
                foreign_key=False,
                nullable=False,
            )
            attributes.insert(0, id_attribute)
            warnings.append(
                f"La entidad {class_name} no tenia primaryKey; se genero id Long automaticamente."
            )

        entity = Entity(
                node_id=str(node.get("id") or f"class-{index + 1}"),
                name=raw_name,
                class_name=class_name,
                variable_name=to_camel_case(class_name),
                route_name=pluralize(class_name),
                table_name=to_snake_case(class_name),
                attributes=attributes,
                id_attribute=id_attribute,
                generated_id=generated_id,
                is_composite_id=is_composite_id,
                composite_id_class_name=composite_id_class_name,
                pk_attributes=pk_attributes,
                abstract=data.get("kind") == "abstractClass",
            )
        entities.append(entity)
        entities_by_node_id[entity.node_id] = entity


    if not entities:
        raise ValueError("No se puede generar backend porque el diagrama no tiene clases.")

    generalizations = resolve_generalizations(edges, entities_by_node_id)
    for edge in edges:
        data = edge.get("data") or {}
        relation_type = str(data.get("relationType") or "association")
        source_id = str(data.get("sourceClassId") or edge.get("source") or "")
        target_id = str(data.get("targetClassId") or edge.get("target") or "")
        source = entities_by_node_id.get(source_id)
        target = entities_by_node_id.get(target_id)

        if relation_type == "realization":
            target_data = (nodes_by_id.get(target_id) or {}).get("data") or {}
            if source is None or target_data.get("kind") != "interface":
                raise ValueError("La realización debe ir de una clase a una interfaz.")
            interface_name = to_pascal_case(target_data.get("name") or "Contrato")
            if interface_name in used_names:
                raise ValueError(f"El nombre de interfaz {interface_name} coincide con una entidad Java.")
            if interface_name not in source.interfaces:
                source.interfaces.append(interface_name)
            for key, signature in interface_methods(target_data).items():
                if key in source.contract_methods and source.contract_methods[key] != signature:
                    raise ValueError(f"Las interfaces de {source.class_name} declaran operaciones incompatibles: {key}.")
                source.contract_methods[key] = signature
            if target_data.get("methods"):
                warnings.append(f"{source.class_name}: completa la lógica de las operaciones de {interface_name}.")
            continue

        if source is None or target is None:
            warnings.append(
                f"Se omitio una relacion {relation_type} porque su origen o destino no existe."
            )
            continue

        if relation_type == "generalization":
            continue

        if relation_type == "associationClass":
            association_class_id = str(data.get("associationClassId") or "")
            association_entity = entities_by_node_id.get(association_class_id)
            if association_entity is None:
                warnings.append(
                    f"Se omitio associationClass {source.class_name}-{target.class_name}: "
                    "no existe la clase intermedia."
                )
                continue
            if not association_entity.is_composite_id:
                warnings.append(
                    f"La clase de asociacion {association_entity.class_name} necesita al menos "
                    "dos atributos primaryKey=true y foreignKey=true."
                )
                continue

            claimed_keys: set[str] = set()
            association_pairs = ((source, data.get("sourceRole")), (target, data.get("targetRole")))
            for related_entity, role in association_pairs:
                mapped_key = find_association_key(
                    association_entity,
                    related_entity,
                    claimed_keys,
                )
                if mapped_key is None:
                    warnings.append(
                        f"No se encontro la PK/FK de {related_entity.class_name} en "
                        f"{association_entity.class_name}."
                    )
                    continue
                if related_entity.is_composite_id:
                    warnings.append(
                        f"La relacion de {association_entity.class_name} con "
                        f"{related_entity.class_name} usa otra clave compuesta y requiere "
                        "revision manual."
                    )
                    continue

                claimed_keys.add(mapped_key.java_name)
                field_name = unique_relationship_field(
                    association_entity,
                    to_camel_case(str(role or related_entity.variable_name)),
                )
                association_entity.relationships.append(
                    Relationship(
                        relation_type="associationClass",
                        field_name=field_name,
                        target_class_name=related_entity.class_name,
                        target_table_name=related_entity.table_name,
                        source_cardinality="1",
                        target_cardinality="1",
                        annotation="ManyToOne",
                        collection=False,
                        required=True,
                        maps_id=mapped_key.java_name,
                        join_column=to_snake_case(mapped_key.name),
                        target_id_type=related_entity.id_attribute.java_type,
                    )
                )

            if len(claimed_keys) != 2:
                warnings.append(
                    f"La clase de asociacion {association_entity.class_name} no pudo enlazar "
                    "correctamente las dos claves foraneas."
                )
            continue

        if relation_type not in {"association", "composition", "aggregation"}:
            warnings.append(f"{relation_type} entre {source.class_name} y {target.class_name}: sin mapeo de persistencia automático.")
            continue

        source_cardinality = str(data.get("sourceCardinality") or "1")
        target_cardinality = str(data.get("targetCardinality") or "0..*")
        source_cardinality = "0..*" if source_cardinality == "*" else source_cardinality
        target_cardinality = "0..*" if target_cardinality == "*" else target_cardinality
        if {source_cardinality, target_cardinality} - {"0..1", "1", "0..*", "1..*"}:
            raise ValueError(f"Multiplicidad sin mapeo en {source.class_name}–{target.class_name}: {source_cardinality} / {target_cardinality}.")
        if relation_type == "composition" and source_cardinality not in {"1", "0..1"}:
            raise ValueError(
                f"Composicion invalida {source.class_name} -> {target.class_name}: "
                "una Parte solo puede pertenecer a un Todo (sourceCardinality 1 o 0..1)."
            )
        annotation = relationship_annotation(source_cardinality, target_cardinality)
        if annotation != "ManyToMany":
            reverse = annotation == "OneToMany"
            owner, parent = (target, source) if reverse else (source, target)
            parent_cardinality = source_cardinality if reverse else target_cardinality
            children_cardinality = target_cardinality if reverse else source_cardinality
            role = data.get("sourceRole" if reverse else "targetRole")
            field_name = unique_relationship_field(owner, to_camel_case(str(role or parent.variable_name)))
            owner_annotation = "OneToOne" if annotation == "OneToOne" else "ManyToOne"
            keys = parent.pk_attributes if parent.is_composite_id else [parent.id_attribute]
            managed_columns = {}
            for attr in (nodes_by_id[owner.node_id].get("data") or {}).get("attributes") or []:
                managed = attr.get("_relationshipKey") or {}
                reference = managed.get("reference") or {}
                if (managed.get("role") == "many" and str(reference.get("nodeId")) == parent.node_id
                        and str(managed.get("edgeId")) == str(edge.get("id", ""))
                        and reference.get("attribute") and attr.get("name")):
                    managed_columns[to_snake_case(reference["attribute"])] = to_snake_case(attr["name"])

            used_columns = {col for rel in owner.relationships for col, _ in rel.join_columns}
            used_columns.update(rel.join_column for rel in owner.relationships if rel.join_column)
            join_columns = []
            for key in keys:
                referenced = to_snake_case(key.name)
                default = f"{to_snake_case(field_name)}_id" if len(keys) == 1 else f"{to_snake_case(field_name)}_{referenced}"
                conventional = f"id_{to_snake_case(parent.variable_name)}"
                declared = next((a for a in owner.attributes if a.foreign_key and not a.primary_key
                                 and to_snake_case(a.name) in {default, conventional}
                                 and to_snake_case(a.name) not in used_columns), None) if len(keys) == 1 else None
                column = managed_columns.get(referenced) or (to_snake_case(declared.name) if declared else default)
                if column in used_columns:
                    raise ValueError(f"La columna {owner.table_name}.{column} ya corresponde a otro vínculo.")
                scalar = next((a for a in owner.attributes if to_snake_case(a.name) == column), None)
                if scalar:
                    if scalar.primary_key or not scalar.foreign_key or scalar.java_type != key.java_type:
                        raise ValueError(f"La columna {owner.table_name}.{column} no es compatible con la clave de {parent.class_name}.")
                    owner.attributes.remove(scalar)
                join_columns.append((column, referenced))

            request_field = to_camel_case(join_columns[0][0]) if len(keys) == 1 else f"{field_name}Id"
            if (any(a.java_name == request_field for a in owner.attributes)
                    or any(r.request_field == request_field for r in owner.relationships)):
                raise ValueError(f"El campo de referencia {owner.class_name}.{request_field} está duplicado.")
            owner.relationships.append(Relationship(
                relation_type, field_name, parent.class_name, parent.table_name,
                children_cardinality, parent_cardinality, owner_annotation, False,
                parent_cardinality == "1", target_id_type=parent.id_attribute.java_type,
                request_field=request_field, join_columns=join_columns,
                target_id_field=parent.id_attribute.java_name,
                cascade_all=relation_type == "composition" and owner_annotation == "OneToOne",
                orphan_removal=relation_type == "composition" and owner_annotation == "OneToOne",
            ))
            if owner_annotation == "ManyToOne":
                inverse_role = str(data.get("targetRole" if reverse else "sourceRole") or owner.variable_name)
                parent.relationships.append(Relationship(
                    relation_type, unique_relationship_field(parent, to_camel_case(pluralize(inverse_role))),
                    owner.class_name, owner.table_name, parent_cardinality, children_cardinality,
                    "OneToMany", True, children_cardinality == "1..*",
                    cascade_all=relation_type == "composition", orphan_removal=relation_type == "composition",
                    mapped_by=field_name,
                ))
                if children_cardinality == "1..*":
                    warnings.append(f"{parent.class_name}–{owner.class_name}: el mínimo de un elemento en la colección requiere validación del flujo de negocio.")
            elif source_cardinality == "1":
                warnings.append(f"{source.class_name}–{target.class_name}: el mínimo obligatorio del extremo inverso requiere validación del flujo de negocio.")
            continue

        warnings.append(f"{source.class_name}–{target.class_name}: para editar el vínculo por REST, modela una clase de asociación.")
        collection = annotation in {"OneToMany", "ManyToMany"}
        role_name = str(data.get("targetRole") or target.variable_name)
        base_field_name = to_camel_case(role_name, target.variable_name)
        if collection and not base_field_name.endswith("s"):
            base_field_name = f"{base_field_name}s"

        source.relationships.append(
            Relationship(
                relation_type=relation_type,
                field_name=unique_relationship_field(source, base_field_name),
                target_class_name=target.class_name,
                target_table_name=target.table_name,
                source_cardinality=source_cardinality,
                target_cardinality=target_cardinality,
                annotation=annotation,
                collection=collection,
                required=target_cardinality in {"1", "1..*"},
                cascade_all=relation_type == "composition",
                orphan_removal=relation_type == "composition" and annotation in {"OneToOne", "OneToMany"},
            )
        )

    for child, parent in generalizations:
        inherited = {attribute.java_name for attribute in parent.attributes}
        if inherited & {attribute.java_name for attribute in child.attributes}:
            raise ValueError(f"{child.class_name} vuelve a declarar un atributo heredado de {parent.class_name}.")
        child.inherited_fields = inherited
        child.attributes = parent.attributes + child.attributes

    return entities, warnings


def package_path(base_package: str) -> str:
    """Convierte un paquete Java en ruta de carpetas."""

    return base_package.replace(".", "/")


def common_imports(attributes: list[Attribute]) -> list[str]:
    """Calcula imports Java adicionales segun los tipos usados por los atributos."""

    imports: set[str] = set()

    for attribute in attributes:
        if attribute.java_type == "BigDecimal":
            imports.add("java.math.BigDecimal")
        if attribute.java_type == "LocalDate":
            imports.add("java.time.LocalDate")
        if attribute.java_type == "LocalDateTime":
            imports.add("java.time.LocalDateTime")

    return sorted(imports)


def validation_annotation(attribute: Attribute) -> str | None:
    """Devuelve la anotacion de validacion que corresponde a un atributo."""

    if attribute.primary_key or attribute.nullable:
        return None

    if attribute.java_type == "String":
        return "@NotBlank"

    return "@NotNull"


def field_declaration(
    attribute: Attribute,
    include_validation: bool = True,
    generated_id: bool = False,
) -> list[str]:
    """Genera las lineas Java de un campo, incluyendo JPA y validaciones."""

    lines: list[str] = []
    validation = validation_annotation(attribute) if include_validation else None

    if validation:
        lines.append(f"    {validation}")

    if attribute.primary_key:
        lines.append("    @Id")
    if generated_id:
        lines.append("    @GeneratedValue(strategy = GenerationType.IDENTITY)")

    column_parts = []

    if not attribute.nullable:
        column_parts.append("nullable = false")

    if column_parts:
        lines.append(f"    @Column({', '.join(column_parts)})")

    lines.append(f"    private {attribute.java_type} {attribute.java_name};")
    return lines


def generate_composite_id_class(base_package: str, entity: Entity) -> GeneratedFile:
    """Genera la clase @Embeddable para entidades con clave primaria compuesta (ej: DetallesPedidoId)."""

    imports = [
        "jakarta.persistence.Column",
        "jakarta.persistence.Embeddable",
        "java.io.Serializable",
        "lombok.AllArgsConstructor",
        "lombok.EqualsAndHashCode",
        "lombok.Getter",
        "lombok.NoArgsConstructor",
        "lombok.Setter",
    ]
    imports.extend(common_imports(entity.pk_attributes))

    fields: list[str] = []
    for attr in entity.pk_attributes:
        fields.append(f'    @Column(name = "{to_snake_case(attr.name)}")')
        fields.append(f"    private {attr.java_type} {attr.java_name};")
        fields.append("")

    content = "\n".join(
        [
            f"package {base_package}.models;",
            "",
            *[f"import {item};" for item in sorted(set(imports))],
            "",
            "@Embeddable",
            "@Getter",
            "@Setter",
            "@NoArgsConstructor",
            "@AllArgsConstructor",
            "@EqualsAndHashCode",
            f"public class {entity.composite_id_class_name} implements Serializable {{",
            "    private static final long serialVersionUID = 1L;",
            "",
            *fields,
            "}",
            "",
        ]
    )

    return GeneratedFile(
        path=f"src/main/java/{package_path(base_package)}/models/{entity.composite_id_class_name}.java",
        language="java",
        content=content,
    )


def relationship_field_declaration(entity: Entity, relationship: Relationship) -> list[str]:
    """Genera una propiedad JPA respetando tipo UML, cardinalidad y ciclo de vida."""

    options: list[str] = []
    if relationship.mapped_by:
        options.append(f'mappedBy = "{relationship.mapped_by}"')
    if relationship.cascade_all:
        options.append("cascade = CascadeType.ALL")
    if relationship.orphan_removal:
        options.append("orphanRemoval = true")
    if relationship.annotation in {"OneToOne", "ManyToOne"}:
        options.append(f"optional = {str(not relationship.required).lower()}")

    annotation = f"    @{relationship.annotation}"
    if options:
        annotation += f"({', '.join(options)})"

    lines: list[str] = []
    if relationship.maps_id:
        lines.append(f'    @MapsId("{relationship.maps_id}")')
    lines.append(annotation)
    if relationship.annotation == "ManyToMany":
        lines.extend(
            [
                "    @JoinTable(",
                f'        name = "{entity.table_name}_{relationship.target_table_name}",',
                f'        joinColumns = @JoinColumn(name = "{entity.variable_name}_id"),',
                f'        inverseJoinColumns = @JoinColumn(name = "{relationship.field_name}_id")',
                "    )",
            ]
        )
    elif relationship.mapped_by:
        pass
    elif relationship.join_columns:
        nullable = str(not relationship.required).lower()
        unique = ", unique = true" if relationship.annotation == "OneToOne" else ""
        if len(relationship.join_columns) == 1:
            column, referenced = relationship.join_columns[0]
            lines.append(f'    @JoinColumn(name = "{column}", referencedColumnName = "{referenced}", nullable = {nullable}{unique})')
        else:
            lines.append("    @JoinColumns({")
            lines.append(",\n".join(f'        @JoinColumn(name = "{column}", referencedColumnName = "{referenced}", nullable = {nullable})' for column, referenced in relationship.join_columns))
            lines.append("    })")
    elif relationship.annotation == "OneToMany":
        lines.append(f'    @JoinColumn(name = "{entity.variable_name}_id")')
    else:
        nullable = str(not relationship.required).lower()
        join_column = relationship.join_column or f"{relationship.field_name}_id"
        lines.append(
            f'    @JoinColumn(name = "{join_column}", nullable = {nullable})'
        )

    if relationship.collection:
        lines.append(
            f"    private List<{relationship.target_class_name}> "
            f"{relationship.field_name} = new ArrayList<>();"
        )
    else:
        lines.append(
            f"    private {relationship.target_class_name} {relationship.field_name};"
        )
    return lines


def generate_model(base_package: str, entity: Entity) -> GeneratedFile:
    """Genera model/Entity.java, incluyendo herencia y relaciones JPA."""

    imports = [
        "jakarta.persistence.*",
        "lombok.AllArgsConstructor",
        "lombok.Getter",
        "lombok.NoArgsConstructor",
        "lombok.Setter",
    ]

    fields: list[str] = []
    model_attributes = (
        [attribute for attribute in entity.attributes if attribute.java_name not in entity.inherited_fields]
        if entity.parent_class_name
        else entity.attributes
    )

    if entity.is_composite_id:
        fields.append("    @EmbeddedId")
        fields.append(f"    private {entity.composite_id_class_name} id;")
        fields.append("")

        non_pk_attributes = [attribute for attribute in model_attributes if not attribute.primary_key]
        validation_needed = any(validation_annotation(attribute) for attribute in non_pk_attributes)

        if validation_needed:
            imports.extend(["jakarta.validation.constraints.NotBlank", "jakarta.validation.constraints.NotNull"])

        imports.extend(common_imports(non_pk_attributes))

        for attribute in non_pk_attributes:
            fields.extend(field_declaration(attribute))
            fields.append("")
    else:
        validation_needed = any(validation_annotation(attribute) for attribute in model_attributes)

        if validation_needed:
            imports.extend(["jakarta.validation.constraints.NotBlank", "jakarta.validation.constraints.NotNull"])

        imports.extend(common_imports(model_attributes))

        for attribute in model_attributes:
            fields.extend(
                field_declaration(
                    attribute,
                    generated_id=entity.generated_id and attribute.primary_key,
                )
            )
            fields.append("")

    if any(relationship.collection for relationship in entity.relationships):
        imports.extend(["java.util.ArrayList", "java.util.List"])

    for relationship in entity.relationships:
        fields.extend(relationship_field_declaration(entity, relationship))
        fields.append("")

    has_fields = bool(fields)
    if entity.contract_methods:
        imports.extend(["java.math.BigDecimal", "java.time.LocalDate", "java.time.LocalDateTime"])
        for signature in entity.contract_methods.values():
            fields.extend([
                "    @Override",
                f"    public {signature} {{",
                '        throw new UnsupportedOperationException("Implementa la operación definida por el contrato UML.");',
                "    }",
                "",
            ])

    inheritance_annotation = (
        ["@Inheritance(strategy = InheritanceType.JOINED)"]
        if entity.inheritance_parent and not entity.parent_class_name
        else []
    )
    extends_clause = f" extends {entity.parent_class_name}" if entity.parent_class_name else ""
    implements_clause = f" implements {', '.join(entity.interfaces)}" if entity.interfaces else ""
    class_modifier = "abstract " if entity.abstract else ""
    composite_uniques = [
        "@UniqueConstraint(columnNames = {" + ", ".join(f'"{column}"' for column, _ in rel.join_columns) + "})"
        for rel in entity.relationships if rel.annotation == "OneToOne" and len(rel.join_columns) > 1
    ]
    table_annotation = f'@Table(name = "{entity.table_name}"'
    if composite_uniques:
        table_annotation += ", uniqueConstraints = {" + ", ".join(composite_uniques) + "}"

    content = "\n".join(
        [
            f"package {base_package}.models;",
            "",
            *[f"import {item};" for item in sorted(set(imports))],
            "",
            "@Entity",
            table_annotation + ")",
            *inheritance_annotation,
            "@Getter",
            "@Setter",
            "@NoArgsConstructor",
            *(["@AllArgsConstructor"] if has_fields else []),
            f"public {class_modifier}class {entity.class_name}{extends_clause}{implements_clause} {{",
            *fields,
            "}",
            "",
        ]
    )

    return GeneratedFile(
        path=f"src/main/java/{package_path(base_package)}/models/{entity.class_name}.java",
        language="java",
        content=content,
    )



def generate_repository(base_package: str, entity: Entity) -> GeneratedFile:
    """Genera el repository que extiende JpaRepository."""

    id_import = ""
    if entity.is_composite_id:
        id_import = f"import {base_package}.models.{entity.composite_id_class_name};"

    content = f"""package {base_package}.repositories;

import {base_package}.models.{entity.class_name};
{id_import}
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface {entity.class_name}Repository extends JpaRepository<{entity.class_name}, {entity.id_attribute.java_type}> {{
}}
"""

    return GeneratedFile(
        path=f"src/main/java/{package_path(base_package)}/repositories/{entity.class_name}Repository.java",
        language="java",
        content=content,
    )


def dto_field_declaration(attribute: Attribute, required: bool = False) -> list[str]:
    """Genera las lineas de un campo para DTO (solo validaciones Jakarta, sin anotaciones JPA @Column/@Id)."""

    lines: list[str] = []
    validation = validation_annotation(attribute)
    if required:
        validation = "@NotBlank" if attribute.java_type == "String" else "@NotNull"

    if validation:
        lines.append(f"    {validation}")

    lines.append(f"    private {attribute.java_type} {attribute.java_name};")
    return lines


def generate_request_dto(base_package: str, entity: Entity) -> GeneratedFile:
    """Genera el DTO usado para crear o actualizar una entidad."""

    attributes = request_attributes(entity)
    imports = [
        "lombok.Getter",
        "lombok.Setter",
    ]
    validation_needed = any(
        attribute.primary_key and not entity.generated_id for attribute in attributes
    ) or any(
        validation_annotation(attribute) for attribute in attributes
    )

    if validation_needed:
        imports.extend(["jakarta.validation.constraints.NotBlank", "jakarta.validation.constraints.NotNull"])

    imports.extend(common_imports(attributes))
    imports.extend(reference_id_imports(base_package, entity))

    fields: list[str] = []

    for attribute in attributes:
        fields.extend(
            dto_field_declaration(
                attribute,
                required=attribute.primary_key and not entity.generated_id,
            )
        )
        fields.append("")

    content = "\n".join(
        [
            f"package {base_package}.dto;",
            "",
            *[f"import {item};" for item in sorted(set(imports))],
            "",
            "@Getter",
            "@Setter",
            f"public class {entity.class_name}Request {{",
            *(fields or ["    // Sin campos editables definidos en el diagrama."]),
            "}",
            "",
        ]
    )

    return GeneratedFile(
        path=f"src/main/java/{package_path(base_package)}/dto/{entity.class_name}Request.java",
        language="java",
        content=content,
    )


def generate_response_dto(base_package: str, entity: Entity) -> GeneratedFile:
    """Genera el DTO usado para responder datos al cliente REST."""

    imports = [
        "lombok.AllArgsConstructor",
        "lombok.Getter",
        "lombok.NoArgsConstructor",
        "lombok.Setter",
    ]
    attributes = entity.attributes + reference_attributes(entity)
    imports.extend(common_imports(attributes))
    imports.extend(reference_id_imports(base_package, entity))

    fields = [f"    private {attribute.java_type} {attribute.java_name};" for attribute in attributes]

    content = "\n".join(
        [
            f"package {base_package}.dto;",
            "",
            *[f"import {item};" for item in sorted(set(imports))],
            "",
            "@Getter",
            "@Setter",
            "@NoArgsConstructor",
            "@AllArgsConstructor",
            f"public class {entity.class_name}Response {{",
            *fields,
            "}",
            "",
        ]
    )

    return GeneratedFile(
        path=f"src/main/java/{package_path(base_package)}/dto/{entity.class_name}Response.java",
        language="java",
        content=content,
    )


def setter_name(attribute: Attribute) -> str:
    """Construye el nombre del setter Java para un atributo."""

    return f"set{attribute.java_name[:1].upper()}{attribute.java_name[1:]}"


def getter_name(attribute: Attribute) -> str:
    """Construye el nombre del getter Java para un atributo."""

    return f"get{attribute.java_name[:1].upper()}{attribute.java_name[1:]}"


def generate_service(base_package: str, entity: Entity) -> GeneratedFile:
    """Genera el service con CRUD completo y conversion a DTO."""

    repo_var = f"{entity.variable_name}Repository"
    request_var = "request"
    model_var = entity.variable_name
    editable_attributes = [attribute for attribute in entity.attributes if not attribute.primary_key]
    create_attributes = [
        attribute
        for attribute in entity.attributes
        if not attribute.primary_key or (not entity.generated_id and not entity.is_composite_id)
    ]
    mapped_relationships = [
        relationship for relationship in entity.relationships if relationship.maps_id
    ]

    create_attribute_assignments = [
        f"        {model_var}.{setter_name(attribute)}({request_var}.{getter_name(attribute)}());"
        for attribute in create_attributes
    ]
    update_attribute_assignments = [
        f"        {model_var}.{setter_name(attribute)}({request_var}.{getter_name(attribute)}());"
        for attribute in editable_attributes
    ]
    response_values = [
        (
            f"{model_var}.getId().{getter_name(attribute)}()"
            if entity.is_composite_id and attribute.primary_key
            else f"{model_var}.{getter_name(attribute)}()"
        )
        for attribute in entity.attributes
    ]
    for relationship in entity.relationships:
        if relationship.request_field:
            related = f"{model_var}.get{relationship.field_name[:1].upper()}{relationship.field_name[1:]}()"
            id_getter = relationship.target_id_field[:1].upper() + relationship.target_id_field[1:]
            response_values.append(f"{related} == null ? null : {related}.get{id_getter}()")
    response_args = ", ".join(response_values)
    composite_id_assignment = ""
    if entity.is_composite_id:
        id_arguments = ", ".join(
            f"request.{getter_name(attribute)}()" for attribute in entity.pk_attributes
        )
        composite_id_assignment = (
            f"        {model_var}.setId(new {entity.composite_id_class_name}({id_arguments}));"
        )

    relationship_assignments = []
    writable_relationships = mapped_relationships + [r for r in entity.relationships if r.request_field]
    update_relationship_assignments = []
    for relationship in writable_relationships:
        repository_var = f"{relationship.field_name}Repository"
        request_field = relationship.maps_id or relationship.request_field
        request_getter = f"get{request_field[:1].upper()}{request_field[1:]}"
        setter = f"set{relationship.field_name[:1].upper()}{relationship.field_name[1:]}"
        request_id = f"request.{request_getter}()"
        lookup = f"{repository_var}.findById({request_id})"
        if not relationship.required:
            lookup = f"{request_id} == null ? null : {lookup}"
        assignments = (
            [
                f"        {model_var}.{setter}(",
                f"                {lookup}",
                "                        .orElseThrow(() -> new ResourceNotFoundException(",
                f'                                "{relationship.target_class_name} no encontrado")));',
            ]
        )
        relationship_assignments.extend(assignments)
        if relationship.request_field:
            update_relationship_assignments.extend(assignments)

    dependency_fields = [f"    private final {entity.class_name}Repository {repo_var};"]
    constructor_parameters = [f"{entity.class_name}Repository {repo_var}"]
    constructor_assignments = [f"        this.{repo_var} = {repo_var};"]
    extra_imports: list[str] = []
    if entity.is_composite_id:
        extra_imports.append(
            f"import {base_package}.models.{entity.composite_id_class_name};"
        )
    for relationship in writable_relationships:
        repository_var = f"{relationship.field_name}Repository"
        if repository_var == repo_var:
            continue
        dependency_fields.append(
            f"    private final {relationship.target_class_name}Repository {repository_var};"
        )
        constructor_parameters.append(
            f"{relationship.target_class_name}Repository {repository_var}"
        )
        constructor_assignments.append(f"        this.{repository_var} = {repository_var};")
        extra_imports.append(
            f"import {base_package}.repositories.{relationship.target_class_name}Repository;"
        )

    create_assignments = [
        *([composite_id_assignment] if composite_id_assignment else []),
        *relationship_assignments,
        *create_attribute_assignments,
    ]
    # Una clave compuesta identifica al recurso y no debe cambiarse durante PUT.
    # Las relaciones @MapsId se conservan a partir de la entidad ya recuperada.
    update_assignments = [*update_relationship_assignments, *update_attribute_assignments]

    content = f"""package {base_package}.services;

import {base_package}.dto.{entity.class_name}Request;
import {base_package}.dto.{entity.class_name}Response;
import {base_package}.exceptions.ResourceNotFoundException;
import {base_package}.models.{entity.class_name};
import {base_package}.repositories.{entity.class_name}Repository;
{chr(10).join(sorted(set(extra_imports)))}
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class {entity.class_name}Service {{

{chr(10).join(dependency_fields)}

    public {entity.class_name}Service({', '.join(constructor_parameters)}) {{
{chr(10).join(constructor_assignments)}
    }}

    public List<{entity.class_name}Response> listar() {{
        return {repo_var}.findAll()
                .stream()
                .map(this::toResponse)
                .toList();
    }}

    public {entity.class_name}Response buscarPorId({entity.id_attribute.java_type} id) {{
        return toResponse(obtenerEntidad(id));
    }}

    public {entity.class_name}Response crear({entity.class_name}Request request) {{
        {entity.class_name} {model_var} = new {entity.class_name}();
{chr(10).join(create_assignments) if create_assignments else "        // No hay campos editables definidos."}
        return toResponse({repo_var}.save({model_var}));
    }}

    public {entity.class_name}Response actualizar({entity.id_attribute.java_type} id, {entity.class_name}Request request) {{
        {entity.class_name} {model_var} = obtenerEntidad(id);
{chr(10).join(update_assignments) if update_assignments else "        // No hay campos editables definidos."}
        return toResponse({repo_var}.save({model_var}));
    }}

    public void eliminar({entity.id_attribute.java_type} id) {{
        {entity.class_name} {model_var} = obtenerEntidad(id);
        {repo_var}.delete({model_var});
    }}

    private {entity.class_name} obtenerEntidad({entity.id_attribute.java_type} id) {{
        return {repo_var}.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException("{entity.class_name} no encontrado con id " + id));
    }}

    private {entity.class_name}Response toResponse({entity.class_name} {model_var}) {{
        return new {entity.class_name}Response({response_args});
    }}
}}
"""

    return GeneratedFile(
        path=f"src/main/java/{package_path(base_package)}/services/{entity.class_name}Service.java",
        language="java",
        content=content,
    )


def generate_controller(base_package: str, entity: Entity) -> GeneratedFile:
    """Genera el controller REST con endpoints CRUD."""

    service_var = f"{entity.variable_name}Service"
    model_import = ""
    if entity.is_composite_id:
        model_import = f"import {base_package}.models.{entity.composite_id_class_name};"
        id_path = "/" + "/".join(
            f"{{{attribute.java_name}}}" for attribute in entity.pk_attributes
        )
        id_parameters = ",\n            ".join(
            f'@PathVariable("{attribute.java_name}") {attribute.java_type} {attribute.java_name}'
            for attribute in entity.pk_attributes
        )
        id_expression = (
            f"new {entity.composite_id_class_name}"
            f"({', '.join(attribute.java_name for attribute in entity.pk_attributes)})"
        )
    else:
        id_path = "/{id}"
        id_parameters = f"@PathVariable {entity.id_attribute.java_type} id"
        id_expression = "id"

    content = f"""package {base_package}.controllers;

import {base_package}.dto.{entity.class_name}Request;
import {base_package}.dto.{entity.class_name}Response;
{model_import}
import {base_package}.services.{entity.class_name}Service;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/{entity.route_name}")
public class {entity.class_name}Controller {{

    private final {entity.class_name}Service {service_var};

    public {entity.class_name}Controller({entity.class_name}Service {service_var}) {{
        this.{service_var} = {service_var};
    }}

    @GetMapping
    public ResponseEntity<List<{entity.class_name}Response>> listar() {{
        return ResponseEntity.ok({service_var}.listar());
    }}

    @GetMapping("{id_path}")
    public ResponseEntity<{entity.class_name}Response> buscarPorId(
            {id_parameters}
    ) {{
        return ResponseEntity.ok({service_var}.buscarPorId({id_expression}));
    }}

    @PostMapping
    public ResponseEntity<{entity.class_name}Response> crear(@Valid @RequestBody {entity.class_name}Request request) {{
        return ResponseEntity.status(HttpStatus.CREATED).body({service_var}.crear(request));
    }}

    @PutMapping("{id_path}")
    public ResponseEntity<{entity.class_name}Response> actualizar(
            {id_parameters},
            @Valid @RequestBody {entity.class_name}Request request
    ) {{
        return ResponseEntity.ok({service_var}.actualizar({id_expression}, request));
    }}

    @DeleteMapping("{id_path}")
    public ResponseEntity<Void> eliminar(
            {id_parameters}
    ) {{
        {service_var}.eliminar({id_expression});
        return ResponseEntity.noContent().build();
    }}
}}
"""

    return GeneratedFile(
        path=f"src/main/java/{package_path(base_package)}/controllers/{entity.class_name}Controller.java",
        language="java",
        content=content,
    )


def generate_application(base_package: str, project_name: str) -> GeneratedFile:
    """Genera la clase principal de Spring Boot."""

    class_name = f"{to_pascal_case(project_name)}Application"

    content = f"""package {base_package};

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class {class_name} {{

    public static void main(String[] args) {{
        SpringApplication.run({class_name}.class, args);
    }}
}}
"""

    return GeneratedFile(
        path=f"src/main/java/{package_path(base_package)}/{class_name}.java",
        language="java",
        content=content,
    )


def generate_backend_metadata_controller(
    base_package: str,
    project_name: str,
    entities: list[Entity],
) -> GeneratedFile:
    """Genera los endpoints usados por el movil para detectar y describir el backend."""

    schema = {
        "proyecto": project_name,
        "version": "1.0",
        "entidades": [
            {
                "nombre": entity.name,
                "endpoint": f"/api/{entity.route_name}",
                "rutaDetalle": (
                    f"/api/{entity.route_name}/"
                    + "/".join(f"{{{attribute.java_name}}}" for attribute in entity.pk_attributes)
                    if entity.is_composite_id
                    else f"/api/{entity.route_name}/{{id}}"
                ),
                "id": {
                    "nombre": entity.id_attribute.java_name,
                    "type": map_schema_type(entity.id_attribute.java_type),
                    "generado": entity.generated_id,
                    "compuesto": entity.is_composite_id,
                    "campos": [
                        {
                            "nombre": attribute.java_name,
                            "type": map_schema_type(attribute.java_type),
                        }
                        for attribute in entity.pk_attributes
                    ],
                },
                "atributos": {
                    attribute.java_name: {
                        "type": map_schema_type(attribute.java_type),
                        "required": not attribute.nullable,
                    }
                    for attribute in entity.attributes + reference_attributes(entity)
                    if not attribute.primary_key
                },
                "operaciones": [
                    "CREAR",
                    "LISTAR",
                    "OBTENER",
                    "ACTUALIZAR",
                    "ELIMINAR",
                ],
                "heredaDe": entity.parent_class_name,
                "relaciones": [
                    {
                        "campo": relationship.field_name,
                        "destino": relationship.target_class_name,
                        "tipoUml": relationship.relation_type,
                        "tipoJpa": relationship.annotation,
                        "sourceCardinality": relationship.source_cardinality,
                        "targetCardinality": relationship.target_cardinality,
                    }
                    for relationship in entity.relationships
                ],
            }
            for entity in entities
        ],
    }
    schema_json = json.dumps(schema, ensure_ascii=False, indent=2)
    project_literal = json.dumps(project_name, ensure_ascii=False)

    content = f'''package {base_package}.controllers;

import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api")
public class BackendMetadataController {{

    private static final String SCHEMA_JSON = """
{schema_json}
            """;

    @GetMapping("/health")
    public Map<String, Object> health() {{
        return Map.of(
                "status", "UP",
                "project", {project_literal},
                "schemaVersion", "1.0"
        );
    }}

    @GetMapping(value = "/schema", produces = MediaType.APPLICATION_JSON_VALUE)
    public String schema() {{
        return SCHEMA_JSON;
    }}
}}
'''

    return GeneratedFile(
        path=f"src/main/java/{package_path(base_package)}/controllers/BackendMetadataController.java",
        language="java",
        content=content,
    )


def json_example_value(java_type: str) -> Any:
    """Devuelve un valor JSON representativo para documentar un tipo Java."""

    examples: dict[str, Any] = {
        "Long": 1,
        "Integer": 1,
        "Double": 10.5,
        "Float": 10.5,
        "BigDecimal": 10.5,
        "Boolean": True,
        "LocalDate": "2026-09-23",
        "LocalDateTime": "2026-09-23T12:00:00",
    }
    return examples.get(java_type, "ejemplo")


def request_attributes(entity: Entity) -> list[Attribute]:
    """Replica los campos que expone el DTO Request de una entidad."""

    return [
        attribute
        for attribute in entity.attributes
        if not attribute.primary_key or entity.is_composite_id or not entity.generated_id
    ] + reference_attributes(entity)


def reference_attributes(entity: Entity) -> list[Attribute]:
    return [
        Attribute(r.request_field, r.request_field, r.target_id_type, False, True, not r.required)
        for r in entity.relationships if r.request_field
    ]


def reference_id_imports(base_package: str, entity: Entity) -> list[str]:
    return [
        f"{base_package}.models.{r.target_id_type}"
        for r in entity.relationships if r.request_field and len(r.join_columns) > 1
    ]


def entity_route_template(entity: Entity) -> str:
    """Construye la ruta de detalle tal como la publica el controller."""

    base_route = f"/api/{entity.route_name}"
    if entity.is_composite_id:
        identifiers = "/".join(
            f"{{{attribute.java_name}}}" for attribute in entity.pk_attributes
        )
        return f"{base_route}/{identifiers}"
    return f"{base_route}/{{id}}"


def entity_example_detail_route(entity: Entity) -> str:
    """Sustituye los parametros de ruta por valores utilizables en Postman."""

    route = entity_route_template(entity)
    if entity.is_composite_id:
        for attribute in entity.pk_attributes:
            route = route.replace(
                f"{{{attribute.java_name}}}",
                str(json_example_value(attribute.java_type)).lower()
                if attribute.java_type == "Boolean"
                else str(json_example_value(attribute.java_type)),
            )
        return route

    value = json_example_value(entity.id_attribute.java_type)
    return route.replace(
        "{id}",
        str(value).lower() if entity.id_attribute.java_type == "Boolean" else str(value),
    )


def generate_readme(
    project_name: str,
    database_name: str,
    entities: list[Entity],
) -> str:
    """Documenta instalacion, variables, rutas y cuerpos JSON del backend."""

    endpoint_rows = [
        "| Metodo | Ruta | Descripcion |",
        "|---|---|---|",
        "| GET | `/api/health` | Comprobar que el backend esta activo |",
        "| GET | `/api/schema` | Obtener metadatos de entidades y campos |",
    ]
    example_sections: list[str] = []

    for entity in entities:
        collection_route = f"/api/{entity.route_name}"
        detail_route = entity_route_template(entity)
        endpoint_rows.extend(
            [
                f"| GET | `{collection_route}` | Listar {entity.name} |",
                f"| GET | `{detail_route}` | Obtener {entity.name} por id |",
                f"| POST | `{collection_route}` | Crear {entity.name} |",
                f"| PUT | `{detail_route}` | Actualizar {entity.name} |",
                f"| DELETE | `{detail_route}` | Eliminar {entity.name} |",
            ]
        )

        request_body = {
            attribute.java_name: json_example_value(attribute.java_type)
            for attribute in request_attributes(entity)
        }
        response_body = {
            attribute.java_name: json_example_value(attribute.java_type)
            for attribute in entity.attributes + reference_attributes(entity)
        }
        request_json = json.dumps(request_body, ensure_ascii=False, indent=2)
        response_json = json.dumps(response_body, ensure_ascii=False, indent=2)
        collection_response_json = json.dumps(
            [response_body],
            ensure_ascii=False,
            indent=2,
        )
        example_detail_route = entity_example_detail_route(entity)
        example_sections.append(
            "\n".join(
                [
                    f"### {entity.name}",
                    "",
                    f"#### Crear - `POST {collection_route}`",
                    "",
                    "En Postman usa **Body > raw > JSON**:",
                    "",
                    "```json",
                    request_json,
                    "```",
                    "",
                    "Respuesta `201 Created`:",
                    "",
                    "```json",
                    response_json,
                    "```",
                    "",
                    f"#### Listar - `GET {collection_route}`",
                    "",
                    "Esta peticion no lleva body. Respuesta `200 OK`:",
                    "",
                    "```json",
                    collection_response_json,
                    "```",
                    "",
                    f"#### Obtener por ID - `GET {detail_route}`",
                    "",
                    f"URL de ejemplo: `GET {example_detail_route}`",
                    "",
                    "Esta peticion no lleva body. Respuesta `200 OK`:",
                    "",
                    "```json",
                    response_json,
                    "```",
                    "",
                    f"#### Actualizar - `PUT {detail_route}`",
                    "",
                    f"URL de ejemplo: `PUT {example_detail_route}`",
                    "",
                    "En Postman usa **Body > raw > JSON**:",
                    "",
                    "```json",
                    request_json,
                    "```",
                    "",
                    "Respuesta `200 OK`:",
                    "",
                    "```json",
                    response_json,
                    "```",
                    "",
                    f"#### Eliminar - `DELETE {detail_route}`",
                    "",
                    f"URL de ejemplo: `DELETE {example_detail_route}`",
                    "",
                    "Esta peticion no lleva body ni devuelve JSON. La respuesta correcta es `204 No Content`.",
                ]
            )
        )

    routes = "\n".join(endpoint_rows)
    examples = "\n\n".join(example_sections) or (
        "El diagrama no contiene entidades, por lo que no se generaron rutas CRUD."
    )

    return f"""# {project_name}

Backend Spring Boot generado por DrawSchemaAI a partir del diagrama de clases.

## Requisitos

- Java 17 o superior
- Maven 3.9 o superior
- PostgreSQL

Comprueba la instalacion:

```powershell
java -version
mvn -version
```

## Base de datos

Ejecuta el archivo `database.sql` o crea la base manualmente:

```sql
CREATE DATABASE {database_name};
```

La conexion acepta variables de entorno. Estos son sus valores predeterminados:

| Variable | Valor predeterminado |
|---|---|
| `DB_URL` | `jdbc:postgresql://localhost:5432/{database_name}` |
| `DB_USERNAME` | `postgres` |
| `DB_PASSWORD` | `postgres` |
| `SERVER_PORT` | `8086` |

Ejemplo para PowerShell si tu configuracion es diferente:

```powershell
$env:DB_URL="jdbc:postgresql://localhost:5432/{database_name}"
$env:DB_USERNAME="postgres"
$env:DB_PASSWORD="tu_password"
$env:SERVER_PORT="8086"
```

No guardes passwords reales dentro de `application.properties` ni los subas a Git.

## Ejecutar

Desde la carpeta raiz del proyecto:

```powershell
mvn spring-boot:run
```

Tambien puedes compilar y ejecutar el JAR:

```powershell
mvn clean package
java -jar target/{project_name}-0.0.1-SNAPSHOT.jar
```

La URL base local es `http://localhost:8086`. Prueba primero:

```http
GET http://localhost:8086/api/health
```

## Rutas REST

{routes}

En las rutas de detalle sustituye `{{id}}` y los identificadores compuestos por valores reales.

## JSON para Postman

Los ejemplos siguientes muestran el body y la respuesta esperada de cada operacion CRUD. Usa `Content-Type: application/json` solamente en `POST` y `PUT`.

{examples}

## Respuestas y errores

- `200 OK`: consulta o actualizacion correcta.
- `201 Created`: recurso creado.
- `204 No Content`: recurso eliminado.
- `400 Bad Request`: JSON o validacion incorrecta.
- `404 Not Found`: no existe el id solicitado.

Ejemplo de error de validacion:

```json
{{
  "timestamp": "2026-09-23T12:00:00",
  "status": 400,
  "message": "Error de validacion",
  "errors": ["nombre: no debe estar vacio"]
}}
```
"""


def generate_common_files(
    base_package: str,
    project_name: str,
    database_name: str,
    entities: list[Entity],
) -> list[GeneratedFile]:
    """Genera archivos comunes: pom.xml, properties, README, SQL, CORS y errores."""

    project_literal = json.dumps(project_name, ensure_ascii=False)

    pom = f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.3.5</version>
        <relativePath/>
    </parent>

    <groupId>{base_package}</groupId>
    <artifactId>{project_name}</artifactId>
    <version>0.0.1-SNAPSHOT</version>
    <name>{project_name}</name>

    <properties>
        <java.version>17</java.version>
        <lombok.version>1.18.48</lombok.version>
    </properties>

    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-data-jpa</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-validation</artifactId>
        </dependency>
        <dependency>
            <groupId>org.postgresql</groupId>
            <artifactId>postgresql</artifactId>
            <scope>runtime</scope>
        </dependency>
        <dependency>
            <groupId>org.projectlombok</groupId>
            <artifactId>lombok</artifactId>
            <version>${{lombok.version}}</version>
            <optional>true</optional>
        </dependency>
        <dependency>
            <groupId>org.jmdns</groupId>
            <artifactId>jmdns</artifactId>
            <version>3.6.3</version>
        </dependency>
    </dependencies>

    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <version>3.13.0</version>
                <configuration>
                    <annotationProcessorPaths>
                        <path>
                            <groupId>org.projectlombok</groupId>
                            <artifactId>lombok</artifactId>
                            <version>${{lombok.version}}</version>
                        </path>
                    </annotationProcessorPaths>
                </configuration>
            </plugin>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
            </plugin>
        </plugins>
    </build>
</project>
"""

    properties = f"""spring.application.name={project_name}
spring.datasource.url=${{DB_URL:jdbc:postgresql://localhost:5432/{database_name}}}
spring.datasource.username=${{DB_USERNAME:postgres}}
spring.datasource.password=${{DB_PASSWORD:postgres}}

spring.jpa.hibernate.ddl-auto=update
spring.jpa.show-sql=true
spring.jpa.properties.hibernate.format_sql=true
spring.jpa.properties.hibernate.dialect=org.hibernate.dialect.PostgreSQLDialect

server.address=0.0.0.0
server.port=${{SERVER_PORT:8086}}
drawschema.discovery.enabled=true
"""

    database_sql = f"CREATE DATABASE {database_name};\n"

    readme = generate_readme(project_name, database_name, entities)

    resource_not_found = f"""package {base_package}.exceptions;

public class ResourceNotFoundException extends RuntimeException {{

    public ResourceNotFoundException(String message) {{
        super(message);
    }}
}}
"""

    global_exception = f"""package {base_package}.exceptions;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;

@RestControllerAdvice
public class GlobalExceptionHandler {{

    @ExceptionHandler(ResourceNotFoundException.class)
    public ResponseEntity<Map<String, Object>> handleNotFound(ResourceNotFoundException exception) {{
        Map<String, Object> body = new HashMap<>();
        body.put("timestamp", LocalDateTime.now());
        body.put("status", 404);
        body.put("message", exception.getMessage());
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(body);
    }}

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, Object>> handleValidation(MethodArgumentNotValidException exception) {{
        Map<String, Object> body = new HashMap<>();
        body.put("timestamp", LocalDateTime.now());
        body.put("status", 400);
        body.put("message", "Error de validacion");
        body.put("errors", exception.getBindingResult().getFieldErrors()
                .stream()
                .map(error -> error.getField() + ": " + error.getDefaultMessage())
                .toList());
        return ResponseEntity.badRequest().body(body);
    }}
}}
"""

    cors_config = f"""package {base_package}.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class CorsConfig implements WebMvcConfigurer {{

    @Override
    public void addCorsMappings(CorsRegistry registry) {{
        registry.addMapping("/api/**")
                .allowedOrigins("*")
                .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
                .allowedHeaders("*");
    }}
}}
"""

    mdns_config = f"""package {base_package}.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.DisposableBean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.context.WebServerInitializedEvent;
import org.springframework.context.ApplicationListener;
import org.springframework.stereotype.Component;

import javax.jmdns.JmDNS;
import javax.jmdns.ServiceInfo;
import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

@Component
public class MdnsServicePublisher
        implements ApplicationListener<WebServerInitializedEvent>, DisposableBean {{

    private static final Logger log = LoggerFactory.getLogger(MdnsServicePublisher.class);
    private static final String SERVICE_TYPE = "_drawschema._tcp.local.";

    @Value("${{drawschema.discovery.enabled:true}}")
    private boolean enabled;

    private volatile JmDNS jmDNS;

    @Override
    public void onApplicationEvent(WebServerInitializedEvent event) {{
        if (!enabled || jmDNS != null) return;

        Thread publisher = new Thread(() -> publish(event.getWebServer().getPort()), "drawschema-mdns");
        publisher.setDaemon(true);
        publisher.start();
    }}

    private void publish(int port) {{
        try {{
            InetAddress address = findLanAddress();
            Map<String, String> properties = new HashMap<>();
            properties.put("project", {project_literal});
            properties.put("schemaVersion", "1.0");
            properties.put("healthPath", "/api/health");
            properties.put("schemaPath", "/api/schema");

            JmDNS instance = JmDNS.create(address);
            ServiceInfo service = ServiceInfo.create(
                    SERVICE_TYPE,
                    {project_literal},
                    port,
                    0,
                    0,
                    properties
            );
            instance.registerService(service);
            jmDNS = instance;
            log.info("DrawSchema disponible en http://{{}}:{{}}", address.getHostAddress(), port);
        }} catch (Exception exception) {{
            log.warn("No se pudo publicar DrawSchema por mDNS: {{}}", exception.getMessage());
        }}
    }}

    private InetAddress findLanAddress() throws Exception {{
        try (DatagramSocket socket = new DatagramSocket()) {{
            socket.connect(new InetSocketAddress("8.8.8.8", 53));
            InetAddress routedAddress = socket.getLocalAddress();
            if (routedAddress instanceof Inet4Address
                    && !routedAddress.isAnyLocalAddress()
                    && !routedAddress.isLoopbackAddress()) {{
                return routedAddress;
            }}
        }} catch (Exception ignored) {{
            // Sin ruta de salida: se intenta con las interfaces disponibles.
        }}

        InetAddress fallback = null;
        for (NetworkInterface network : Collections.list(NetworkInterface.getNetworkInterfaces())) {{
            if (!network.isUp() || network.isLoopback() || network.isVirtual()) continue;
            for (InetAddress address : Collections.list(network.getInetAddresses())) {{
                if (!(address instanceof Inet4Address) || address.isLoopbackAddress()) continue;
                if (address.isSiteLocalAddress()) return address;
                if (!address.isLinkLocalAddress()) fallback = address;
            }}
        }}
        if (fallback != null) return fallback;
        throw new IllegalStateException("No se encontro una direccion IPv4 de red local");
    }}

    @Override
    public void destroy() throws Exception {{
        JmDNS instance = jmDNS;
        if (instance != null) {{
            instance.unregisterAllServices();
            instance.close();
        }}
    }}
}}
"""

    return [
        GeneratedFile(path="pom.xml", language="xml", content=pom),
        GeneratedFile(path="README.md", language="markdown", content=readme),
        GeneratedFile(path="database.sql", language="sql", content=database_sql),
        GeneratedFile(
            path="src/main/resources/application.properties",
            language="properties",
            content=properties,
        ),
        GeneratedFile(
            path=f"src/main/java/{package_path(base_package)}/exceptions/ResourceNotFoundException.java",
            language="java",
            content=resource_not_found,
        ),
        GeneratedFile(
            path=f"src/main/java/{package_path(base_package)}/exceptions/GlobalExceptionHandler.java",
            language="java",
            content=global_exception,
        ),
        GeneratedFile(
            path=f"src/main/java/{package_path(base_package)}/config/CorsConfig.java",
            language="java",
            content=cors_config,
        ),
        GeneratedFile(
            path=f"src/main/java/{package_path(base_package)}/config/MdnsServicePublisher.java",
            language="java",
            content=mdns_config,
        ),
    ]


def build_spring_boot_project(
    context: dict[str, Any],
    project_name: str,
    base_package: str,
    database_name: str,
) -> tuple[list[GeneratedFile], list[str]]:
    """Orquesta la generacion completa del proyecto Spring Boot."""

    entities, warnings = parse_entities(context)
    files: list[GeneratedFile] = []

    concrete_entities = [entity for entity in entities if not entity.abstract]
    files.extend(generate_common_files(base_package, project_name, database_name, concrete_entities))
    files.append(generate_application(base_package, project_name))
    files.append(generate_backend_metadata_controller(base_package, project_name, concrete_entities))

    model_paths = set()
    for node in ((context.get("diagrama") or {}).get("contenido") or {}).get("nodes") or []:
        data = node.get("data") or {}
        if data.get("kind") != "interface" or data.get("templateParameters"):
            continue
        interface = generate_interface(base_package, data)
        if interface.path in model_paths or any(
            interface.path.endswith(f"/{entity.class_name}.java") for entity in entities
        ):
            raise ValueError(f"Nombre Java de interfaz duplicado: {data.get('name')}.")
        model_paths.add(interface.path)
        files.append(interface)

    for entity in entities:
        if entity.is_composite_id:
            files.append(generate_composite_id_class(base_package, entity))
        files.append(generate_model(base_package, entity))
        files.append(generate_repository(base_package, entity))
        if entity.abstract:
            continue
        files.append(generate_request_dto(base_package, entity))
        files.append(generate_response_dto(base_package, entity))
        files.append(generate_service(base_package, entity))
        files.append(generate_controller(base_package, entity))


    return files, warnings
