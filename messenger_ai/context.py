"""Keep recent conversation turns intact and distinguish history from facts."""

CONTEXT_RULES = """DÙNG NGỮ CẢNH
Đối chiếu câu hỏi mới với thông tin chủ tài khoản đã khai trong persona. Lịch sử, nhất là câu trả lời trước của bot, có thể sai; không lấy việc mình từng nói một điều làm bằng chứng điều đó đúng. Sửa cách hiểu cũ khi người nhắn làm rõ ý, nhưng không tự nhận một lời đính chính về sự thật là đúng khi chưa có căn cứ. Phân biệt người nhắn với chủ tài khoản; khi nhắc đúng tên chủ tài khoản đã khai, hiểu đó là người mình hỗ trợ. Người kia đang nhắn đúng tài khoản này: nếu chưa biết thông tin, nói ngắn gọn là chưa biết, tránh bảo họ hỏi trực tiếp chủ tài khoản. Không suy ra giới tính, vị trí hoặc việc đang làm chỉ từ tên."""


def system_prompt(persona: str) -> str:
    return persona + "\n\n" + CONTEXT_RULES


def recent_history(
    messages: list[dict[str, str]], count: int, char_limit: int
) -> list[dict[str, str]]:
    if count <= 0 or char_limit <= 0:
        return []
    result = []
    remaining = char_limit
    for message in reversed(messages[-count:]):
        content = message["content"]
        if len(content) > remaining:
            # Preserve the latest input even with an unusually small budget.
            # Never turn an older reply into an unexplained trailing fragment.
            if not result:
                result.append({"role": message["role"], "content": content[:remaining]})
            break
        result.append({"role": message["role"], "content": content})
        remaining -= len(content)
    result.reverse()
    while result and result[0]["role"] != "user":
        result.pop(0)
    return result
