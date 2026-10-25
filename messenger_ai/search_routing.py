"""Fast local intent rules and the protocol for model-requested web verification."""

from __future__ import annotations

import re
import unicodedata

SEARCH_REQUEST = "[[NEED_SEARCH]]"
SEARCH_REQUEST_PROMPT = (
    "\nCHỌN TRA CỨU KHI CẦN\n"
    "Hệ thống có model khác được phép tra cứu web. Bạn quyết định theo ý nghĩa câu hỏi "
    "và ngữ cảnh, không chỉ từ khóa. Nếu cần xác minh thông tin công khai mà bạn không "
    "biết chắc, thông tin có thể thay đổi, giá/mua bán, dịch vụ/địa điểm, lịch, tin tức, "
    "sản phẩm, phần mềm, quy định, hoặc người nhắn yêu cầu tìm/kiểm tra lại, "
    f"chỉ trả đúng {SEARCH_REQUEST}, không kèm câu trả lời hay giải thích. "
    "Hệ thống sẽ chuyển câu hỏi và ngữ cảnh sang model có Search. Đừng từ chối bằng câu "
    "'không có công cụ tra cứu' khi có thể yêu cầu chuyển này. "
    "Thông tin mới cần kiểm chứng không được thay bằng một câu trả lời đoán mò. "
    "Lời chào, cảm thán như 'thế à', chuyện riêng, cảm xúc, lời rủ, tính toán, "
    "dịch/viết lại văn bản và kiến thức ổn định đã biết thì trả lời bình thường. "
    "Ngày giờ hiện tại đã có trong chỉ dẫn thời gian, không cần Search. "
    "Không tra cứu việc riêng của chủ tài khoản, không đưa dữ liệu riêng vào truy vấn; "
    "tuân thủ khi người nhắn không muốn tìm trên mạng."
)


def normalized(text: str) -> str:
    text = re.sub(r"\bđừng\b", "khong", text[:2000].casefold())
    text = unicodedata.normalize("NFKD", text.replace("đ", "d"))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"\b(?:hnay|hom nai)\b", "hom nay", text)
    text = re.sub(r"\b(?:thoi tit|thoitiet)\b", "thoi tiet", text)
    text = re.sub(r"\b(?:nhiu|nhju)\b", "nhieu", text)
    return re.sub(r"\s+", " ", text).strip()


NO_SEARCH = re.compile(
    r"\b(?:khong|ko|k|khoi)(?:\s+can)?\s+(?:(?:su dung|dung)\s+)?"
    r"(?:tra(?: cuu)?|tim(?: kiem)?|search|google|len mang)\b"
    r"|\b(?:do not|don't|dont|no) (?:web )?search\b"
)
EXPLICIT_SEARCH = re.compile(
    r"\b(?:tra cuu|tra google|tra tren mang|tim kiem|tim tren (?:mang|web)|"
    r"tim (?:giup|ho).{0,40}tren mang|tim thu(?: xem)?|tra thu|tim xem|"
    r"len (?:google|mang) (?:tra|tim|xem)|"
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
    r"\b(?:(?<!tac )(?<!danh )(?<!chuyen )(?<!quoc )(?<!nguoi )"
    r"gia(?! (?:dinh|tri|su|nhu|tao)\b)|phi|price|pricing|cost)\b.{0,100}"
    r"\b(?:bao nhieu|bn|bnh|nhieu|hom nay|hien tai|bay gio|nay|now|today)\b"
    r"|\b(?:iphone|samsung|macbook|laptop|vps|api|model|mo hinh|goi|token)\b"
    r".{0,100}\b(?:bao nhieu|bn|free|mien phi|han muc|quota|limit|gia)\b"
    r"|\b(?:usd|eur|cny|nhan dan te|te|btc)\b.{0,60}\b(?:bao nhieu|bang|doi|sang)\b"
    r"|\b(?:binh (?:ga|gas)|gas|xang|dien|iphone|dien thoai|laptop|ve tau|ve xe|"
    r"ve may bay|sim|goi cuoc)\b.{0,100}\b(?:bao nhieu|bn|bnh|nhieu|may tien|gia)\b"
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
ACKNOWLEDGEMENT = re.compile(
    r"(?:a|ah|o|oh|uh|u|uhu|uhm|uk|ukm|um|vang|da|ok|oke|okay|oki|"
    r"cam on(?: ban)?|thanks|biet roi|hieu roi|dung roi|ra vay|the|vay)"
    r"(?: (?:a|ah|ha|ho|he|o|oh|uh|u|uk|um|vang|da|ok|oke|okay|oki|the|vay|"
    r"roi|thoi|nua|nhi|nhe|nha|b|ban|cam on|biet roi|hieu roi|dung roi))*"
)
FOLLOWUP_FILLER = set(
    "con the vay thi sao a ah ha nhi nhe nha b ban minh to tui toi em anh cau roi thoi nua".split()
)
SOCIAL_FOLLOWUP = re.compile(
    r"\b(?:di (?:choi|choei|an|ngu)|cho (?:ti|chut)|doi (?:ti|chut)|"
    r"de (?:minh|to)|tu tu|nhan tin|goi (?:minh|to)|co ranh|co ban|"
    r"ranh (?:khong|ko|k)|ban (?:khong|ko)|an (?:chua|com chua)|ngu chua|"
    r"(?:cho|gui) (?:minh|to|tui|toi|em|anh|ban|b) (?:xin )?(?:anh|hinh|sdt)|"
    r"co nen|nen (?:mac|mang|cam|dem)|"
    r"(?:minh|to|tui|toi|em|anh|cau|ban|b) (?:buon|vui|chan|met|doi|"
    r"dang|lam gi|di dau|thi di|thay|cam thay|(?:khong|ko|k) (?:thich|biet|hieu|muon)))\b"
)
CURRENT_CLOCK = re.compile(
    r"^(?:(?:the|vay|cho hoi|b|ban) )*(?:hom nay|nay|bay gio|gio|hien tai) "
    r"(?:la )?(?:(?:ngay|thu) (?:may|gi|bao nhieu)|may gio|ngay may thang may)"
    r"(?: (?:roi|the|vay|a|nhi|b|ban))*[?!. ]*$"
)


def acknowledgement(text: str) -> bool:
    return bool(ACKNOWLEDGEMENT.fullmatch(" ".join(re.findall(r"[a-z0-9]+", text))))


def followup(text: str) -> bool:
    if len(text) > 160 or acknowledgement(text) or SOCIAL_FOLLOWUP.search(text):
        return False
    words = re.findall(r"[a-z0-9]+", text)
    # An acknowledgement may precede a real question: "thế à, còn ngày mai?".
    for count in range(min(4, len(words) - 1), 0, -1):
        rest = " ".join(words[count:])
        if ACKNOWLEDGEMENT.fullmatch(" ".join(words[:count])) and FOLLOWUP.search(rest):
            words = words[count:]
            break
    if not FOLLOWUP.search(" ".join(words)):
        return False
    return any(word not in FOLLOWUP_FILLER for word in words)


def direct_search(text: str) -> bool:
    if NO_SEARCH.search(text) or CURRENT_CLOCK.fullmatch(text):
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
    if (
        NO_SEARCH.search(latest)
        or acknowledgement(latest)
        or CURRENT_CLOCK.fullmatch(latest)
    ):
        return False
    if direct_search(latest):
        return True
    if PRIVATE_CHAT.search(latest) or not followup(latest):
        return False
    for previous in reversed(recent[:-1]):
        if NO_SEARCH.search(previous):
            return False
        if direct_search(previous):
            return True
        if followup(previous) or acknowledgement(previous):
            continue
        break
    return False


def can_request_search(history: list[dict[str, str]]) -> bool:
    """Allow semantic judgment for new public questions, never a pure reaction."""
    if not history or history[-1].get("role") != "user":
        return False
    content = history[-1].get("content")
    if not isinstance(content, str):
        return False
    text = normalized(content)
    return bool(text) and not (
        acknowledgement(text)
        or NO_SEARCH.search(text)
        or PRIVATE_CHAT.search(text)
        or SOCIAL_FOLLOWUP.search(text)
        or CURRENT_CLOCK.fullmatch(text)
    )
