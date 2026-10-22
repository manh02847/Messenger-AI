from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from .ai import AIError
from .config import Settings
from .handoff import reply_text, requests_human
from .state import State

VIETNAM = timezone(timedelta(hours=7))


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
    )


class AI(Protocol):
    async def generate(
        self, history: list[dict[str, str]], reserve: Callable[[], bool]
    ) -> str: ...


class Transport(Protocol):
    async def send(self, message: Message, text: str) -> dict[str, Any]: ...


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

    def receive(self, message: Message) -> None:
        now = self.clock()
        if message.thread not in self.settings.allowed_threads:
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
            self.state.pause(message.thread, now + self.settings.manual_pause_seconds)
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
        if not message.text.strip():
            return
        self.state.remember(
            message.thread,
            "user",
            message.text[: self.settings.input_char_limit],
            now,
            self.settings.history_messages,
        )
        if requests_human(message.text):
            self.revisions[message.thread] = self.revisions.get(message.thread, 0) + 1
            self.pending.discard(message.thread)
            self.state.pause(message.thread, now + self.settings.manual_pause_seconds)
            self.log("Người nhắn yêu cầu dừng hoặc gặp Mạnh: tạm nhường trả lời.")
            return
        if self.state.paused(message.thread, now):
            return
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

    async def _worker(self, thread: str) -> None:
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
                )
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

    async def close(self) -> None:
        # Let any in-flight send finish instead of blindly cancelling/replaying it.
        self.pending.clear()
        if self.tasks:
            done, waiting = await asyncio.wait(list(self.tasks.values()), timeout=35)
            for task in waiting:
                task.cancel()
            if waiting:
                await asyncio.gather(*waiting, return_exceptions=True)
