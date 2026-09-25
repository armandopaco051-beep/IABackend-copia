import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from app.agents.planner_agent import run_planner
from app.config.agents_models import get_agent_model_name
from app.config.settings import settings
from app.schemas.chat import ChatRequest, ChatResponse, PlannerRequest, PlannerResponse
from app.services.backend_client import get_diagrama, get_proyecto, get_permisos_usuario
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
@app.post("/ai/planner", response_model=PlannerResponse)
async def planner(
    datos: PlannerRequest,
    authorization: str | None = Header(default=None),
):
    token = extract_token(authorization)
    context = await build_context(datos.proyecto_id, datos.diagrama_id, token)

    if datos.user_role:
        context["user_role"] = datos.user_role.upper()

    try:
        return await run_planner(datos.message, context)
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
        await verify_user_permission(datos.proyecto_id, token, min_role="EDITOR")

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
