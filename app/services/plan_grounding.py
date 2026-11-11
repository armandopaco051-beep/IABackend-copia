import re
import unicodedata

from app.schemas.chat import PlannerResponse


CLASS_NAME_PREFIX = (
    r"\b(?:clase|tabla|entidad)\s+(?:(?:de(?!\s+nombre\b)|la|el|una|un|nueva|nuevo)\s+)*"
    r"(?:(?:llamad[ao]|nombrad[ao]|denominad[ao]|de\s+nombre|con\s+(?:el\s+)?nombre(?:\s+de)?)\s*:?\s+)?"
)
CLASS_NAME_REFERENCE = re.compile(
    CLASS_NAME_PREFIX + r"""(?:["'\x60«“]([^"'\x60»”\r\n]+)["'\x60»”]|([^\W\d][\w-]*))""",
    re.IGNORECASE,
)


def normalized(value):
    value = unicodedata.normalize("NFKD", str(value)).casefold()
    return "".join(c for c in value if c.isalnum() and not unicodedata.combining(c))


def grounding_issues(message: str, plan: PlannerResponse, context: dict | None):
    """Check proposed entities against this request/graph; no business-specific names."""
    if plan.intent == "explain_diagram" and not plan.actions:
        # Los ejemplos educativos no necesitan coincidir con clases del diagrama.
        return []
    content = ((context or {}).get("diagrama") or {}).get("contenido") or {}
    names = {normalized((n.get("data") or {}).get("name", "")) for n in content.get("nodes", [])}
    names_by_id = {str(n.get("id")): normalized((n.get("data") or {}).get("name", "")) for n in content.get("nodes", [])}
    explicit = {
        normalized(quoted or plain) for quoted, plain in CLASS_NAME_REFERENCE.findall(message)
    } - {"que", "con", "actual", "existente", "nueva", "intermedia", "asociacion",
         "llamada", "nombrada", "denominada", "nombre"}
    # If a complete referenced name exists, a similarly prefixed class is a different target.
    exact_existing = explicit & names
    association_names = {
        normalized(a.arguments.get("associationClassName", ""))
        for a in plan.actions if a.tool in {"create_relation", "update_relation"}
    } - {""}
    issues = []
    if (re.search(r"\b(?:genera\w*|crea\w*|construye\w*|arma\w*)\b", message, re.IGNORECASE)
        and re.search(r"base\s+de\s+datos|\bbd\b", message, re.IGNORECASE)
        and not re.search(r"sin\s+relaciones|solo\s+(?:las\s+)?tablas", message, re.IGNORECASE)
        and len([a for a in plan.actions if a.tool == "create_class"]) > 1
        and not any(a.tool in {"create_relation", "update_relation"} for a in plan.actions)):
        issues.append("La petición de una base de datos completa necesita acciones de relaciones además de las clases; prepara las clases primero y después sus vínculos.")
    if explicit and not plan.actions and not plan.questions and not any(
        item in normalized(plan.summary) for item in explicit
    ):
        issues.append("La respuesta no atiende a la clase nombrada en la petición actual. Responde sobre esa clase o pregunta qué operación necesita.")
    for action in sorted(plan.actions, key=lambda a: a.order):
        args = action.arguments
        if action.tool in {"update_class", "delete_class", "move_class"}:
            target = normalized(args.get("className", "")) or names_by_id.get(str(args.get("classId", "")), "")
            if target and explicit and not any(
                target == item or (item not in exact_existing and target.startswith(item)) for item in explicit
            ):
                issues.append("La acción modifica una clase diferente de la nombrada en la petición actual.")
        if action.tool == "create_class":
            name = normalized(args.get("name", ""))
            if not name:
                issues.append("Falta el nombre de la clase que se solicita crear.")
            elif name in names:
                issues.append(f"La clase {args.get('name')} ya existe: reutilízala o propón modificarla, no la dupliques.")
            elif explicit and name not in association_names and not any(
                name == item or name.startswith(item) or item.startswith(name) for item in explicit
            ):
                issues.append(f"La clase propuesta {args.get('name')} no coincide con la clase nombrada en la petición actual.")
            names.add(name)
    return issues
