"""A model chooses a reaction; a bounded header carries that decision internally."""

from dataclasses import dataclass
import re

# Accept old model headers and stored history while new replies choose Unicode directly.
EMOJI = {"like": "👍", "love": "❤", "haha": "😆", "wow": "😮", "sad": "😢"}
LABELS = {
    "like": "thích",
    "love": "tim",
    "haha": "vui",
    "wow": "ngạc nhiên",
    "sad": "buồn",
}
INSTRUCTION = """
ĐIỀU KHIỂN CẢM XÚC TIN NHẮN
Thả cảm xúc là thao tác được phép; yêu cầu không emoji chỉ áp dụng phần chữ.
Tự hiểu ngữ cảnh rồi chọn có thả cảm xúc vào tin mới nhất không. Không dựa chỉ vào từ khóa,
không thả mọi tin, không thả tim khi quan hệ/ý nghĩa chưa phù hợp, không dùng cảm xúc để
nhận lời, xác nhận giao dịch hoặc cam kết thay chủ tài khoản. Khi chưa chắc chọn none.
Tự chọn một emoji Unicode bất kỳ phù hợp sắc thái, không bị giới hạn vào danh sách có sẵn.
Chọn biểu tượng có ý nghĩa tự nhiên với người đang nhắn; tránh chế giễu hoặc công kích.
Mọi câu trả lời cuối có dòng đầu nội bộ dạng [[react:EMOJI]], thay EMOJI bằng đúng một
biểu tượng, ví dụ [[react:😂]], [[react:🫶]], [[react:🤔]]; hoặc [[react:none]] nếu không thả.
Emoji ghép, màu da, cờ đều được. Không dùng tên emoji, mã shortcode hay nhiều emoji rời.
Sau dòng điều khiển, xuống dòng và
viết câu trả lời tự nhiên không emoji theo persona. Dòng điều khiển không phải lời nhắn.
Nếu chỉ cần cảm xúc để xác nhận/kết chuyện, dùng [[react:👍:only]] (hoặc cảm xúc phù hợp)
và vẫn viết một câu dự phòng bên dưới; câu đó chỉ được gửi khi không thả được cảm xúc.
Nếu câu hỏi cần nội dung thì trả lời đầy đủ, không dùng :only để né câu hỏi.
Nếu hệ thống yêu cầu xuất mã điều phối tra cứu, xuất đúng mã đó, không thêm dòng react.
"""


def reaction_emoji(value: str) -> str:
    from emoji import is_emoji

    if not isinstance(value, str):
        raise ValueError("Cảm xúc cần đúng một emoji Unicode.")
    selected = EMOJI.get(value, value)
    if not 1 <= len(selected) <= 32 or not is_emoji(selected):
        raise ValueError("Cảm xúc cần đúng một emoji Unicode.")
    return selected


def reaction_label(value: str) -> str:
    return LABELS.get(value, value)


@dataclass(frozen=True)
class ReplyAction:
    text: str
    reaction: str | None = None
    reaction_only: bool = False


def instructions(enabled: bool) -> str:
    return INSTRUCTION if enabled else ""


def parse_reply(text: str, *, enabled: bool = True) -> ReplyAction:
    text = text.strip()
    if not text.startswith("[[react:"):
        return ReplyAction(text)
    first, separator, body = text.partition("\n")
    match = re.fullmatch(
        r"\[\[react:([^:\]\r\n]{1,32})(:only)?\]\]", first.strip()
    )
    if not match or not separator or not body.strip() or "[[react:" in body:
        raise ValueError("Phản hồi điều khiển cảm xúc chưa hợp lệ.")
    reaction = match[1] if match[1] != "none" else None
    if reaction is not None:
        reaction_emoji(reaction)
    if match[2] and reaction is None:
        raise ValueError("Phản hồi điều khiển cảm xúc chưa hợp lệ.")
    return ReplyAction(
        body.strip(), reaction if enabled else None, bool(match[2]) and enabled
    )
