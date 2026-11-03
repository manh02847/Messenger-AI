"""Read only routing metadata from the pinned bridge's decryption-failure event."""

from dataclasses import dataclass, field
from datetime import datetime
import math
import re

from .core import Message, canonical_thread


@dataclass(frozen=True)
class DecryptNotice:
    source: str
    kind: str
    chat: str
    activity: Message | None = field(default=None, repr=False)


def _peer(jid: object) -> str:
    if not isinstance(jid, str) or len(jid) > 100:
        return ""
    match = re.fullmatch(r"([1-9][0-9]{0,24})(?:\.[0-9]+)?(?::[0-9]+)?@msgr", jid)
    return match[1] if match else ""


def undecryptable_notice(event: object, own_id: str) -> DecryptNotice | None:
    if not isinstance(event, dict) or event.get("type") != "raw":
        return None
    raw = event.get("data")
    if (
        not isinstance(raw, dict)
        or raw.get("from") != "whatsmeow"
        or raw.get("type") != "UndecryptableMessage"
    ):
        return None
    data = raw.get("data")
    data = data if isinstance(data, dict) else {}
    info = data.get("Info")
    info = info if isinstance(info, dict) else {}
    sender, chat = _peer(info.get("Sender")), _peer(info.get("Chat"))
    from_me = info.get("IsFromMe")
    source = (
        "self"
        if sender == own_id and bool(own_id) and from_me is True
        else "other"
        if sender and sender != own_id and from_me is False
        else "unknown"
    )
    unavailable = data.get("IsUnavailable")
    kind = (
        "missing_ciphertext"
        if unavailable is True
        else "decrypt_failed"
        if unavailable is False
        else "unknown"
    )
    group = info.get("IsGroup")
    chat_kind = (
        "group"
        if group is True
        else "private"
        if group is False and chat
        else "unknown"
    )
    notice = DecryptNotice(source, kind, chat_kind)
    if source != "self" or chat_kind != "private" or chat == own_id:
        return notice
    mid, timestamp = info.get("ID"), info.get("Timestamp")
    if (
        not isinstance(mid, str)
        or not 1 <= len(mid) <= 500
        or any(ord(c) < 32 for c in mid)
        or not isinstance(timestamp, str)
        or len(timestamp) > 64
    ):
        return notice
    try:
        date = datetime.fromisoformat(timestamp)
        if date.tzinfo is None:
            return notice
        seconds = date.timestamp()
        if not math.isfinite(seconds) or seconds <= 0:
            return notice
    except (ValueError, OverflowError, OSError):
        return notice
    activity = Message(
        canonical_thread("e2ee:" + info["Chat"]),
        mid,
        own_id,
        "",
        seconds,
        chat_jid=info["Chat"],
        sender_jid=info["Sender"],
        is_private=True,
        metadata_only=True,
    )
    return DecryptNotice(source, kind, chat_kind, activity)
