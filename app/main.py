import json
import logging
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.evolution_client import EvolutionAPIError, EvolutionClient
from app.schemas import CreateInstanceBody, SendTextBody, SetWebhookBody
from app.webhook_inbox import (
    clear_inbox,
    ingest_evolution_webhook,
    list_inbox,
    list_webhook_hits,
    log_webhook_received,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="BotWP Admin", version="0.1.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.exception_handler(EvolutionAPIError)
async def evolution_api_error_handler(_request: Request, exc: EvolutionAPIError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def evolution_client(settings: Settings = Depends(get_settings)) -> EvolutionClient:
    if not settings.evolution_api_key:
        raise HTTPException(
            status_code=500,
            detail="Falta EVOLUTION_API_KEY en el entorno (.env)",
        )
    return EvolutionClient(settings)


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/admin", status_code=302)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
async def public_config(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {"webhook_public_url": settings.webhook_public_url or ""}


@app.get("/admin")
async def admin_page() -> FileResponse:
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Panel no encontrado")
    return FileResponse(index)


@app.get("/api/instances")
async def list_instances(client: EvolutionClient = Depends(evolution_client)) -> JSONResponse:
    data = await client.fetch_instances()
    return JSONResponse(content=data)


@app.post("/api/instances")
async def create_instance(
    body: CreateInstanceBody,
    client: EvolutionClient = Depends(evolution_client),
) -> JSONResponse:
    data = await client.create_instance(body.instance_name, qrcode=body.qrcode)
    return JSONResponse(content=data)


@app.delete("/api/instances/{instance_name}")
async def remove_instance(
    instance_name: str,
    client: EvolutionClient = Depends(evolution_client),
) -> JSONResponse:
    data = await client.delete_instance(instance_name)
    return JSONResponse(content=data)


@app.post("/api/instances/{instance_name}/logout")
async def logout_instance(
    instance_name: str,
    client: EvolutionClient = Depends(evolution_client),
) -> JSONResponse:
    data = await client.logout(instance_name)
    return JSONResponse(content=data)


@app.get("/api/instances/{instance_name}/connect")
async def connect_instance(
    instance_name: str,
    client: EvolutionClient = Depends(evolution_client),
) -> JSONResponse:
    data = await client.connect(instance_name)
    return JSONResponse(content=data)


@app.get("/api/instances/{instance_name}/state")
async def instance_state(
    instance_name: str,
    client: EvolutionClient = Depends(evolution_client),
) -> JSONResponse:
    data = await client.connection_state(instance_name)
    return JSONResponse(content=data)


@app.post("/api/instances/{instance_name}/send-text")
async def send_text(
    instance_name: str,
    body: SendTextBody,
    client: EvolutionClient = Depends(evolution_client),
) -> JSONResponse:
    data = await client.send_text(instance_name, body.number, body.text)
    return JSONResponse(content=data)


@app.get("/api/instances/{instance_name}/webhook")
async def get_instance_webhook(
    instance_name: str,
    client: EvolutionClient = Depends(evolution_client),
) -> JSONResponse:
    data = await client.find_webhook(instance_name)
    return JSONResponse(content=data)


@app.post("/api/instances/{instance_name}/webhook")
async def set_instance_webhook(
    instance_name: str,
    body: SetWebhookBody,
    settings: Settings = Depends(get_settings),
    client: EvolutionClient = Depends(evolution_client),
) -> JSONResponse:
    url = (body.url or "").strip() or settings.webhook_public_url.strip()
    if not url:
        raise HTTPException(
            status_code=400,
            detail="Indicá url en el cuerpo o definí WEBHOOK_PUBLIC_URL en .env",
        )
    data = await client.set_webhook(
        instance_name,
        url,
        events=body.events,
        webhook_by_events=body.webhook_by_events,
        webhook_base64=body.webhook_base64,
    )
    return JSONResponse(content=data)


@app.get("/api/inbox")
async def get_inbox(
    limit: int = 50,
    instance: str | None = None,
    hits_limit: int = 20,
) -> JSONResponse:
    hits = list_webhook_hits(limit=hits_limit)
    last_ts = hits[0]["ts"] if hits else None
    return JSONResponse(
        content={
            "items": list_inbox(limit=limit, instance=instance),
            "recent_webhooks": hits,
            "diagnostics": {
                "last_webhook_ts": last_ts,
                "tip_es": "Si recent_webhooks está vacío, ningún POST llegó a /webhook/evolution de este proceso "
                "(revisá URL en Evolution, túnel ngrok, o que el proxy apunte a este puerto).",
            },
        },
    )


@app.post("/api/debug/simulate-webhook")
async def simulate_webhook(body: dict[str, Any] = Body(...)) -> JSONResponse:
    """Prueba local: mismo parseo que POST /webhook/evolution sin pasar por Evolution."""
    added = ingest_evolution_webhook(body)
    log_webhook_received(
        payload=body,
        raw_len=0,
        added_messages=added,
        parse_note="Simulación vía POST /api/debug/simulate-webhook",
    )
    return JSONResponse(content={"added_messages": added})


@app.delete("/api/inbox")
async def wipe_inbox() -> dict[str, str]:
    clear_inbox()
    return {"ok": "true"}


@app.post("/webhook/evolution")
async def evolution_webhook(request: Request) -> dict[str, str]:
    raw = await request.body()
    raw_len = len(raw)
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        log_webhook_received(
            payload={"_error": "invalid_json"},
            raw_len=raw_len,
            added_messages=0,
            parse_note="Body no es JSON válido",
        )
        logger.warning("Webhook Evolution: JSON inválido (%s bytes)", raw_len)
        return {"ok": "true"}

    added = 0
    if isinstance(payload, dict):
        added = ingest_evolution_webhook(payload)
        log_webhook_received(payload=payload, raw_len=raw_len, added_messages=added)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                added += ingest_evolution_webhook(item)
        log_webhook_received(
            payload={"_root": "array", "_len": len(payload)},
            raw_len=raw_len,
            added_messages=added,
            parse_note="JSON raíz es array",
        )
    else:
        log_webhook_received(
            payload={"_type": type(payload).__name__},
            raw_len=raw_len,
            added_messages=0,
            parse_note="JSON raíz no es objeto ni lista",
        )

    if isinstance(payload, dict):
        logger.info(
            "Webhook Evolution (+%s mensajes): %s",
            added,
            json.dumps(payload, ensure_ascii=False)[:2000],
        )
    return {"ok": "true"}


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
