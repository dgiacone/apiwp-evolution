from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any

_JSON_FALLBACK_MAX = 2000
_STRING_SNIFF_KEYS = frozenset(
    {
        "text",
        "caption",
        "title",
        "description",
        "displayText",
        "body",
        "name",
        "selectedDisplayText",
        "selectedRowId",
        "selectedButtonId",
        "inviteCode",
        "question",
        "matchedText",
        "notify",
        "contentText",
        "footer",
        "hydratedContentText",
        "address",
        "vcard",
    },
)

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


def _compact_json(obj: Any, limit: int = _JSON_FALLBACK_MAX) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except TypeError:
        s = str(obj)
    if len(s) > limit:
        return s[: limit - 3] + "..."
    return s


def _message_type_tags(message: dict[str, Any]) -> list[str]:
    tags = [k for k in message if isinstance(k, str) and k.endswith("Message")]
    if not tags:
        tags = [k for k in message if isinstance(k, str) and not k.startswith("_")]
    return tags[:24]


def _unwrap_inner_messages(msg: dict[str, Any]) -> dict[str, Any]:
    cur: Any = msg
    for _ in range(12):
        if not isinstance(cur, dict):
            return {}
        if any(
            k in cur
            for k in (
                "conversation",
                "extendedTextMessage",
                "imageMessage",
                "videoMessage",
                "audioMessage",
                "documentMessage",
                "stickerMessage",
                "contactMessage",
                "locationMessage",
                "liveLocationMessage",
                "reactionMessage",
                "pollCreationMessage",
                "listMessage",
                "buttonsMessage",
                "interactiveMessage",
                "templateMessage",
                "listResponseMessage",
                "buttonsResponseMessage",
            )
        ):
            return cur
        wrapped: dict[str, Any] | None = None
        for wrap in (
            "ephemeralMessage",
            "viewOnceMessage",
            "viewOnceMessageV2",
            "documentWithCaptionMessage",
        ):
            w = cur.get(wrap)
            if isinstance(w, dict):
                inner = w.get("message")
                wrapped = inner if isinstance(inner, dict) else w
                break
        if wrapped:
            cur = wrapped
            continue
        if "message" in cur and isinstance(cur["message"], dict):
            keys = set(cur.keys())
            if keys <= {"message", "messageContextInfo"} or keys == {"message"}:
                cur = cur["message"]
                continue
        return cur
    return cur if isinstance(cur, dict) else {}


def _sniff_strings(obj: Any, depth: int = 0, found: list[str] | None = None) -> list[str]:
    if found is None:
        found = []
    if depth > 6 or len(found) > 40:
        return found
    if isinstance(obj, str):
        t = obj.strip()
        if 0 < len(t) < 4000:
            found.append(t)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                continue
            if k in _STRING_SNIFF_KEYS:
                if isinstance(v, str) and v.strip():
                    found.append(f"{k}: {v.strip()}")
            elif isinstance(v, (dict, list)):
                _sniff_strings(v, depth + 1, found)
    elif isinstance(obj, list):
        for it in obj[:50]:
            _sniff_strings(it, depth + 1, found)
    return found


def _text_from_message(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    bubble = _unwrap_inner_messages(message)

    if "conversation" in bubble:
        return str(bubble.get("conversation") or "")
    et = bubble.get("extendedTextMessage")
    if isinstance(et, dict) and et.get("text"):
        return str(et["text"])
    img = bubble.get("imageMessage")
    if isinstance(img, dict):
        cap = img.get("caption")
        return str(cap) if cap else "[imagen]"
    vid = bubble.get("videoMessage")
    if isinstance(vid, dict):
        cap = vid.get("caption")
        return str(cap) if cap else "[video]"
    if bubble.get("audioMessage"):
        return "[audio]"
    if bubble.get("stickerMessage"):
        return "[sticker]"
    doc = bubble.get("documentMessage")
    if isinstance(doc, dict):
        fn = doc.get("fileName") or doc.get("title")
        cap = doc.get("caption")
        parts = [p for p in (cap, fn) if p]
        return " · ".join(str(p) for p in parts) if parts else "[documento]"
    c = bubble.get("contactMessage")
    if isinstance(c, dict):
        return str(c.get("displayName") or c.get("vcard") or "[contacto]")
    loc = bubble.get("locationMessage")
    if isinstance(loc, dict):
        bits = [
            str(loc.get("name") or ""),
            str(loc.get("address") or ""),
            f"{loc.get('degreesLatitude', '')},{loc.get('degreesLongitude', '')}",
        ]
        return " · ".join(b for b in bits if b) or "[ubicación]"
    ll = bubble.get("liveLocationMessage")
    if isinstance(ll, dict):
        cap = ll.get("caption")
        return str(cap) if cap else "[ubicación en vivo]"
    react = bubble.get("reactionMessage")
    if isinstance(react, dict) and react.get("text"):
        return f"[reacción] {react.get('text')}"
    poll = bubble.get("pollCreationMessage")
    if isinstance(poll, dict):
        name = poll.get("name") or ""
        opts = poll.get("options") or []
        opt_txt = ", ".join(str(o.get("optionName", o)) for o in opts[:12] if isinstance(o, dict))
        return " · ".join(p for p in (name, opt_txt) if p) or "[encuesta]"
    lst = bubble.get("listMessage")
    if isinstance(lst, dict):
        t = lst.get("title") or ""
        d = lst.get("description") or ""
        return " · ".join(p for p in (t, d) if p) or "[lista]"
    btns = bubble.get("buttonsMessage")
    if isinstance(btns, dict):
        ct = btns.get("contentText") or btns.get("text") or ""
        return str(ct) if ct else "[botones]"
    inter = bubble.get("interactiveMessage")
    if isinstance(inter, dict):
        body = inter.get("body")
        if isinstance(body, dict) and body.get("text"):
            return str(body["text"])
        hdr = inter.get("header")
        if isinstance(hdr, dict) and hdr.get("title"):
            return str(hdr["title"])
        return "[interactivo]"
    tmpl = bubble.get("templateMessage")
    if isinstance(tmpl, dict):
        hyd = tmpl.get("hydratedTemplate") or tmpl.get("hydratedFourRowTemplate")
        if isinstance(hyd, dict):
            for k in ("hydratedContentText", "hydratedTitleText", "title"):
                if hyd.get(k):
                    return str(hyd[k])
        return "[plantilla]"
    lresp = bubble.get("listResponseMessage")
    if isinstance(lresp, dict):
        sing = lresp.get("singleSelectReply") or {}
        if isinstance(sing, dict) and sing.get("selectedRowId"):
            return str(sing.get("selectedRowId"))
        if lresp.get("title"):
            return str(lresp["title"])
        return "[respuesta lista]"
    bresp = bubble.get("buttonsResponseMessage")
    if isinstance(bresp, dict):
        if bresp.get("selectedDisplayText"):
            return str(bresp["selectedDisplayText"])
        return "[respuesta botones]"

    sniffed = _sniff_strings(bubble)
    if sniffed:
        merged: list[str] = []
        for s in sniffed:
            if s not in merged:
                merged.append(s)
            if len(merged) >= 12:
                break
        return " | ".join(merged)

    tags = ", ".join(_message_type_tags(message)) or "desconocido"
    return f"[{tags}] {_compact_json(bubble)}"


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

        push = node.get("pushName")
        ts = node.get("messageTimestamp") or node.get("timestamp")
        message = node.get("message")
        wa_mt = str(node.get("messageType") or "")
        if isinstance(message, dict):
            text = _text_from_message(message)
            tags = _message_type_tags(message)
            reply_quote = False
            ext = message.get("extendedTextMessage")
            if isinstance(ext, dict):
                ctx = ext.get("contextInfo")
                if isinstance(ctx, dict) and ctx.get("quotedMessage"):
                    reply_quote = True
        else:
            stub = node.get("messageStubType")
            stub_params = node.get("messageStubParameters")
            text = (
                f"[stub/protocolo messageType={wa_mt or '?'} stubType={stub}] "
                f"{_compact_json({'stubType': stub, 'stubParameters': stub_params, 'rawMessage': message})}"
            )
            tags = []
            reply_quote = False

        _append_incoming(
            instance,
            {
                "from_jid": remote,
                "chat_type": chat_type,
                "push_name": push,
                "text": text,
                "message_tags": tags,
                "wa_message_type": wa_mt,
                "message_id": key.get("id"),
                "wa_timestamp": ts,
                "is_reply_to_prior": reply_quote,
            },
        )
        count += 1
    return count
