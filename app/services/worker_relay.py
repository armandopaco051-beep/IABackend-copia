"""Relay de inferencia por conexiones salientes WSS del PC; no escribe diagramas."""
import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import json
import time
from uuid import uuid4
from app.config.settings import settings

MAX_BYTES = 2 * 1024 * 1024
ALLOWED_PATHS = {"api/chat", "v1/chat/completions"}
ERRORS = {
    "LOCAL_UNAVAILABLE": "Ollama o el worker de tu PC no están disponibles.",
    "LOCAL_TIMEOUT": "Ollama local no respondió a tiempo.",
    "LOCAL_INVALID_RESPONSE": "Ollama local devolvió una respuesta inválida.",
}


class WorkerRelayError(RuntimeError):
    def __init__(self, message, code="LOCAL_UNAVAILABLE", status=503):
        super().__init__(message)
        self.code, self.status = code, status


def validate_payload(path, body):
    if path not in ALLOWED_PATHS or not isinstance(body, dict) or body.get("stream"):
        raise WorkerRelayError("Ruta o streaming no permitido para el worker", status=422)
    if str(body.get("model", settings.OLLAMA_MODEL)).removeprefix("openai/") != settings.OLLAMA_MODEL:
        raise WorkerRelayError("El worker debe usar el modelo local configurado", status=422)
    if len(json.dumps(body, ensure_ascii=False).encode()) > MAX_BYTES:
        raise WorkerRelayError("La consulta supera 2 MB", status=413)


@dataclass(eq=False)
class WorkerConnection:
    id: str
    model: str
    socket: object
    ready: bool
    connected: bool = True
    last_seen: float = field(default_factory=time.monotonic)
    waiting: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: dict = field(default_factory=dict)

    async def send(self, data):
        async with self.send_lock:
            await self.socket.send_json(data)


class WorkerRelay:
    def __init__(self):
        self.workers = {}

    async def register(self, connection):
        previous = self.workers.get(connection.id)
        if previous is not None:
            self.remove(previous)
            with suppress(Exception):
                await previous.socket.close(code=1000, reason="Worker reemplazado por una conexión nueva")
        self.workers[connection.id] = connection

    def remove(self, connection):
        connection.connected = False
        if self.workers.get(connection.id) is connection:
            del self.workers[connection.id]
        for future in tuple(connection.pending.values()):
            if not future.done():
                future.set_exception(WorkerRelayError("El worker se desconectó. La consulta sigue guardada; puedes reintentar."))

    def active(self, connection):
        return (connection.connected and connection.ready
                and time.monotonic() - connection.last_seen < settings.OLLAMA_WORKER_STALE_SECONDS)

    def status(self):
        return {"transport": settings.OLLAMA_TRANSPORT,
                "model": settings.OLLAMA_MODEL,
                "workers": [{"id": w.id, "model": w.model, "ready": self.active(w), "pending": w.waiting}
                            for w in self.workers.values()]}

    def receive(self, connection, message):
        connection.last_seen = time.monotonic()
        if message.get("type") == "heartbeat":
            if not isinstance(message.get("ready"), bool):
                raise WorkerRelayError("Heartbeat inválido", status=422)
            connection.ready = message["ready"]
            return
        if message.get("type") != "result":
            raise WorkerRelayError("Mensaje del worker no permitido", status=422)
        future = connection.pending.get(message.get("id"))
        if future is None or future.done():
            return  # Respuesta tardía de un trabajo que ya fue cancelado.
        if message.get("error"):
            code = message["error"] if message["error"] in ERRORS else "LOCAL_INVALID_RESPONSE"
            future.set_exception(WorkerRelayError(ERRORS[code], code, 502))
        elif isinstance(message.get("result"), dict):
            future.set_result(message["result"])
        else:
            future.set_exception(WorkerRelayError(ERRORS["LOCAL_INVALID_RESPONSE"], "LOCAL_INVALID_RESPONSE", 502))

    async def infer(self, path, body):
        validate_payload(path, body)
        available = [w for w in self.workers.values() if self.active(w) and w.model == settings.OLLAMA_MODEL]
        if not available:
            raise WorkerRelayError("No hay un worker local disponible. Enciende Ollama y ejecuta el worker en tu PC.")
        choices = [w for w in available if w.waiting < settings.OLLAMA_WORKER_MAX_PENDING]
        if not choices:
            raise WorkerRelayError("La cola de IA local está llena. Espera a que termine alguna consulta y reintenta.",
                                   "LOCAL_QUEUE_FULL", 429)
        connection = min(choices, key=lambda w: w.waiting)
        connection.waiting += 1
        request_id = str(uuid4())
        future, sent = None, False
        try:
            async with asyncio.timeout(max(1, settings.AI_REQUEST_TIMEOUT - 10)):
                async with connection.lock:
                    if not self.active(connection):
                        raise WorkerRelayError("El worker dejó de estar disponible; puedes reintentar.")
                    future = asyncio.get_running_loop().create_future()
                    connection.pending[request_id] = future
                    await connection.send({"type": "infer", "id": request_id, "path": path,
                                           "body": {**body, "model": settings.OLLAMA_MODEL, "stream": False}})
                    sent = True
                    return await future
        except TimeoutError as exc:
            raise WorkerRelayError("El worker local agotó el tiempo disponible; puedes reintentar.", "LOCAL_TIMEOUT", 504) from exc
        except (OSError, RuntimeError) as exc:
            if isinstance(exc, WorkerRelayError):
                raise
            raise WorkerRelayError("Se perdió la conexión con el worker local.") from exc
        finally:
            connection.waiting -= 1
            connection.pending.pop(request_id, None)
            if future is not None and not future.done():
                future.cancel()
            elif future is not None and not future.cancelled():
                future.exception()
            if sent and (future is None or future.cancelled()) and connection.connected:
                with suppress(Exception):
                    async with asyncio.timeout(2):
                        await connection.send({"type": "cancel", "id": request_id})


worker_relay = WorkerRelay()
