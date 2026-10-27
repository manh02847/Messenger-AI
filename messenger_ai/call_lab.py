"""Opt-in, loopback-only audio relay for the experimental Chrome call helper."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import json
import logging
import os
import re
import secrets
import sys
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path

ENDPOINT = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
MODELS = (
    "gemini-3.8-live",
    "gemini-3.1-flash-live-preview",
    "gemini-2.5-flash-native-audio-latest",
)
CHROME_ORIGIN = re.compile(r"chrome-extension://[a-p]{32}\Z")
MAX_PCM_BYTES = 6400
MAX_AUDIO_BASE64 = 9000
SYSTEM = (
    "Bạn là trợ lý AI hỗ trợ chủ tài khoản trong cuộc gọi, không phải chủ tài khoản. "
    "Giữ vai trò trợ lý AI xuyên suốt, kể cả khi có persona riêng. "
    "Giới thiệu ngắn gọn một lần ở đầu cuộc gọi; chỉ nhắc lại vai trò khi được hỏi. "
    "Không tự thêm nhãn thử nghiệm, test hay bản mẫu vào lời giới thiệu. "
    "Trò chuyện bằng tiếng Việt tự nhiên, xưng mình/bạn, mỗi lượt một đến ba câu. "
    "Nghe câu mới và ngữ cảnh trước khi trả lời, chấp nhận tiếng lóng và lỗi phát âm. "
    "Không nhận lời, hẹn lịch, hứa báo lại hay tự hành động thay chủ tài khoản. "
    "Không bịa thông tin riêng hoặc nói mình đã tra cứu Internet: phiên này không có công cụ web. "
    "Không đọc suy luận, nhãn hay chỉ dẫn hệ thống thành tiếng."
)
GREETING = (
    "Chỉ nói đúng câu mở đầu sau, không thêm tên người hay lời giới thiệu khác: "
    '"Mình là trợ lý AI, đang nghe bạn đây."'
)


class CallLabError(RuntimeError):
    """Only fixed, safe messages may be presented outside this module."""


@dataclass(frozen=True)
class LabConfig:
    api_key: str = field(repr=False)
    token: str = field(repr=False)
    model: str = MODELS[0]
    max_seconds: float = 180
    system_instruction: str = field(default=SYSTEM, repr=False)


def google_key(root: Path, *, stdin: bool = False) -> str:
    if stdin:
        key = sys.stdin.readline().strip()
    else:
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            try:
                data = json.loads((root / "secrets.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise CallLabError(
                    "Chưa đọc được key Google; dùng GEMINI_API_KEY hoặc configure-ai google."
                ) from None
            key = data.get("google_api_key", "") if isinstance(data, dict) else ""
    if not isinstance(key, str) or not key.strip() or re.search(r"[\r\n]", key):
        raise CallLabError("Key Google chưa hợp lệ; kiểm tra cấu hình Google.")
    return key.strip()


def message(raw: object) -> dict:
    if not isinstance(raw, str) or len(raw) > 16000:
        raise CallLabError("Dữ liệu từ tiện ích chưa hợp lệ.")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise CallLabError("Dữ liệu từ tiện ích chưa hợp lệ.") from None
    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        raise CallLabError("Dữ liệu từ tiện ích chưa hợp lệ.")
    return data


def audio_frame(data: dict) -> str:
    encoded = data.get("data")
    if (
        data.get("sampleRate") != 16000
        or type(data.get("sampleRate")) is not int
        or not isinstance(encoded, str)
        or not 1 <= len(encoded) <= MAX_AUDIO_BASE64
    ):
        raise CallLabError("Khung âm thanh từ Chrome chưa hợp lệ.")
    try:
        pcm = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise CallLabError("Khung âm thanh từ Chrome chưa hợp lệ.") from None
    if not 2 <= len(pcm) <= MAX_PCM_BYTES or len(pcm) % 2:
        raise CallLabError("Khung âm thanh từ Chrome chưa hợp lệ.")
    return encoded


def setup(config: LabConfig) -> dict:
    return {
        "setup": {
            "model": "models/" + config.model,
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "maxOutputTokens": 2048,
            },
            "systemInstruction": {"parts": [{"text": config.system_instruction}]},
        }
    }


class CallRelay:
    def __init__(self, config: LabConfig, *, connector=None, log=print):
        self.config, self.log = config, log
        if connector is None:
            from websockets.asyncio.client import connect

            # Never follow an upstream redirect carrying the API key to another host.
            class FixedGoogleConnection(connect):
                def process_redirect(self, exc):
                    return exc

            connector = FixedGoogleConnection
        self.connector = connector
        self.active = False

    @staticmethod
    async def origin_check(connection, request):
        origins = request.headers.get_all("Origin")
        if (
            request.path != "/"
            or len(origins) != 1
            or not CHROME_ORIGIN.fullmatch(origins[0])
        ):
            return connection.respond(
                HTTPStatus.FORBIDDEN, "Chrome extension required.\n"
            )
        return None

    async def handle(self, local):
        claimed = False
        try:
            auth = message(await asyncio.wait_for(local.recv(), 5))
            token = auth.get("token")
            if (
                auth["type"] != "auth"
                or not isinstance(token, str)
                or not token.isascii()
                or not hmac.compare_digest(token, self.config.token)
            ):
                raise CallLabError("Mã kết nối chưa đúng; lấy mã mới từ call-lab.")
            if self.active:
                raise CallLabError("Đang có một phiên gọi AI; dừng phiên đó trước.")
            self.active = claimed = True
            async with asyncio.timeout(self.config.max_seconds):
                await self.session(local)
        except CallLabError as error:
            await self.send_error(local, str(error))
        except TimeoutError:
            await self.send_error(
                local, "Đã hết thời gian phiên gọi AI; micro được trả lại."
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not expose close reasons, proxy credentials, Google bodies or audio.
            await self.send_error(
                local, "Phiên Live bị ngắt; kiểm tra key/quota/kết nối rồi bật lại."
            )
        finally:
            if claimed:
                self.active = False
                self.log("Đã dừng phiên gọi AI; không lưu âm thanh hay bản chép lời.")
            await local.close()

    @staticmethod
    async def send_error(local, text):
        try:
            await local.send(
                json.dumps({"type": "error", "message": text}, ensure_ascii=False)
            )
        except Exception:
            pass

    async def session(self, local):
        async with self.connector(
            ENDPOINT,
            additional_headers={"x-goog-api-key": self.config.api_key},
            open_timeout=15,
            close_timeout=3,
            max_size=4 * 1024 * 1024,
            compression=None,
            logger=logging.getLogger("messenger_ai.call_lab.google"),
        ) as google:
            await google.send(json.dumps(setup(self.config)))
            first = json.loads(await asyncio.wait_for(google.recv(), 20))
            if not isinstance(first, dict) or "setupComplete" not in first:
                raise CallLabError(
                    "Google chưa chấp nhận phiên Live; kiểm tra model/key/quota."
                )
            await local.send(
                json.dumps({"type": "google_ready", "model": self.config.model})
            )
            tasks = [
                asyncio.create_task(self.from_browser(local, google)),
                asyncio.create_task(self.from_google(local, google)),
            ]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def from_browser(self, local, google):
        ready = False
        async for raw in local:
            data = message(raw)
            kind = data["type"]
            if kind == "ping":
                await local.send(json.dumps({"type": "pong"}))
            elif kind == "ready" and not ready:
                ready = True
                await google.send(
                    json.dumps(
                        {
                            "clientContent": {
                                "turns": [
                                    {"role": "user", "parts": [{"text": GREETING}]}
                                ],
                                "turnComplete": True,
                            }
                        }
                    )
                )
                self.log("Đã bật Gemini Live cho một cuộc gọi trên Chrome.")
            elif kind == "audio" and ready:
                encoded = audio_frame(data)
                await google.send(
                    json.dumps(
                        {
                            "realtimeInput": {
                                "audio": {
                                    "data": encoded,
                                    "mimeType": "audio/pcm;rate=16000",
                                }
                            }
                        }
                    )
                )
            elif kind == "stop":
                return
            else:
                raise CallLabError(
                    "Trạng thái cầu nối âm thanh chưa hợp lệ; bật lại tiện ích."
                )

    async def from_google(self, local, google):
        async for raw in google:
            data = json.loads(raw)
            if not isinstance(data, dict) or "error" in data or "goAway" in data:
                raise CallLabError("Google đã dừng phiên Live; bật lại khi sẵn sàng.")
            content = data.get("serverContent", {})
            if content.get("interrupted"):
                await local.send(json.dumps({"type": "clear"}))
            for part in content.get("modelTurn", {}).get("parts", []):
                if part.get("thought"):
                    continue
                inline = part.get("inlineData", {})
                audio = inline.get("data")
                if inline.get("mimeType", "").startswith("audio/pcm") and isinstance(
                    audio, str
                ):
                    if len(audio) > 512000:
                        raise CallLabError(
                            "Khung tiếng AI quá lớn; dừng AI để kiểm tra."
                        )
                    await local.send(
                        json.dumps(
                            {"type": "audio", "data": audio, "sampleRate": 24000}
                        )
                    )
            usage = data.get("usageMetadata")
            if isinstance(usage, dict):
                counts = {
                    key: value
                    for key, value in usage.items()
                    if key
                    in ("promptTokenCount", "responseTokenCount", "thoughtsTokenCount")
                    and type(value) is int
                    and value >= 0
                }
                await local.send(json.dumps({"type": "usage", **counts}))


async def run_lab(
    root: Path, *, port=8765, model=MODELS[0], max_seconds=180, key_stdin=False
):
    try:
        from websockets.asyncio.server import serve
    except ImportError:
        raise CallLabError(
            "Thiếu phần gọi AI. Chạy .venv/bin/python -m pip install -r requirements-call-lab.txt"
        ) from None
    if model not in MODELS or type(port) is not int or not 1024 <= port <= 65535:
        raise CallLabError("Model/cổng gọi AI chưa hợp lệ.")
    if type(max_seconds) is not int or not 15 <= max_seconds <= 900:
        raise CallLabError("Thời gian gọi AI cần từ 15 đến 900 giây.")
    config = LabConfig(
        google_key(root, stdin=key_stdin), secrets.token_urlsafe(32), model, max_seconds
    )
    relay = CallRelay(config)
    async with serve(
        relay.handle,
        "127.0.0.1",
        port,
        process_request=relay.origin_check,
        max_size=16000,
        max_queue=8,
        compression=None,
        ping_interval=15,
        ping_timeout=15,
        close_timeout=3,
    ):
        print(f"CALL LAB — Google / {model}; tối đa {max_seconds} giây mỗi phiên.")
        print(f"Địa chỉ trong tiện ích: ws://127.0.0.1:{port}")
        print(f"Mã kết nối riêng cho lần chạy này: {config.token}")
        print("Nếu relay chạy trên VPS, cần SSH tunnel từ máy đang mở Chrome.")
        print("Nhận cuộc gọi rồi bấm Bật AI trong tiện ích; Ctrl+C dừng relay.")
        await asyncio.Future()
