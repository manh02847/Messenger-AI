from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

from .core import Message
from .images import (
    MAX_IMAGE_BYTES,
    MEDIA_TIMEOUT,
    ImageAttachment,
    ImageError,
    ImageInput,
    prepare_image,
    validate_attachment,
    validate_media_url,
)


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
        self.media_client: httpx.AsyncClient | None = None

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
        if self.media_client is not None:
            await self.media_client.aclose()

    async def load_image(
        self, image: ImageAttachment, *, encrypted: bool
    ) -> ImageInput:
        from fbchat_v2._messaging._bridge_actions import BridgeActions

        if self.listener is None or self.closing:
            raise ImageError()
        validate_attachment(image, encrypted=encrypted)
        try:
            async with asyncio.timeout(MEDIA_TIMEOUT):
                if encrypted:
                    if self.listener._bridge is None:
                        raise ImageError()
                    result = await BridgeActions(
                        self.listener._bridge
                    ).download_e2ee_media(
                        image.direct_path,
                        image.media_key,
                        image.media_sha256,
                        image.media_enc_sha256,
                        "image",
                        image.mime_type,
                        image.file_size,
                    )
                    data = result.get("data")
                    if not isinstance(data, bytes) or len(data) != image.file_size:
                        raise ImageError()
                else:
                    data = await self._download_photo(image.url)
                return await asyncio.to_thread(prepare_image, data)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ImageError() from None

    async def _download_photo(self, url: str) -> bytes:
        if self.media_client is None:
            # Signed Meta CDN URLs do not need the Facebook cookie.
            self.media_client = httpx.AsyncClient(
                timeout=10, follow_redirects=False, trust_env=False
            )
        for _ in range(5):
            validate_media_url(url)
            async with self.media_client.stream(
                "GET", url, headers={"Accept-Encoding": "identity"}
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location", "")
                    url = str(response.url.join(location))
                    validate_media_url(url)
                    continue
                response.raise_for_status()
                length = response.headers.get("content-length")
                if length is not None and int(length) > MAX_IMAGE_BYTES:
                    raise ImageError()
                data = bytearray()
                async for chunk in response.aiter_bytes(65536):
                    if len(data) + len(chunk) > MAX_IMAGE_BYTES:
                        raise ImageError()
                    data.extend(chunk)
                return bytes(data)
        raise ImageError()
