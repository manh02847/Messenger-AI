"""Interactive AI conversation with in-memory context and no Messenger transport."""

from time import monotonic

from .ai import AIError
from .context import recent_history
from .handoff import reply_text, requests_human


def bounded_history(history, settings):
    return recent_history(
        history, settings.history_messages, settings.history_char_limit
    )


async def chat_loop(ai, settings, reserve, *, read=input, write=print, clock=monotonic):
    history = []
    last_activity = None
    write(
        f"Nguồn AI: {getattr(ai, 'description', settings.model)}. Chỉ thử AI; không kết nối Messenger."
    )
    write("/reset: ngữ cảnh mới; /context: số tin gửi cho AI; /quit: thoát.")
    while True:
        try:
            text = read("Bạn: ").strip()
        except EOFError:
            return
        if text == "/quit":
            return
        if text == "/reset":
            history.clear()
            last_activity = None
            write("Đã bắt đầu ngữ cảnh mới.")
            continue
        if text == "/context":
            write(
                f"Ngữ cảnh: {len(history)} tin, {sum(len(m['content']) for m in history)} ký tự."
            )
            continue
        if not text:
            continue
        if requests_human(text):
            write("[Nếu trên Messenger: yêu cầu này sẽ tạm nhường cho Mạnh.]")
            continue
        now = clock()
        if (
            settings.history_idle_seconds
            and last_activity is not None
            and now - last_activity >= settings.history_idle_seconds
        ):
            history.clear()
            write("Đã bắt đầu ngữ cảnh mới sau thời gian không nhắn.")
        last_activity = now
        history.append({"role": "user", "content": text[: settings.input_char_limit]})
        history = bounded_history(history, settings)
        try:
            answer = reply_text(await ai.generate(history, reserve))
        except AIError as error:
            write(str(error))
            continue
        answer = settings.reply_prefix + answer.strip()[: settings.output_char_limit]
        write("AI: " + answer)
        history.append({"role": "assistant", "content": answer})
        history = bounded_history(history, settings)
        last_activity = clock()
