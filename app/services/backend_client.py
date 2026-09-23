import httpx

from app.config.settings import settings

#esta parte del archivo permita que el backend IA lea datos del backend principal
def build_headers(token: str | None = None):
    headers = {
        "Content-Type": "application/json",
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


async def get_diagrama(diagrama_id: int, token: str | None = None):
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{settings.BACKEND_API_URL}/diagramas/{diagrama_id}",
            headers=build_headers(token),
        )
        response.raise_for_status()
        return response.json()


async def get_proyecto(proyecto_id: int, token: str | None = None):
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{settings.BACKEND_API_URL}/proyectos/{proyecto_id}",
            headers=build_headers(token),
        )
        response.raise_for_status()
        return response.json()


async def get_permisos_usuario(proyecto_id: int, token: str | None = None):
    """Obtiene el rol real del backend principal; nunca eleva permisos por fallback."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{settings.BACKEND_API_URL}/proyectos/{proyecto_id}/permiso",
            headers=build_headers(token),
        )
        response.raise_for_status()
        return response.json()

async def create_class(diagrama_id: int, body: dict, token: str | None = None):
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{settings.BACKEND_API_URL}/diagramas/{diagrama_id}/clases",
            json=body,
            headers=build_headers(token),
        )
        response.raise_for_status()
        return response.json()


async def update_class(diagrama_id: int, clase_id: str, body: dict, token: str | None = None):
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.put(
            f"{settings.BACKEND_API_URL}/diagramas/{diagrama_id}/clases/{clase_id}",
            json=body,
            headers=build_headers(token),
        )
        response.raise_for_status()
        return response.json()


async def move_class(diagrama_id: int, clase_id: str, body: dict, token: str | None = None):
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.patch(
            f"{settings.BACKEND_API_URL}/diagramas/{diagrama_id}/clases/{clase_id}/mover",
            json=body,
            headers=build_headers(token),
        )
        response.raise_for_status()
        return response.json()


async def delete_class(
    diagrama_id: int,
    clase_id: str,
    autor_codigo: str | None = None,
    token: str | None = None,
):
    params = {}

    if autor_codigo:
        params["autor_codigo"] = autor_codigo

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.delete(
            f"{settings.BACKEND_API_URL}/diagramas/{diagrama_id}/clases/{clase_id}",
            params=params,
            headers=build_headers(token),
        )
        response.raise_for_status()
        return response.json()


async def create_relation(diagrama_id: int, body: dict, token: str | None = None):
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{settings.BACKEND_API_URL}/diagramas/{diagrama_id}/relaciones",
            json=body,
            headers=build_headers(token),
        )
        response.raise_for_status()
        return response.json()


async def update_relation(
    diagrama_id: int,
    relacion_id: str,
    body: dict,
    token: str | None = None,
):
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.put(
            f"{settings.BACKEND_API_URL}/diagramas/{diagrama_id}/relaciones/{relacion_id}",
            json=body,
            headers=build_headers(token),
        )
        response.raise_for_status()
        return response.json()


async def delete_relation(
    diagrama_id: int,
    relacion_id: str,
    autor_codigo: str | None = None,
    token: str | None = None,
):
    params = {}

    if autor_codigo:
        params["autor_codigo"] = autor_codigo

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.delete(
            f"{settings.BACKEND_API_URL}/diagramas/{diagrama_id}/relaciones/{relacion_id}",
            params=params,
            headers=build_headers(token),
        )
        response.raise_for_status()
        return response.json()
