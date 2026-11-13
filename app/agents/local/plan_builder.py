"""Construye planes del editor sin delegar IDs ni dependencias al modelo."""
from copy import deepcopy
import unicodedata

from app.schemas.chat import PlannerAction, PlannerResponse
from .commands import Interpretation


def key(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value or "")).casefold()
                   if c.isalnum() and not unicodedata.combining(c))


def build_plan(parsed: Interpretation, context: dict | None):
    context = context or {}
    conversation = context.get("conversacion") or {}
    requester = context.get("solicitante") or conversation.get("solicitante") or {}
    role = str(context.get("user_role") or requester.get("rol_proyecto") or "").upper()
    if parsed.intent != "modify_diagram":
        return PlannerResponse(intent=parsed.intent, summary=parsed.answer,
                               questions=parsed.questions, can_execute=False)
    if role in {"VISUALIZADOR", "VIEWER"}:
        return PlannerResponse(intent="needs_clarification", summary="Tu rol es de solo lectura; no puedes modificar este diagrama.")
    if parsed.questions:
        return PlannerResponse(intent="needs_clarification", summary=parsed.answer, questions=parsed.questions)
    graph = deepcopy((context.get("diagrama") or {}).get("contenido") or {})
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    actions, assumptions = [], []

    def node(name):
        if name is None or not str(name).strip():
            raise ValueError("La interpretación omitió un participante del vínculo. No se prepararon cambios incompletos.")
        matches = [n for n in nodes if str(n.get("id")) == str(name) or key((n.get("data") or {}).get("name")) == key(name)]
        if not matches:
            raise ValueError(f"La clase «{name}» no está en el diagrama activo.")
        if len(matches) > 1:
            raise ValueError(f"Hay varias clases llamadas «{name}» en el diagrama activo; se necesita su identificador.")
        return matches[0]

    def add(tool, args, description, destructive=False):
        action = PlannerAction(order=len(actions) + 1, tool=tool, arguments=args,
                               description=description, requires_confirmation=destructive)
        actions.append(action)
        return action

    def rename_members(members, renames):
        for old, new in renames.items():
            matches = [m for m in members if key(m.get("name")) == key(old)]
            if len(matches) != 1 or not new.strip():
                raise ValueError(f"No se identifica el atributo o método {old} a renombrar.")
            if any(m is not matches[0] and key(m.get("name")) == key(new) for m in members):
                raise ValueError(f"Ya existe un atributo o método llamado {new}.")
            matches[0]["name"] = new

    def create(name, attributes, kind="class", x=None, y=None):
        if not name or not name.strip():
            raise ValueError("Falta el nombre de la clase a crear.")
        if any(key((n.get("data") or {}).get("name")) == key(name) for n in nodes):
            raise ValueError(f"La clase {name} ya existe; debe reutilizarse o modificarse.")
        attributes = [{"type": "VARCHAR", **a} for a in attributes]
        args = {"name": name.strip(), "attributes": attributes, "methods": [], "kind": kind}
        if x is None and y is None:
            x = max(((n.get("position") or {}).get("x", 100) for n in nodes), default=-200) + 300
            y = min(((n.get("position") or {}).get("y", 100) for n in nodes), default=100)
        if x is not None and y is not None:
            args.update(x=x, y=y)
        add("create_class", args, f"Crear clase {name}")
        created = {"id": f"planned-{len(actions)}", "data": deepcopy(args), "position": {"x": x or 100, "y": y or 100}}
        nodes.append(created)
        return created

    try:
        for cmd in parsed.commands:
            attributes = [a.model_dump(exclude_none=True) for a in cmd.attributes]
            if cmd.operation == "create_class":
                created = create(cmd.name, attributes, cmd.kind or "class", cmd.x, cmd.y)
                if cmd.methods:
                    methods = [m.model_dump() for m in cmd.methods]
                    actions[-1].arguments["methods"] = methods
                    created["data"]["methods"] = methods
                if cmd.template_parameters:
                    actions[-1].arguments["templateParameters"] = cmd.template_parameters
                    created["data"]["templateParameters"] = cmd.template_parameters
                    created["data"]["templateParameters"] = cmd.template_parameters
            elif cmd.operation in {"update_class", "delete_class", "move_class"}:
                target = node(cmd.name)
                name = target["data"]["name"]
                args = {"className": name}
                if cmd.operation == "delete_class":
                    add("delete_class", args, f"Eliminar clase {name}", True)
                    nodes.remove(target)
                    edges[:] = [e for e in edges if target["id"] not in (e.get("source"), e.get("target"))]
                elif cmd.operation == "move_class":
                    if cmd.x is None or cmd.y is None:
                        raise ValueError("Faltan las coordenadas para mover la clase.")
                    add("move_class", {**args, "x": cmd.x, "y": cmd.y}, f"Mover clase {name}")
                else:
                    if cmd.new_name:
                        if any(n is not target and key(n["data"].get("name")) == key(cmd.new_name) for n in nodes):
                            raise ValueError(f"Ya existe una clase llamada {cmd.new_name}.")
                        args["newName"] = cmd.new_name
                    if attributes or cmd.remove_attributes or cmd.rename_attributes:
                        removed = {key(n) for n in cmd.remove_attributes}
                        merged = [a for a in deepcopy(target["data"].get("attributes") or []) if key(a.get("name")) not in removed]
                        rename_members(merged, cmd.rename_attributes)
                        for attribute in attributes:
                            previous = next((a for a in merged if key(a.get("name")) == key(attribute["name"])), None)
                            if previous is None:
                                merged.append({"type": "VARCHAR", **attribute})
                            else:
                                previous.update(attribute)
                        args["attributes"] = merged
                    if cmd.kind:
                        args["kind"] = cmd.kind
                    if cmd.template_parameters:
                        args["templateParameters"] = cmd.template_parameters
                    if cmd.methods or cmd.remove_methods or cmd.rename_methods:
                        removed = {key(n) for n in cmd.remove_methods}
                        methods = [m for m in deepcopy(target["data"].get("methods") or []) if key(m.get("name")) not in removed]
                        rename_members(methods, cmd.rename_methods)
                        for method in cmd.methods:
                            methods = [m for m in methods if key(m.get("name")) != key(method.name)]
                            methods.append(method.model_dump())
                        args["methods"] = methods
                    if cmd.template_parameters:
                        args["templateParameters"] = cmd.template_parameters
                    if len(args) == 1:
                        raise ValueError(f"No se indicó qué modificar en {name}.")
                    add("update_class", args, f"Actualizar clase {name}", bool(cmd.remove_attributes or cmd.remove_methods))
                    target["data"].update({k: v for k, v in args.items() if k != "className"})
                    if cmd.new_name:
                        target["data"]["name"] = cmd.new_name
            else:
                existing = None
                if cmd.relation_id:
                    existing = next((e for e in edges if str(e.get("id")) == cmd.relation_id), None)
                    if existing is None:
                        raise ValueError("La relación indicada no existe en el diagrama activo.")
                if existing:
                    source = node(cmd.source or existing["source"])
                    target = node(cmd.target or existing["target"])
                    if cmd.old_participant or cmd.new_participant:
                        old, new = node(cmd.old_participant), node(cmd.new_participant)
                        if old["id"] == source["id"]:
                            source = new
                        elif old["id"] == target["id"]:
                            target = new
                        else:
                            raise ValueError("La clase que se quiere reemplazar no participa en la relación seleccionada.")
                else:
                    source, target = node(cmd.source), node(cmd.target)
                if cmd.operation != "create_relation" and existing is None:
                    matches = [e for e in edges if e.get("source") == source["id"] and e.get("target") == target["id"]]
                    if len(matches) != 1:
                        raise ValueError("No se identifica una única relación a modificar o eliminar.")
                    existing = matches[0]
                relation = cmd.relation or ((existing or {}).get("data") or {}).get("relationType") or "association"
                previous_data = (existing or {}).get("data") or {}
                if relation == "association" and (cmd.source_cardinality or previous_data.get("sourceCardinality")) in {"0..*", "1..*"} and (cmd.target_cardinality or previous_data.get("targetCardinality")) in {"0..*", "1..*"}:
                    relation = "associationClass"
                args = {"sourceName": source["data"]["name"], "targetName": target["data"]["name"], "relationType": relation}
                if existing:
                    args["relationId"] = existing["id"]
                if cmd.operation == "delete_relation":
                    add("delete_relation", args, "Eliminar relación", True)
                    edges.remove(existing)
                    continue
                if relation in {"generalization", "realization"}:
                    if source is target:
                        raise ValueError("Herencia y realización no pueden apuntar a la misma clase.")
                    if relation == "realization" and target["data"].get("kind") != "interface":
                        raise ValueError("El destino de una realización debe ser una interfaz.")
                    # Comprueba ciclos con el grafo actual y relaciones ya planificadas.
                    pending, visited = [target["id"]], set()
                    while pending:
                        current = pending.pop()
                        if current == source["id"]:
                            raise ValueError("La relación introduciría un ciclo de herencia o realización.")
                        if current not in visited:
                            visited.add(current)
                            pending.extend(e["target"] for e in edges if e.get("source") == current
                                           and e is not existing and (e.get("data") or {}).get("relationType") == relation)
                else:
                    previous = (existing or {}).get("data") or {}
                    sc = cmd.source_cardinality or previous.get("sourceCardinality") or ("0..*" if relation == "associationClass" else "1")
                    tc = cmd.target_cardinality or previous.get("targetCardinality") or "0..*"
                    if relation == "composition" and sc not in {"1", "0..1"}:
                        raise ValueError("En composición cada Parte pertenece como máximo a un Todo.")
                    if relation != "templateBinding":
                        args.update(sourceCardinality=sc, targetCardinality=tc)
                        if (cmd.source_cardinality is None and not previous.get("sourceCardinality")) or (cmd.target_cardinality is None and not previous.get("targetCardinality")):
                            assumptions.append("Las multiplicidades no indicadas usan una convención editable en el plan.")
                if relation == "templateBinding":
                    bindings = cmd.template_bindings or ((existing or {}).get("data") or {}).get("templateBindings")
                    parameters = target["data"].get("templateParameters") or []
                    if not parameters or not bindings or any(p not in bindings for p in parameters):
                        raise ValueError("La vinculación de plantilla necesita una clase genérica destino y valores para sus parámetros.")
                    args["templateBindings"] = bindings
                if relation == "composition":
                    if any(e is not existing and e.get("target") == target["id"] and e.get("source") != source["id"]
                           and (e.get("data") or {}).get("relationType") == "composition" for e in edges):
                        raise ValueError("La Parte ya tiene otro Todo por composición.")
                    pending, visited = [target["id"]], set()
                    while pending:
                        current = pending.pop()
                        if current == source["id"]:
                            raise ValueError("La composición introduciría un ciclo Todo-Parte.")
                        if current not in visited:
                            visited.add(current)
                            pending.extend(e["target"] for e in edges if e is not existing and e.get("source") == current
                                           and (e.get("data") or {}).get("relationType") == "composition")
                if relation == "associationClass":
                    previous = (existing or {}).get("data") or {}
                    middle_name = cmd.intermediate
                    if not middle_name and previous.get("associationClassId"):
                        middle_name = node(previous["associationClassId"])["data"]["name"]
                    middle_name = middle_name or f"Vinculo{source['data']['name']}{target['data']['name']}"
                    if key(middle_name) in {key(source["data"]["name"]), key(target["data"]["name"])}:
                        raise ValueError("La clase intermedia debe ser distinta de ambos participantes.")
                    matches = [n for n in nodes if key(n["data"].get("name")) == key(middle_name)]
                    if not matches:
                        # Solo reutiliza PK conocidas; no inventa identificadores de negocio.
                        keys = []
                        for participant in (source, target):
                            for attr in participant["data"].get("attributes") or []:
                                if attr.get("primaryKey"):
                                    keys.append({**deepcopy(attr), "name": f"{participant['data']['name']}_{attr['name']}", "primaryKey": True, "foreignKey": True})
                        create(middle_name, keys + [a for a in attributes if key(a["name"]) not in {key(k["name"]) for k in keys}])
                    args["associationClassName"] = matches[0]["data"]["name"] if matches else middle_name
                if cmd.operation == "create_relation":
                    duplicates = [e for e in edges if e.get("source") == source["id"] and e.get("target") == target["id"]
                                  and (e.get("data") or {}).get("relationType") == relation]
                    if duplicates:
                        compare = ("sourceCardinality", "targetCardinality", "associationClassName", "templateBindings")
                        if all(e.get("_planned") and all((e.get("data") or {}).get(k) == args.get(k) for k in compare) for e in duplicates):
                            continue
                        raise ValueError("La relación ya existe o el plan repite el vínculo con datos distintos; debe actualizarse en lugar de duplicarse.")
                add(cmd.operation, args, f"{'Crear' if cmd.operation == 'create_relation' else 'Actualizar'} {relation}: {source['data']['name']} → {target['data']['name']}")
                if existing:
                    existing["data"].update(args)
                    existing["source"], existing["target"] = source["id"], target["id"]
                else:
                    edges.append({"id": f"planned-edge-{len(actions)}", "source": source["id"], "target": target["id"], "data": args, "_planned": True})
        if not actions:
            raise ValueError("La interpretación no contiene cambios para el diagrama.")
    except ValueError as exc:
        return PlannerResponse(intent="needs_clarification", summary="No se prepararon cambios: " + str(exc), questions=[str(exc)])
    summary = "\n".join(([parsed.answer] if parsed.answer else []) + [a.description for a in actions] + list(dict.fromkeys(assumptions)))
    return PlannerResponse(intent="modify_diagram", summary=summary, actions=actions, can_execute=True)
