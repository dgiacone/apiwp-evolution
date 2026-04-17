from typing import Any

import httpx

from app.config import Settings


class EvolutionAPIError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class EvolutionClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.evolution_base_url.rstrip("/")
        self._headers = {"apikey": settings.evolution_api_key}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(method, url, headers=self._headers, json=json)
        if response.is_error:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise EvolutionAPIError(response.status_code, detail)
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text

    async def fetch_instances(self) -> Any:
        return await self._request("GET", "/instance/fetchInstances")

    async def create_instance(
        self,
        instance_name: str,
        *,
        qrcode: bool = True,
        integration: str = "WHATSAPP-BAILEYS",
    ) -> Any:
        body = {
            "instanceName": instance_name,
            "qrcode": qrcode,
            "integration": integration,
        }
        return await self._request("POST", "/instance/create", json=body)

    async def connect(self, instance_name: str) -> Any:
        return await self._request("GET", f"/instance/connect/{instance_name}")

    async def connection_state(self, instance_name: str) -> Any:
        return await self._request("GET", f"/instance/connectionState/{instance_name}")

    async def logout(self, instance_name: str) -> Any:
        return await self._request("DELETE", f"/instance/logout/{instance_name}")

    async def delete_instance(self, instance_name: str) -> Any:
        return await self._request("DELETE", f"/instance/delete/{instance_name}")

    async def send_text(self, instance_name: str, number: str, text: str) -> Any:
        jid = _to_whatsapp_jid(number)
        body = {"number": jid, "textMessage": {"text": text}}
        return await self._request("POST", f"/message/sendText/{instance_name}", json=body)

    async def find_webhook(self, instance_name: str) -> Any:
        return await self._request("GET", f"/webhook/find/{instance_name}")

    async def set_webhook(
        self,
        instance_name: str,
        url: str,
        *,
        events: list[str] | None = None,
        webhook_by_events: bool = False,
        webhook_base64: bool = False,
    ) -> Any:
        ev = events or [
            "MESSAGES_UPSERT",
            "MESSAGES_UPDATE",
            "CONNECTION_UPDATE",
            "QRCODE_UPDATED",
        ]
        body: dict[str, Any] = {
            "url": url,
            "webhook_by_events": webhook_by_events,
            "webhook_base64": webhook_base64,
            "events": ev,
        }
        return await self._request("POST", f"/webhook/set/{instance_name}", json=body)


def _to_whatsapp_jid(number: str) -> str:
    n = number.strip()
    if "@" in n:
        return n
    digits = "".join(c for c in n if c.isdigit())
    return f"{digits}@s.whatsapp.net"
