from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from .ai import AIError, ChatAI
from .config import Settings
from .context import recent_history
from .handoff import reply_text, requests_human
from .images import (
    IMAGE_FAILURE,
    MAX_IMAGES,
    ImageAttachment,
    ImageError,
    ImageInput,
    image_attachments,
)
from .state import State

VIETNAM = timezone(timedelta(hours=7))
TYPING_REFRESH_SECONDS = 4
TYPING_UPDATE_TIMEOUT = 2


@dataclass(frozen=True)
class Message:
    thread: str
    id: str
    sender_id: str
    text: str
    timestamp: float
    chat_jid: str = ""
    sender_jid: str = ""
    thread_id: int = 0
    is_private: bool = False
    thread_type: int = 1
    images: tuple[ImageAttachment, ...] = ()


def parse_event(event: object) -> Message | None:
    if not isinstance(event, dict) or event.get("type") not in (
        "message",
        "e2eeMessage",
    ):
        return None
    data = event.get("data")
    if not isinstance(data, dict) or data.get("isAdminMsg"):
        return None
    mid, sender = data.get("id"), data.get("senderId")
    timestamp = data.get("timestampMs")
    text = data.get("text", "")
    if (
        not isinstance(mid, str)
        or not mid
        or isinstance(sender, bool)
        or not str(sender).isdigit()
    ):
        return None
    if (
        not isinstance(timestamp, (int, float))
        or isinstance(timestamp, bool)
        or not isinstance(text, str)
    ):
        return None
    if event["type"] == "e2eeMessage":
        jid = data.get("chatJid")
        sender_jid = data.get("senderJid", "")
        if not isinstance(jid, str) or not re.fullmatch(
            r"[0-9][0-9A-Za-z:._-]*@[A-Za-z0-9._-]+", jid
        ):
            return None
        return Message(
            "e2ee:" + jid,
            mid,
            str(sender),
            text,
            timestamp / 1000,
            jid,
            sender_jid if isinstance(sender_jid, str) else "",
            is_private=bool(
                re.fullmatch(r"[1-9][0-9]*(?:\.[0-9]+)?(?::[0-9]+)?@msgr", jid)
            ),
            images=image_attachments(data.get("attachments")),
        )
    tid = data.get("threadId")
    if isinstance(tid, bool) or not str(tid).isdigit() or int(tid) <= 0:
        return None
    return Message(
        f"thread:{int(tid)}",
        mid,
        str(sender),
        text,
        timestamp / 1000,
        thread_id=int(tid),
        # mautrix-meta ThreadType values pinned by fbchat-v2 2.3.4.
        # Unknown, groups, channels and AI bots are deliberately excluded.
        is_private=type(data.get("threadType")) is int
        and data["threadType"] in (1, 7, 10, 13, 15),
        thread_type=data["threadType"]
        if type(data.get("threadType")) is int and data["threadType"] > 0
        else 1,
        images=image_attachments(data.get("attachments")),
    )


class AI(Protocol):
    async def generate(
        self, history: list[dict[str, str]], reserve: Callable[[], bool]
    ) -> str: ...


class Transport(Protocol):
    async def send(self, message: Message, text: str) -> dict[str, Any]: ...

    async def set_typing(self, message: Message, is_typing: bool) -> None: ...

    async def load_image(
        self, image: ImageAttachment, *, encrypted: bool
    ) -> ImageInput: ...


class ReplyBot:
    def __init__(
        self,
        settings: Settings,
        state: State,
        ai: AI,
        transport: Transport,
        own_id: str,
        *,
        clock: Callable[[], float] = time.time,
        log: Callable[[str], None] = print,
        image_ai: ChatAI | None = None,
    ):
        self.settings, self.state, self.ai, self.transport = (
            settings,
            state,
            ai,
            transport,
        )
        self.own_id, self.clock, self.log = own_id, clock, log
        self.started_at = clock()
        self.latest: dict[str, Message] = {}
        self.revisions: dict[str, int] = {}
        self.pending: set[str] = set()
        self.tasks: dict[str, asyncio.Task] = {}
        self.typing_tasks: dict[str, asyncio.Task] = {}
        self.closing = False
        self.image_ai = image_ai
        self.pending_images: dict[str, list[tuple[ImageAttachment, bool]]] = {}
        self.image_slots = asyncio.Semaphore(1)

    def _input_content(self, message: Message) -> str:
        content = message.text[: self.settings.input_char_limit]
        if message.images:
            content += (
                "\n[Người nhắn gửi ảnh đính kèm.]"
                if self.image_ai is not None
                else "\n[Ảnh đính kèm chưa được cung cấp cho AI vì chức năng đọc ảnh chưa bật.]"
            )
        return content.strip()

    def receive(self, message: Message) -> None:
        if self.closing:
            return
        now = self.clock()
        if self.settings.reply_scope == "all_private":
            if not message.is_private:
                return
        elif message.thread not in self.settings.allowed_threads:
            return
        if not (
            max(self.started_at - 2, now - self.settings.max_message_age_seconds)
            <= message.timestamp
            <= now + 30
        ):
            return
        if not self.state.claim(message.thread, message.id, now):
            return
        if message.sender_id == self.own_id:
            if self.state.bot_echo(message.thread, message.id, message.text, now):
                return
            self.revisions[message.thread] = self.revisions.get(message.thread, 0) + 1
            self.pending.discard(message.thread)
            self.pending_images.pop(message.thread, None)
            self.state.pause(message.thread, now + self.settings.manual_pause_seconds)
            self._cancel_typing(message.thread)
            if message.text.strip():
                self.state.remember(
                    message.thread,
                    "assistant",
                    message.text[: self.settings.input_char_limit],
                    now,
                    self.settings.history_messages,
                )
            self.log(
                "Bạn vừa nhắn thủ công: tạm dừng auto rep trong cuộc trò chuyện này."
            )
            return
        if not message.text.strip() and not (
            message.images and self.image_ai is not None
        ):
            if message.images:
                self.log(
                    "Nhận ảnh nhưng chưa bật nguồn đọc ảnh; bỏ qua tin chỉ có ảnh."
                )
            return
        self.state.remember(
            message.thread,
            "user",
            self._input_content(message),
            now,
            self.settings.history_messages,
        )
        if requests_human(message.text):
            self.revisions[message.thread] = self.revisions.get(message.thread, 0) + 1
            self.pending.discard(message.thread)
            self.pending_images.pop(message.thread, None)
            self.state.pause(message.thread, now + self.settings.manual_pause_seconds)
            self._cancel_typing(message.thread)
            self.log("Người nhắn yêu cầu dừng hoặc gặp Mạnh: tạm nhường trả lời.")
            return
        if self.state.paused(message.thread, now):
            return
        if message.images and self.image_ai is not None:
            queued = self.pending_images.setdefault(message.thread, [])
            queued.extend((image, bool(message.chat_jid)) for image in message.images)
            self.pending_images[message.thread] = queued[-MAX_IMAGES:]
        self.latest[message.thread] = message
        self.revisions[message.thread] = self.revisions.get(message.thread, 0) + 1
        self.pending.add(message.thread)
        if message.thread not in self.tasks or self.tasks[message.thread].done():
            self.tasks[message.thread] = asyncio.create_task(
                self._worker(message.thread)
            )

    def _may_send(self, thread: str) -> bool:
        now = self.clock()
        return (
            thread in self.pending
            and not self.state.paused(thread, now)
            and now - self.latest[thread].timestamp
            <= self.settings.max_message_age_seconds
        )

    def _reserve_ai(self) -> bool:
        day = datetime.fromtimestamp(self.clock(), VIETNAM).date().isoformat()
        return self.state.reserve_ai(day, self.settings.max_ai_calls_per_day)

    async def _typing_update(self, message: Message, is_typing: bool) -> bool:
        try:
            async with asyncio.timeout(TYPING_UPDATE_TIMEOUT):
                await self.transport.set_typing(message, is_typing)
            return True
        except Exception:
            self.log("Không cập nhật được trạng thái đang nhập; vẫn xử lý trả lời.")
            return False

    async def _typing_worker(self, message: Message) -> None:
        try:
            while self._may_send(message.thread):
                if not await self._typing_update(message, True):
                    break
                await asyncio.sleep(TYPING_REFRESH_SECONDS)
        finally:
            cleanup = asyncio.create_task(self._typing_update(message, False))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    def _cancel_typing(self, thread: str) -> None:
        task = self.typing_tasks.get(thread)
        if task is not None and not task.done() and not task.cancelling():
            task.cancel()

    async def _finish_typing(self, thread: str) -> None:
        self._cancel_typing(thread)
        task = self.typing_tasks.pop(thread, None)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def _worker(self, thread: str) -> None:
        image_cache: dict[tuple[ImageAttachment, bool], ImageInput] = {}
        try:
            while thread in self.pending:
                revision = self.revisions[thread]
                await asyncio.sleep(self.settings.debounce_seconds)
                if revision != self.revisions[thread]:
                    continue
                now = self.clock()
                wait = (
                    self.state.last_send(thread)
                    + self.settings.reply_cooldown_seconds
                    - now
                )
                if wait > 0:
                    await asyncio.sleep(wait)
                if not self._may_send(thread):
                    break
                if revision != self.revisions[thread]:
                    continue
                midnight = (
                    datetime.fromtimestamp(self.clock(), VIETNAM)
                    .replace(hour=0, minute=0, second=0, microsecond=0)
                    .timestamp()
                )
                if (
                    self.state.sends_since(thread, midnight)
                    >= self.settings.max_replies_per_thread_per_day
                ):
                    self.log("Đã đạt giới hạn trả lời trong ngày của cuộc trò chuyện.")
                    break
                history = self.state.history(
                    thread,
                    self.settings.history_messages,
                    self.settings.history_char_limit,
                    idle_seconds=self.settings.history_idle_seconds,
                )
                if not history or history[-1]["role"] != "user":
                    # A prior send can finish after the next input was stored.
                    # Keep that pending input last, including with a tiny budget.
                    for index in range(len(history) - 1, -1, -1):
                        if history[index]["role"] == "user":
                            history.pop(index)
                            break
                    history.append(
                        {
                            "role": "user",
                            "content": self._input_content(self.latest[thread]),
                        }
                    )
                    history = recent_history(
                        history,
                        self.settings.history_messages,
                        self.settings.history_char_limit,
                    )
                if not self.settings.dry_run and thread not in self.typing_tasks:
                    self.typing_tasks[thread] = asyncio.create_task(
                        self._typing_worker(self.latest[thread])
                    )
                attachments = list(self.pending_images.get(thread, ()))
                if attachments and self.image_ai is not None:
                    async with self.image_slots:
                        if not self._may_send(thread):
                            break
                        if revision != self.revisions[thread]:
                            continue
                        image_cache = {
                            key: value
                            for key, value in image_cache.items()
                            if key in attachments
                        }
                        try:
                            for attachment, encrypted in attachments:
                                key = (attachment, encrypted)
                                if key not in image_cache:
                                    image_cache[key] = await self.transport.load_image(
                                        attachment, encrypted=encrypted
                                    )
                                if (
                                    not self._may_send(thread)
                                    or revision != self.revisions[thread]
                                ):
                                    break
                            if not self._may_send(thread):
                                break
                            if revision != self.revisions[thread]:
                                continue
                            text = await self.image_ai.generate(
                                history,
                                self._reserve_ai,
                                images=[image_cache[key] for key in attachments],
                            )
                            self.log(f"Đã đọc ảnh bằng: {self.image_ai.last_used}.")
                        except ImageError:
                            self.log(
                                "Không tải/xử lý được ảnh; không gọi AI để đoán nội dung."
                            )
                            text = IMAGE_FAILURE
                else:
                    text = await self.ai.generate(history, self._reserve_ai)
                if not self._may_send(thread):
                    break
                if revision != self.revisions[thread]:
                    continue
                text = reply_text(text)
                message = self.latest[thread]
                text = (
                    self.settings.reply_prefix
                    + text.strip()[: self.settings.output_char_limit]
                )
                self.pending.discard(thread)
                self.pending_images.pop(thread, None)
                image_cache.clear()
                if self.settings.dry_run:
                    self.log(f"[XEM TRƯỚC — CHƯA GỬI] {text}")
                    continue
                outbox_id = self.state.begin_send(thread, text, self.clock())
                try:
                    result = await self.transport.send(message, text)
                except Exception:
                    self.state.finish_send(outbox_id, "unknown")
                    self.state.pause(
                        thread, self.clock() + self.settings.manual_pause_seconds
                    )
                    self.log(
                        "Gửi chưa rõ kết quả: không tự gửi lại; tạm dừng cuộc trò chuyện."
                    )
                    continue
                mid = (
                    result.get("messageId") or result.get("id")
                    if isinstance(result, dict)
                    else None
                )
                if (
                    not isinstance(result, dict)
                    or result.get("deliveryStatus") == "unknown"
                    or not mid
                ):
                    self.state.finish_send(
                        outbox_id, "unknown", str(mid) if mid else None
                    )
                    self.state.pause(
                        thread, self.clock() + self.settings.manual_pause_seconds
                    )
                    self.log("Chưa xác nhận được tin đã gửi: không tự gửi lại.")
                    continue
                self.state.finish_send(outbox_id, "sent", str(mid))
                self.state.remember(
                    thread,
                    "assistant",
                    text,
                    self.clock(),
                    self.settings.history_messages,
                )
                self.log("Đã gửi một câu trả lời tự động.")
        except AIError as error:
            self.log(str(error))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.log(
                f"Lượt trả lời dừng do lỗi {type(error).__name__}; nội dung lỗi chi tiết được ẩn."
            )
        finally:
            self.pending.discard(thread)
            self.pending_images.pop(thread, None)
            await self._finish_typing(thread)
            # A new message may arrive while the typing-off RPC is finishing.
            if thread in self.pending and not self.closing:
                self.tasks[thread] = asyncio.create_task(self._worker(thread))

    async def close(self) -> None:
        # Let any in-flight send finish instead of blindly cancelling/replaying it.
        self.closing = True
        self.pending.clear()
        self.pending_images.clear()
        for thread in self.typing_tasks:
            self._cancel_typing(thread)
        if self.typing_tasks:
            await asyncio.gather(*self.typing_tasks.values(), return_exceptions=True)
        if self.tasks:
            done, waiting = await asyncio.wait(list(self.tasks.values()), timeout=35)
            for task in waiting:
                task.cancel()
            if waiting:
                await asyncio.gather(*waiting, return_exceptions=True)
