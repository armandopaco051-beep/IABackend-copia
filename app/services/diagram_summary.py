import re
import unicodedata

from app.schemas.chat import PlannerResponse


def requests_diagram_summary(message: str) -> bool:
    text = ''.join(
        char for char in unicodedata.normalize('NFKD', message.casefold())
        if not unicodedata.combining(char)
    )
    if not re.search(r'\b(?:diagrama|modelo)\b', text):
        return False
    if re.search(r'\b(?:agrega|anade|crea|elimina|borra|modifica|actualiza|cambia|relaciona|conecta|aplica|renombra)\b', text):
        return False
    return bool(re.search(
        r'\b(?:contexto|resumen|resume|resumeme|proposito|utilidad|'
        r'para que (?:sirve|funciona|se usa)|como funciona|'
        r'(?:a que|en que) (?:esta )?(?:dirigido|enfocado)|'
        r'explica(?:me)?\s+(?:el|este|mi|nuestro)\s+(?:diagrama|modelo))\b',
        text,
    ))


RELATION_LABELS = {
    'association': 'asociación',
    'associationClass': 'clase de asociación',
    'generalization': 'generalización',
    'composition': 'composición',
    'aggregation': 'agregación',
    'realization': 'realización',
    'templateBinding': 'vinculación de plantilla',
}


def summarize_diagram(context: dict) -> PlannerResponse:
    diagram = context.get('diagrama')
    if not diagram:
        return PlannerResponse(intent='explain_diagram', summary='Abre un diagrama para que pueda resumirlo.')

    project = context.get('proyecto') or {}
    content = diagram.get('contenido') or {}
    nodes = {str(node['id']): node.get('data') or {} for node in content.get('nodes') or [] if 'id' in node}
    names = {node_id: str(data.get('name') or node_id) for node_id, data in nodes.items()}
    edges = content.get('edges') or []
    title = diagram.get('nombre') or 'Diagrama activo'
    project_name = project.get('nombre')
    project_suffix = f' del proyecto «{project_name}»' if project_name else ''
    lines = [f'«{title}»{project_suffix} contiene {len(nodes)} clases y {len(edges)} relaciones.']

    description = str(project.get('descripcion') or '').strip()
    if description:
        lines.append(f'Según la descripción del proyecto, su finalidad es la siguiente: {description}')
    elif names:
        lines.append(f'El modelo organiza la información de {", ".join(list(names.values())[:6])}. '
                     'El propósito de negocio exacto no está indicado en la descripción del proyecto.')
    else:
        lines.append('El diagrama está vacío. Su estructura y finalidad todavía no se pueden resumir a partir de sus clases.')

    relations = []
    for edge in edges:
        source = names.get(str(edge.get('source')))
        target = names.get(str(edge.get('target')))
        if not source or not target:
            continue
        data = edge.get('data') or {}
        label = RELATION_LABELS.get(data.get('relationType'), 'relación')
        name = f' «{data["name"]}»' if data.get('name') else ''
        source_card, target_card = data.get('sourceCardinality'), data.get('targetCardinality')
        cardinalities = f', multiplicidades {source_card} y {target_card}' if source_card and target_card else ''
        intermediate = names.get(str(data.get('associationClassId')))
        through = f', mediante {intermediate}' if intermediate else ''
        relations.append(f'{source} → {target} ({label}{name}{cardinalities}{through})')
        if len(relations) == 5:
            break
    if relations:
        lines.append('Algunos vínculos del modelo: ' + '; '.join(relations) + '.')

    return PlannerResponse(intent='explain_diagram', summary='\n\n'.join(lines))
