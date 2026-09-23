# Flujo de agentes DrawSchemaAI

## Regla principal

La IA no escribe directo en PostgreSQL.
La IA interpreta el mensaje del usuario y propone acciones.
El backend principal valida permisos, reglas UML y persistencia.

## Configuracion de modelos

Cada agente puede usar un modelo diferente desde `.env`.

- `PLANNER_MODEL`
- `DIAGRAM_MODEL`
- `SUGGESTION_MODEL`
- `VALIDATION_MODEL`
- `CODEGEN_MODEL`
- `IMAGE_MODEL`

El archivo `app/config/agents_models.py` centraliza esa configuracion.
El archivo `app/providers/ai_provider.py` centraliza el proveedor de IA.

## Planner Agent

Responsabilidad:
- Convertir una solicitud del usuario en un plan ordenado.
- Leer contexto de proyecto o diagrama si se envia `proyecto_id` o `diagrama_id`.
- No ejecutar cambios todavia.

Validaciones:
- Mensaje no vacio.
- Acciones limitadas a tools conocidas.
- Acciones destructivas requieren confirmacion.
- Si falta informacion, devuelve preguntas y `can_execute=false`.

Salida:
- `intent`
- `summary`
- `actions`
- `questions`
- `can_execute`

## Diagram Agent

Responsabilidad:
- Ejecutar el plan aprobado usando endpoints del backend principal.

Validaciones:
- Token presente.
- El backend principal valida permisos.
- No modificar JSONB directamente.

## Image Agent

Responsabilidad:
- Leer imagenes PNG, JPEG o WebP de diagramas UML, ER o bocetos.
- Extraer clases/tablas, atributos, metodos, relaciones y multiplicidades.
- Comparar la extraccion con el diagrama actual y producir acciones ejecutables
  que el frontend aplica directamente a la pizarra.
- Reconocer una clase de asociacion como una tercera clase conectada por linea
  discontinua al centro de la asociacion principal, sin crear edges auxiliares.

Validaciones:
- Maximo 10 MB y firma binaria de imagen valida.
- Cardinalidades limitadas a `1`, `0..1`, `0..*` y `1..*`.
- Generalization no lleva cardinalidades.
- Aggregation y composition conservan multiplicidades en ambos extremos.
- En composition, `sourceCardinality` es `1` o `0..1` porque la Parte solo
  puede pertenecer a un Todo.
- Una cardinalidad ilegible en una relacion que la necesita genera una pregunta
  y esa relacion no se ejecuta automaticamente.
- Las relaciones deben apuntar a clases extraidas o existentes.
- El rol visualizador puede analizar, pero no ejecutar cambios.

Endpoint:
- `POST /ai/image/analyze` con `multipart/form-data`.

## Suggestion Agent

Responsabilidad futura:
- Sugerir mejoras al diagrama sin aplicarlas directamente.

## Validation Agent

Responsabilidad futura:
- Revisar calidad del modelo y detectar problemas de diseno.
- No reemplaza las validaciones deterministas del backend principal.

## Codegen Agent

Responsabilidad futura:
- Generar codigo desde el JSONB validado del diagrama.
- Debe trabajar sobre una copia/artefacto, no sobre la base directamente.
