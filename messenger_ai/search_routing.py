"""Bounded, local search intent rules; no classifier request or persisted chat state."""

from __future__ import annotations

import re
import unicodedata


def normalized(text: str) -> str:
    text = re.sub(r"\bđừng\b", "khong", text[:2000].casefold())
    text = unicodedata.normalize("NFKD", text.replace("đ", "d"))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"\b(?:hnay|hom nai)\b", "hom nay", text)
    text = re.sub(r"\b(?:thoi tit|thoitiet)\b", "thoi tiet", text)
    return re.sub(r"\s+", " ", text).strip()


NO_SEARCH = re.compile(
    r"\b(?:khong|ko|k|khoi)(?:\s+can)?\s+(?:(?:su dung|dung)\s+)?"
    r"(?:tra(?: cuu)?|tim kiem|search|google|len mang)\b"
    r"|\b(?:do not|don't|dont|no) (?:web )?search\b"
)
EXPLICIT_SEARCH = re.compile(
    r"\b(?:tra cuu|tra google|tra tren mang|tim kiem|tim tren (?:mang|web)|"
    r"tim (?:giup|ho).{0,40}tren mang|len (?:google|mang) (?:tra|tim|xem)|"
    r"google (?:giup|ho|xem)|search|kiem chung|xac minh|fact check|"
    r"(?:dung|su dung) (?:google search|google)|"
    r"kiem tra (?:lai|thong tin)|nguon (?:dau|nao)|dan nguon|link nguon)\b"
)
PRIVATE_CHAT = re.compile(
    r"\b(?:ban|minh|cau|to|tui|anh|em)\s+"
    r"(?:dang lam gi|lam gi|o dau|an (?:chua|com chua)|ngu chua|co ranh|"
    r"co tin (?:gi|moi)|thich (?:ai|gi)|co thich|yeu (?:ai|minh|ban))\b"
    r"|\bdang lam gi\b"
    r"|\b(?:di choi|di choei|di an|gap nhau|hen nhau).{0,25}\b(?:khong|ko|k|nhe|nha)\b"
)
FRESHNESS = re.compile(
    r"\b(?:hom nay|ngay mai|hien tai|hien nay|bay gio|moi nhat|"
    r"moi ra mat|moi phat hanh|moi cong bo|tuan nay|thang nay|nam nay|"
    r"today|tomorrow|current|latest|recent|now)\b"
)
PUBLIC_TOPIC = re.compile(
    r"\b(?:thoi tiet|weather|forecast|du bao thoi tiet|nhiet do|bao nhieu do|may do|"
    r"co mua (?:khong|ko|k|chua)|troi (?:mua|nang)|"
    r"tin tuc|tin nong|thoi su|tin moi nhat|news|"
    r"gia vang|gia xang|gia dau|gia btc|gia bitcoin|ty gia|ti gia|exchange rate|"
    r"co phieu|chung khoan|lai suat|hoc phi|"
    r"lich (?:thi dau|chieu|bay|nghi le)|ket qua (?:tran|bong da|thi dau)|"
    r"ti so|ty so|chuyen bay|ve may bay|ve tau|"
    r"luat (?:moi|hien hanh)|quy dinh (?:moi|hien hanh)|muc phat|"
    r"lich am|hom nay (?:la ngay|ngay may))\b"
)
PRICE_QUESTION = re.compile(
    r"\b(?:gia(?! (?:dinh|tri|su|nhu)\b)|phi|price|pricing|cost)\b.{0,100}"
    r"\b(?:bao nhieu|bn|bnh|nhieu|hom nay|hien tai|bay gio|nay|now|today)\b"
    r"|\b(?:iphone|samsung|macbook|laptop|vps|api|model|mo hinh|goi|token)\b"
    r".{0,100}\b(?:bao nhieu|bn|free|mien phi|han muc|quota|limit|gia)\b"
    r"|\b(?:usd|eur|cny|nhan dan te|te|btc)\b.{0,60}\b(?:bao nhieu|bang|doi|sang)\b"
)
CURRENT_FACT = re.compile(
    r"\b(?:phien ban|model|mo hinh|ban cap nhat|python|ios|android|gemini|chatgpt)\b"
    r".{0,100}\bmoi nhat\b"
    r"|\bmoi nhat\b.{0,100}\b(?:phien ban|model|mo hinh)\b"
    r"|\b(?:moi ra mat|moi phat hanh|moi cong bo)\b"
    r"|\b(?:thu tuong|tong thong|bo truong|ceo)\b.{0,60}\b(?:ai|hien tai|hien nay)\b"
    r"|\b(?:hien tai|hien nay)\b.{0,60}\b(?:thu tuong|tong thong|bo truong|ceo)\b"
)
FOLLOWUP = re.compile(
    r"^(?:con|the|vay)\b"
    r"|^(?:hom nay|mai|ngay mai|ngay kia|tuan sau|thang sau|nam sau|"
    r"bao nhieu|khi nao|o dau|nguon dau|co link|link dau|co that|that khong)\b"
)
ACKNOWLEDGEMENT = re.compile(r"(?:ok|oke|okay|cam on(?: ban)?|thanks|uh|u|vang)[.!? ]*")


def direct_search(text: str) -> bool:
    if NO_SEARCH.search(text):
        return False
    if PRIVATE_CHAT.search(text) and not PUBLIC_TOPIC.search(text):
        return False
    if EXPLICIT_SEARCH.search(text):
        return True
    # Definitions can be answered from knowledge; freshness or an explicit search
    # request overrides this check (e.g. "tỷ giá hôm nay là gì?").
    if re.search(
        r"\b(?:la gi|nghia la gi|dinh nghia|khai niem)\b", text
    ) and not FRESHNESS.search(text):
        return False
    return bool(
        PUBLIC_TOPIC.search(text)
        or PRICE_QUESTION.search(text)
        or CURRENT_FACT.search(text)
    )


def needs_search(history: list[dict[str, str]]) -> bool:
    if not history or history[-1].get("role") != "user":
        return False
    recent = [
        normalized(item["content"])
        for item in history[-12:]
        if item.get("role") == "user" and isinstance(item.get("content"), str)
    ][-4:]
    if not recent:
        return False
    latest = recent[-1]
    if NO_SEARCH.search(latest):
        return False
    if direct_search(latest):
        return True
    if PRIVATE_CHAT.search(latest) or len(latest) > 160 or not FOLLOWUP.search(latest):
        return False
    for previous in reversed(recent[:-1]):
        if NO_SEARCH.search(previous):
            return False
        if direct_search(previous):
            return True
        if len(previous) <= 160 and (
            FOLLOWUP.search(previous) or ACKNOWLEDGEMENT.fullmatch(previous)
        ):
            continue
        break
    return False
