from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .core import Message


class FacebookTransport:
    def __init__(self, cookie: str, device_path: Path, binary_path: Path, log=print):
        self.cookie, self.device_path, self.binary_path = (
            cookie,
            device_path,
            binary_path,
        )
        self.log = log
        self.own_id = ""
        self.listener: Any = None
        self.task: asyncio.Task | None = None
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.overflowed = False
        self.closing = False

    async def connect(self) -> None:
        # Import only after setup, so configure/help can run without dependencies.
        from fbchat_v2 import dataGetHome, listeningE2EEEvent

        if not self.cookie or "c_user=" not in self.cookie or "xs=" not in self.cookie:
            raise ValueError("Thiếu cookie Facebook hợp lệ. Chạy configure trước.")
        self.device_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.device_path.parent.chmod(0o700)
        data = await dataGetHome(self.cookie)
        if not isinstance(data, dict) or not str(data.get("FacebookID", "")).isdigit():
            raise RuntimeError(
                "Phiên Facebook chưa hợp lệ. Kiểm tra đăng nhập/checkpoint rồi cập nhật cookie."
            )
        self.own_id = str(data["FacebookID"])
        self.listener = listeningE2EEEvent(
            data,
            binary_path=str(self.binary_path),
            device_path=str(self.device_path),
            e2ee_memory_only=False,
            debug_errors=False,
        )
        loop = asyncio.get_running_loop()

        def forward(event: dict) -> None:
            if isinstance(event, dict) and event.get("type") in (
                "message",
                "e2eeMessage",
            ):
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(self._enqueue, event)

        self.listener.on_message(forward)
        self.listener.set_connection_state_callback(
            lambda status: loop.call_soon_threadsafe(self._status, status)
        )
        self.task = asyncio.create_task(self.listener.connect_mqtt())
        while True:
            ready = await asyncio.to_thread(
                self.listener.wait_until_connected,
                self.listener.startup_timeout,
                require_e2ee=True,
            )
            if ready:
                self.log("Messenger đã kết nối. Đang chờ tin nhắn mới.")
                return
            if self.task.done():
                self.task.result()
                raise RuntimeError("Bộ kết nối Messenger đã dừng.")
            if self.listener.connection_state != "reconnecting":
                raise RuntimeError("Chưa khởi động được kết nối Messenger mã hóa.")
            self.log("Kết nối tạm gián đoạn; bộ kết nối đang tự thử lại.")

    def _status(self, status: dict) -> None:
        if not self.closing:
            state = status.get("state")
            if state in {
                "connected",
                "reconnecting",
                "auth_required",
                "failed",
                "stopped",
            }:
                self.log(f"Trạng thái Messenger: {state}")

    def _enqueue(self, event: dict) -> None:
        if self.closing:
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            # Stop instead of dropping a manual message and replying over the owner.
            self.overflowed = True

    async def events(self) -> AsyncIterator[dict]:
        while not self.closing:
            if self.overflowed:
                raise RuntimeError(
                    "Hàng đợi tin nhắn đã đầy; dừng bot để tránh xử lý thiếu ngữ cảnh."
                )
            if self.task is None or self.task.done():
                if self.task is not None:
                    self.task.result()
                raise RuntimeError(
                    "Kết nối Messenger đã dừng; có thể cần cập nhật cookie."
                )
            try:
                yield await asyncio.wait_for(self.queue.get(), timeout=1)
            except asyncio.TimeoutError:
                continue

    async def send(self, message: Message, text: str) -> dict[str, Any]:
        if self.listener is None or self.closing:
            raise RuntimeError("Messenger chưa sẵn sàng gửi.")
        if message.chat_jid:
            return await self.listener.send_e2ee_message(
                message.chat_jid,
                text,
                reply_to_id=message.id,
                reply_to_sender_jid=message.sender_jid,
            )
        return await self.listener.send_message(
            message.thread_id, text, reply_to_id=message.id
        )

    async def set_typing(self, message: Message, is_typing: bool) -> None:
        from fbchat_v2._messaging._bridge_actions import BridgeActions

        if self.listener is None or self.closing or self.listener._bridge is None:
            raise RuntimeError("Messenger chưa sẵn sàng cập nhật trạng thái.")
        # Reuse the listener's current bridge and paired E2EE device.
        actions = BridgeActions(self.listener._bridge)
        if message.chat_jid:
            await actions.send_e2ee_typing(message.chat_jid, is_typing)
        else:
            await actions.send_typing_indicator(
                message.thread_id, is_typing, thread_type=message.thread_type
            )

    async def close(self) -> None:
        self.closing = True
        if self.listener is not None:
            await asyncio.to_thread(self.listener.stop)
        if self.task is not None:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await self.task
