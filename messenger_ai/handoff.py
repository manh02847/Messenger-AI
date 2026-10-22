"""Recognize a small set of explicit stop requests, never model guesses."""

import re
import unicodedata

CLARIFY = "Mình chưa hiểu rõ ý bạn, bạn nói rõ hơn chút nhé?"


def requests_human(text: str) -> bool:
    normalized = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = " ".join(normalized.split())
    patterns = (
        r"(?:cho (?:minh|toi) |(?:minh|toi) muon )(?:gap|noi chuyen voi) manh",
        r"(?:de |cho )?manh (?:tu )?(?:tra loi|rep)",
        r"(?:dung|ngung|thoi) (?:tra loi|rep)(?: nua)?",
        r"(?:minh |toi )?khong muon (?:noi chuyen|chat) voi bot(?: nua)?",
        r"bot (?:dung|ngung|thoi) (?:tra loi|rep)(?: nua)?",
    )
    return any(
        re.fullmatch(pattern + r"(?: di| nhe| nha| nhe ban)?", normalized)
        for pattern in patterns
    )


def reply_text(text: str) -> str:
    # A mistaken control marker must never silence the conversation or be sent.
    return CLARIFY if "[[HANDOFF]]" in text else text
