from fastapi import HTTPException
from app.services.backend_client import get_permisos_usuario

ROLE_HIERARCHY = {
    "PROPIETARIO": 3,
    "ADMINISTRADOR": 3,
    "ADMIN": 3,
    "OWNER": 3,
    "EDITOR": 2,
    "DESIGNER": 2,
    "DISEÑADOR": 2,
    "VISUALIZADOR": 1,
    "VIEWER": 1,
}


def is_role_sufficient(user_role: str, min_required_role: str) -> bool:
    user_level = ROLE_HIERARCHY.get(user_role.upper(), 1)
    min_level = ROLE_HIERARCHY.get(min_required_role.upper(), 2)
    return user_level >= min_level


async def verify_user_permission(
    proyecto_id: int | None,
    token: str | None,
    min_role: str = "EDITOR",
) -> str:
    """
    Verifica que el usuario tenga el rol mínimo requerido para actuar sobre un proyecto.
    Retorna el nombre del rol en mayúsculas.
    Si el rol es insuficiente, lanza HTTPException 403 Forbidden.
    """
    if proyecto_id is None:
        return "EDITOR"

    if not token:
        raise HTTPException(status_code=401, detail="Token requerido")

    user_info = await get_permisos_usuario(proyecto_id, token)
    user_role = str(user_info.get("rol", "EDITOR")).upper()

    if not is_role_sufficient(user_role, min_role):
        raise HTTPException(
            status_code=403,
            detail=f"Permiso insuficiente. Tu rol en el proyecto es '{user_role}', pero se requiere al menos '{min_role}'.",
        )

    return user_role
