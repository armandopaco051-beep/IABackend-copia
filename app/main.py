import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from app.services.chat_orchestrator import run_chat
from app.agents.local.interpreter import LocalInferenceError
from app.routers.local_worker import router as local_worker_router
from app.services.worker_relay import WorkerRelayError
from app.config.agents_models import get_agent_model_name, select_text_provider
from app.config.settings import settings
from app.schemas.chat import ChatRequest, ChatResponse, PlannerRequest, PlannerResponse, PlannerApiResponse
from app.services.backend_client import get_diagrama, get_proyecto, get_permisos_usuario
from app.services.backend_client import get_contexto_chat
from app.services.rbac_guard import verify_user_permission

from app.agents.diagram_agent import execute_plan
from app.schemas.diagram_execution import DiagramExecutePlanRequest, DiagramExecutePlanResponse

from fastapi.responses import FileResponse

from app.schemas.codegen import CodegenRequest, CodegenResponse
from app.services.codegen_storage import get_generated_zip_path, save_generated_project
from app.services.spring_boot_builder import build_spring_boot_project

from app.agents.suggestion_agent import run_suggestion
from app.schemas.suggestion import SuggestionRequest, SuggestionResponse

from app.agents.validation_agent import run_validation
from app.agents.image_agent import detect_image_mime, run_image_agent
from app.schemas.image_diagram import ImageDiagramResponse
from app.schemas.validation import ValidationRequest, ValidationResponse
app = FastAPI(
    title="DrawSchema AI Service",
    version="1.0.0",
)

app.include_router(local_worker_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://frontend-copia-software.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def extract_token(authorization: str | None):
    if not authorization:
        return None

    if authorization.lower().startswith("bearer "):
        return authorization[7:]

    return authorization


async def build_context(
    proyecto_id: int | None,
    diagrama_id: int | None,
    token: str | None,
):
    context = {}

    try:
        if proyecto_id is not None:
            context["proyecto"] = await get_proyecto(proyecto_id, token)
            permiso_info = await get_permisos_usuario(proyecto_id, token)
            context["user_role"] = permiso_info.get("rol", "EDITOR")

        if diagrama_id is not None:
            context["diagrama"] = await get_diagrama(diagrama_id, token)

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code

        try:
            detail = exc.response.json().get("detail", "No se pudo leer el contexto")
        except Exception:
            detail = "No se pudo leer el contexto"

        raise HTTPException(status_code=status_code, detail=detail) from exc

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="No se pudo conectar con el backend principal",
        ) from exc

    return context


@app.get("/")
def inicio():
    return {
        "mensaje": "DrawSchema AI funcionando correctamente",
    }


@app.get("/health")
def health():
    return {
        "estado": "ok",
        "servicio": "DrawSchemaAI",
        "backend_principal": settings.BACKEND_API_URL,
        "proveedor": settings.AI_PROVIDER,
        "proveedores_texto": ["gemini", "local"],
        "modelo_texto_local": settings.OLLAMA_MODEL,
        "proveedor_imagenes": "gemini",
        "modelo_planner": get_agent_model_name("planner"),
        "modelo_diagram": get_agent_model_name("diagram"),
        "modelo_suggestion": get_agent_model_name("suggestion"),
        "modelo_validation": get_agent_model_name("validation"),
        "modelo_codegen": get_agent_model_name("codegen"),
        "modelo_image": get_agent_model_name("image"),
    }


@app.post("/ai/image/analyze", response_model=ImageDiagramResponse)
async def analyze_diagram_image(
    image: UploadFile = File(...),
    proyecto_id: int = Form(...),
    diagrama_id: int = Form(...),
    message: str = Form(default="Extrae el diagrama respetando sus multiplicidades"),
    authorization: str | None = Header(default=None),
):
    token = extract_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token requerido para analizar una imagen del proyecto",
        )

    image_bytes = await image.read(settings.IMAGE_MAX_BYTES + 1)
    await image.close()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="La imagen esta vacia")
    if len(image_bytes) > settings.IMAGE_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"La imagen supera el limite de {settings.IMAGE_MAX_BYTES} bytes",
        )

    try:
        mime_type = detect_image_mime(image_bytes, image.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    context = await build_context(proyecto_id, diagrama_id, token)
    diagram_project_id = (context.get("diagrama") or {}).get("id_proyecto")
    if diagram_project_id != proyecto_id:
        raise HTTPException(
            status_code=400,
            detail="El diagrama indicado no pertenece al proyecto",
        )

    try:
        return await run_image_agent(
            image_bytes=image_bytes,
            mime_type=mime_type,
            message=message,
            context=context,
            filename=image.filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error del proveedor IA al analizar la imagen: {exc}",
        ) from exc


@app.post("/ai/chat", response_model=ChatResponse)
async def chat(datos: ChatRequest):
    return ChatResponse(
        respuesta=f"Recibi tu mensaje: {datos.message}",
        actions=[],
    )


# Endpoint para el planner
@app.post("/ai/planner", response_model=PlannerApiResponse)
async def planner(
    datos: PlannerRequest,
    authorization: str | None = Header(default=None),
):
    token = extract_token(authorization)
    context = await build_context(datos.proyecto_id, datos.diagrama_id, token)

    if datos.conversacion_id is not None:
        try:
            conversation = await get_contexto_chat(datos.conversacion_id, token, datos.mensaje_id)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, "No tienes acceso a esta conversación") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(503, "No se pudo cargar el historial") from exc
        if conversation.get("proyecto_id") != datos.proyecto_id:
            raise HTTPException(400, "La conversación no pertenece al proyecto")
        requester = conversation.get("solicitante") or {}
        current_question = conversation.get("consulta_actual")
        if datos.mensaje_id is not None:
            if not current_question or current_question.get("id") != datos.mensaje_id:
                raise HTTPException(400, "No se pudo identificar la consulta original")
            if current_question.get("autor_codigo") != requester.get("codigo"):
                raise HTTPException(403, "La consulta pertenece a otro participante")
            if current_question.get("diagrama_id") != datos.diagrama_id:
                raise HTTPException(400, "El diagrama no coincide con la consulta original")
            datos = datos.model_copy(update={"message": current_question["texto"]})
        context["conversacion"] = conversation
        # History is conversational evidence, never the current diagram state.
        context["conversacion"] = {
            **conversation,
            "mensajes": [m for m in conversation.get("mensajes", [])
                         if m.get("diagrama_id") == datos.diagrama_id],
        }
        context["solicitante"] = requester
        context["consulta_actual"] = current_question
    if datos.diagrama_id is not None and datos.proyecto_id is not None:
        if (context.get("diagrama") or {}).get("id") != datos.diagrama_id:
            raise HTTPException(400, "El backend devolvió un diagrama diferente del solicitado")
        if (context.get("diagrama") or {}).get("id_proyecto") != datos.proyecto_id:
            raise HTTPException(400, "El diagrama no pertenece al proyecto")
    diagram = context.get("diagrama") or {}
    context["diagrama_activo"] = {
        "id": diagram.get("id"), "nombre": diagram.get("nombre"),
        "version": diagram.get("version"),
        "fuente": "diagrama guardado obtenido del backend para esta consulta",
    }

    try:
        with select_text_provider(datos.text_provider):
            plan = await run_chat(datos.message, context)
            return PlannerApiResponse(
                **plan.model_dump(), provider=datos.text_provider,
                model=get_agent_model_name("planner"),
            )
    except WorkerRelayError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc)}) from exc
    except LocalInferenceError as exc:
        raise HTTPException(status_code=502, detail={"code": exc.code, "message": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error del proveedor IA: {exc}",
        ) from exc


# Endpoint para ejecutar un plan de diagrama
@app.post("/ai/diagram/execute-plan", response_model=DiagramExecutePlanResponse)
async def execute_diagram_plan(
    datos: DiagramExecutePlanRequest,
    authorization: str | None = Header(default=None),
):
    token = extract_token(authorization)
    return await execute_plan(datos, token)


@app.post("/ai/suggestions", response_model=SuggestionResponse)
async def suggestions(
    datos: SuggestionRequest,
    authorization: str | None = Header(default=None),
):
    token = extract_token(authorization)
    context = await build_context(datos.proyecto_id, datos.diagrama_id, token)

    try:
        return await run_suggestion(datos.message, context)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error del proveedor IA: {exc}",
        ) from exc


@app.post("/ai/validation", response_model=ValidationResponse)
async def validation(
    datos: ValidationRequest,
    authorization: str | None = Header(default=None),
):
    token = extract_token(authorization)
    context = await build_context(datos.proyecto_id, datos.diagrama_id, token)

    try:
        return await run_validation(datos.message, context)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error del proveedor IA: {exc}",
        ) from exc


@app.post("/ai/codegen", response_model=CodegenResponse)
async def codegen(
    datos: CodegenRequest,
    authorization: str | None = Header(default=None),
):
    token = extract_token(authorization)

    if datos.proyecto_id is not None:
        try:
            await verify_user_permission(datos.proyecto_id, token, min_role="EDITOR")
        except httpx.TimeoutException as exc:
            raise HTTPException(504, "El backend principal tardó demasiado al verificar los permisos. Reintenta la generación.") from exc
        except httpx.HTTPStatusError as exc:
            upstream_status = exc.response.status_code
            if upstream_status in {401, 403, 404}:
                raise HTTPException(upstream_status, "No se pudo verificar tu acceso al proyecto.") from exc
            raise HTTPException(502, "El backend principal no pudo verificar los permisos del proyecto.") from exc
        except httpx.RequestError as exc:
            raise HTTPException(503, "No se pudo conectar con el backend principal para verificar los permisos.") from exc

    context = await build_context(datos.proyecto_id, datos.diagrama_id, token)


    try:
        files, warnings = build_spring_boot_project(
            context=context,
            project_name=datos.project_name,
            base_package=datos.base_package,
            database_name=datos.database_name,
        )

        generation_id, _zip_path = save_generated_project(
            project_name=datos.project_name,
            files=files,
        )

        return CodegenResponse(
            success=True,
            summary=(
                f"Backend Spring Boot '{datos.project_name}' generado correctamente "
                f"con {len(files)} archivos."
            ),
            target=datos.target,
            project_name=datos.project_name,
            base_package=datos.base_package,
            database_name=datos.database_name,
            files=files,
            warnings=warnings,
            generation_id=generation_id,
            download_url=f"/ai/codegen/{generation_id}/download",
        )

    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error del proveedor IA: {exc}",
        ) from exc


@app.get("/ai/codegen/{generation_id}/download")
async def download_codegen(generation_id: str):
    zip_path = get_generated_zip_path(generation_id)

    if zip_path is None:
        raise HTTPException(status_code=404, detail="Proyecto generado no encontrado")

    return FileResponse(
        path=zip_path,
        filename=zip_path.name,
        media_type="application/zip",
    )
