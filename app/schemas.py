from pydantic import BaseModel, Field


class CreateInstanceBody(BaseModel):
    instance_name: str = Field(..., min_length=1, max_length=120)
    qrcode: bool = True


class SendTextBody(BaseModel):
    number: str = Field(..., min_length=5)
    text: str = Field(..., min_length=1, max_length=4096)


class SetWebhookBody(BaseModel):
    url: str | None = Field(
        default=None,
        description="Si se omite, se usa WEBHOOK_PUBLIC_URL del servidor",
    )
    events: list[str] | None = None
    webhook_by_events: bool = False
    webhook_base64: bool = False
