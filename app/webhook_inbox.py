from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

_MAX = 200
_HITS = 50
_lock = threading.Lock()
_items: deque[dict[str, Any]] = deque(maxlen=_MAX)
_webhook_hits: deque[dict[str, Any]] = deque(maxlen=_HITS)


def clear_inbox() -> None:
    with _lock:
        _items.clear()
        _webhook_hits.clear()


def list_inbox(*, limit: int = 50, instance: str | None = None) -> list[dict[str, Any]]:
    lim = max(1, min(limit, _MAX))
    with _lock:
        rows = list(_items)
        hits = list(_webhook_hits)
    if instance:
        inst = instance.strip().lower()
        rows = [r for r in rows if (r.get("instance") or "").lower() == inst]
    return rows[:lim]


def list_webhook_hits(*, limit: int = 25) -> list[dict[str, Any]]:
    lim = max(1, min(limit, _HITS))
    with _lock:
        return list(_webhook_hits)[:lim]


def log_webhook_received(
    *,
    payload: Any,
    raw_len: int,
    added_messages: int,
    parse_note: str | None = None,
) -> None:
    event = ""
    instance = ""
    keys: list[str] = []
    if isinstance(payload, dict):
        event = str(payload.get("event") or payload.get("type") or payload.get("action") or "")
        instance = str(payload.get("instance") or payload.get("instanceName") or "")
        keys = list(payload.keys())[:20]
    hint = parse_note or ""
    if not hint and added_messages == 0 and isinstance(payload, dict):
        evn = _normalize_event(event)
        if not keys:
            hint = "JSON sin claves reconocibles"
        elif "messages.upsert" not in evn and "messages.update" not in evn and "send.message" not in evn:
            hint = "Si esperabas un mensaje, el evento no coincide con MESSAGES_UPSERT; revisá la config del webhook"

    row = {
        "ts": time.time(),
        "added_messages": added_messages,
        "event": event,
        "instance": instance,
        "payload_keys": keys,
        "raw_bytes": raw_len,
        "hint": hint,
    }
    with _lock:
        _webhook_hits.appendleft(row)


def _text_from_message(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    if "conversation" in message:
        return str(message.get("conversation") or "")
    et = message.get("extendedTextMessage")
    if isinstance(et, dict) and et.get("text"):
        return str(et["text"])
    img = message.get("imageMessage")
    if isinstance(img, dict):
        cap = img.get("caption")
        return str(cap) if cap else "[imagen]"
    vid = message.get("videoMessage")
    if isinstance(vid, dict):
        cap = vid.get("caption")
        return str(cap) if cap else "[video]"
    if message.get("audioMessage"):
        return "[audio]"
    if message.get("stickerMessage"):
        return "[sticker]"
    if message.get("documentMessage"):
        return "[documento]"
    if message.get("contactMessage"):
        return "[contacto]"
    return ""


def _append_incoming(instance: str, row: dict[str, Any]) -> None:
    entry = {
        "ts": time.time(),
        "instance": instance,
        **row,
    }
    with _lock:
        _items.appendleft(entry)


def _normalize_event(name: Any) -> str:
    return str(name or "").replace("_", ".").lower()


def _is_outgoing(key: dict[str, Any]) -> bool:
    v = key.get("fromMe")
    if v is True:
        return True
    if isinstance(v, str) and v.lower() == "true":
        return True
    if v == 1:
        return True
    return False


def _payload_data(payload: dict[str, Any]) -> Any:
    if "data" in payload and payload.get("data") is not None:
        return payload.get("data")
    if "body" in payload and payload.get("body") is not None:
        return payload.get("body")
    return None


def _iter_message_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    if isinstance(payload.get("key"), dict) and (
        "message" in payload or payload.get("messageStubType") is not None
    ):
        out.append(payload)

    data = _payload_data(payload)

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                out.append(item)
        return out

    if not isinstance(data, dict):
        return out

    if "messages" in data and isinstance(data["messages"], list):
        for item in data["messages"]:
            if isinstance(item, dict):
                out.append(item)
        return out

    if "key" in data:
        out.append(data)
        return out

    for k in ("messages", "message", "content"):
        sub = data.get(k)
        if isinstance(sub, list):
            for item in sub:
                if isinstance(item, dict) and isinstance(item.get("key"), dict):
                    out.append(item)
        elif isinstance(sub, dict) and isinstance(sub.get("key"), dict):
            out.append(sub)

    return out


def _is_likely_message_webhook_event(event_norm: str) -> bool:
    if not event_norm:
        return True
    if "messages.upsert" in event_norm:
        return True
    if "send.message" in event_norm:
        return True
    if event_norm.endswith(".upsert") and "message" in event_norm:
        return True
    return False


def ingest_evolution_webhook(payload: dict[str, Any]) -> int:
    """
    Extrae mensajes entrantes (fromMe falso) del JSON del webhook.
    """
    event = _normalize_event(
        payload.get("event") or payload.get("type") or payload.get("action"),
    )
    nodes = _iter_message_nodes(payload)
    if not nodes:
        return 0
    if event and not _is_likely_message_webhook_event(event):
        if not any(isinstance(n.get("message"), dict) for n in nodes):
            return 0

    instance = str(payload.get("instance") or payload.get("instanceName") or "")
    count = 0
    for node in nodes:
        key = node.get("key")
        if not isinstance(key, dict):
            continue
        if _is_outgoing(key):
            continue
        remote = str(key.get("remoteJid") or "")
        if remote.endswith("@g.us"):
            chat_type = "grupo"
        elif "@s.whatsapp.net" in remote or remote.endswith("@lid"):
            chat_type = "privado"
        else:
            chat_type = "otro"

        message = node.get("message")
        text = _text_from_message(message)
        push = node.get("pushName")
        ts = node.get("messageTimestamp") or node.get("timestamp")

        reply_quote = False
        if isinstance(message, dict):
            ext = message.get("extendedTextMessage")
            if isinstance(ext, dict):
                ctx = ext.get("contextInfo")
                if isinstance(ctx, dict) and ctx.get("quotedMessage"):
                    reply_quote = True

        _append_incoming(
            instance,
            {
                "from_jid": remote,
                "chat_type": chat_type,
                "push_name": push,
                "text": text or "[sin texto parseado]",
                "message_id": key.get("id"),
                "wa_timestamp": ts,
                "is_reply_to_prior": reply_quote,
            },
        )
        count += 1
    return count
