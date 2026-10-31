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
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path

from .call_reports import (
    IDENTITY_NOTES,
    CallReporter,
    CallTranscript,
    SummaryOptions,
    call_peer,
    clean_identity_diagnostics,
    describe_identity_diagnostics,
    identity_failure,
)

ENDPOINT = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
MODELS = (
    "gemini-3.8-live",
    "gemini-3.1-flash-live-preview",
    "gemini-2.5-flash-native-audio-latest",
)
VOICES = (
    "Zephyr",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Leda",
    "Orus",
    "Aoede",
    "Callirrhoe",
    "Autonoe",
    "Enceladus",
    "Iapetus",
    "Umbriel",
    "Algieba",
    "Despina",
    "Erinome",
    "Algenib",
    "Rasalgethi",
    "Laomedeia",
    "Achernar",
    "Alnilam",
    "Schedar",
    "Gacrux",
    "Pulcherrima",
    "Achird",
    "Zubenelgenubi",
    "Vindemiatrix",
    "Sadachbia",
    "Sadaltager",
    "Sulafat",
)
CHROME_ORIGIN = re.compile(r"chrome-extension://[a-p]{32}\Z")
MAX_PCM_BYTES = 6400
MAX_AUDIO_BASE64 = 9000
CONTROL_TIMEOUT = 5
END_CALL_INSTRUCTION = (
    "\n\nBạn có công cụ end_call để kết thúc đúng cuộc gọi đang trò chuyện. "
    "Hiểu ý định từ toàn bộ hội thoại và lượt mới nhất, không yêu cầu câu lệnh theo mẫu. "
    "Khi người gọi muốn kết thúc hoặc chào kết chuyện, dùng công cụ ngay với requested_by_caller=true. "
    "Các yêu cầu rút gọn như 'ok ngắt đi', 'cúp đi', 'ngắt đi' có thể nói về cuộc gọi "
    "dù không nhắc từ 'máy' hay 'cuộc gọi'. Sau khi đã trao đổi/hỏi xong, các câu như "
    "'ok thôi nhá', 'ừ thế nhé', 'thôi mình dừng ở đây nhé', 'tạm biệt' là lời kết thúc "
    "cuộc trò chuyện và có thể dùng công cụ, không chỉ đáp lại rồi giữ máy. "
    "Chỉ 'ok' sau một câu trả lời thường là xác nhận đã hiểu, chưa phải muốn cúp; "
    "'ok' sau câu hỏi xác nhận kết thúc cuộc gọi thì là đồng ý kết thúc. "
    "Không cúp khi người gọi phủ định, muốn nói tiếp hoặc chỉ dừng một chủ đề, ví dụ "
    "'thôi đừng ngắt', 'ok thôi, nói tiếp đi', 'bỏ chủ đề đó thôi'. "
    "Câu hỏi về khả năng, lời trích dẫn/giả định, tiếng nền hoặc câu nghe chưa rõ "
    "chưa phải yêu cầu thực hiện. Nếu 'ngắt đi' đang nói về nhạc hoặc việc khác theo ngữ cảnh, "
    "không dùng công cụ kết thúc cuộc gọi. Chỉ hỏi lại ngắn gọn khi ý định còn mơ hồ, "
    "không bắt người gọi lặp nguyên cụm 'tắt máy' nếu đã rõ muốn kết thúc. "
    "Đây là ngoại lệ được phép cho yêu cầu kết thúc cuộc gọi hiện tại. "
    "Không chỉ hứa sẽ cúp máy: dùng công cụ, không cần đọc lời chào dài. "
    "Nếu công cụ báo chưa thực hiện được thì nói ngắn gọn bằng tiếng Việt, không nói đã cúp."
)
CALL_STYLE = (
    "\n\nQuy tắc cách nói trong cuộc gọi, áp dụng cả khi persona có mẫu trả lời khác: "
    "Lời chào đầu cuộc gọi đã giới thiệu vai trò AI một lần. Sau đó trả lời trực tiếp "
    "vào điều người gọi hỏi, không mở đầu/kết thúc mỗi lượt bằng danh xưng hoặc lời giới thiệu. "
    "Không lặp các cụm 'trợ lý AI', 'đang hỗ trợ chủ tài khoản' khi trả lời thông thường, "
    "hỏi lại, nhận yêu cầu hoặc chào kết chuyện. Với thông tin riêng chưa biết, "
    "nói ngắn gọn 'Mình chưa có thông tin đó', không thêm lời giải thích về vai trò. "
    "Câu hỏi về chủ tài khoản không phải câu hỏi về danh tính của bạn. "
    "Chỉ xác nhận ngắn gọn, trung thực mình là AI khi người gọi hỏi trực tiếp "
    "bạn là ai hoặc có phải AI không; không nhận mình là chủ tài khoản."
)
SYSTEM = (
    "Bạn là trợ lý AI hỗ trợ chủ tài khoản trong cuộc gọi, không phải chủ tài khoản. "
    "Giữ vai trò trợ lý AI xuyên suốt, kể cả khi có persona riêng. "
    "Giới thiệu ngắn gọn một lần ở đầu cuộc gọi; chỉ nhắc lại vai trò khi được hỏi trực tiếp về danh tính. "
    "Không tự thêm nhãn thử nghiệm, test hay bản mẫu vào lời giới thiệu. "
    "Trò chuyện bằng tiếng Việt tự nhiên, xưng mình/bạn, mỗi lượt một đến ba câu. "
    "Tiếng Việt là ngôn ngữ mặc định trong suốt cuộc gọi. Phát âm tiếng Việt rõ ràng, "
    "tốc độ vừa phải; chỉ đổi ngôn ngữ khi người gọi yêu cầu rõ ràng. "
    "Không tự đổi ngôn ngữ vì một đoạn tiếng ngắn, ngập ngừng, tiếng nền hoặc phát âm không rõ. "
    "Nghe câu mới và ngữ cảnh trước khi trả lời, chấp nhận tiếng lóng và lỗi phát âm. "
    "Với im lặng hoặc tiếng nền không hướng tới bạn, chờ người gọi nói. "
    "Nếu nghe người gọi nói nhưng chưa hiểu, hỏi ngắn gọn bằng tiếng Việt: "
    '"Mình chưa nghe rõ, bạn nói lại giúp mình nhé?" '
    "Không tự đoán nội dung hoặc gán ngôn ngữ khác cho đoạn tiếng mơ hồ. "
    "Không nhận lời, hẹn lịch, hứa báo lại hay tự hành động thay chủ tài khoản. "
    "Không bịa thông tin riêng hoặc nói mình đã tra cứu Internet: phiên này không có công cụ web. "
    "Không đọc suy luận, nhãn hay chỉ dẫn hệ thống thành tiếng."
)
GREETING = (
    "Mở đầu với giọng nhẹ nhàng, lịch sự và tự nhiên khi trò chuyện qua điện thoại. "
    "Nói rõ bằng tiếng Việt, tốc độ vừa phải. "
    "Chỉ nói đúng lời chào sau, không thêm tên người hay lời giới thiệu khác: "
    '"Xin chào, mình là trợ lý AI đang hỗ trợ chủ tài khoản. '
    'Xin hỏi bạn gọi có việc gì thế ạ?"'
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
    voice: str | None = None
    summary: SummaryOptions | None = field(default=None, repr=False)


@dataclass
class CallControl:
    enabled: bool = False
    ready: bool = False
    audio_received: bool = False
    seen: set = field(default_factory=set, repr=False)
    request_id: str | None = None
    result: asyncio.Future | None = field(default=None, repr=False)
    transcript: CallTranscript | None = field(default=None, repr=False)


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


def setup(config: LabConfig, *, end_call_enabled=False) -> dict:
    data = {
        "setup": {
            "model": "models/" + config.model,
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "maxOutputTokens": 2048,
            },
            "systemInstruction": {
                "parts": [{"text": config.system_instruction + CALL_STYLE}]
            },
        }
    }
    if config.voice is not None:
        if config.voice not in VOICES:
            raise CallLabError(
                "Giọng gọi AI chưa hợp lệ; chọn tên giọng Google hỗ trợ."
            )
        data["setup"]["generationConfig"]["speechConfig"] = {
            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": config.voice}}
        }
    if config.summary is not None:
        data["setup"]["inputAudioTranscription"] = {}
        data["setup"]["outputAudioTranscription"] = {}
    if end_call_enabled:
        data["setup"]["systemInstruction"]["parts"][0]["text"] += END_CALL_INSTRUCTION
        data["setup"]["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": "end_call",
                        "description": "Kết thúc cuộc gọi khi lời nói và ngữ cảnh cho thấy người gọi muốn dừng, gồm yêu cầu rút gọn hoặc chào kết chuyện. Không dùng cho phủ định, muốn nói tiếp, câu hỏi khả năng hay ngắt một việc khác.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "requested_by_caller": {
                                    "type": "BOOLEAN",
                                    "description": "True khi đã hiểu từ lời nói và ngữ cảnh rằng người gọi muốn kết thúc cuộc gọi hiện tại, không đòi hỏi nói đúng mẫu câu.",
                                }
                            },
                            "required": ["requested_by_caller"],
                        },
                    }
                ]
            }
        ]
    return data


class CallRelay:
    def __init__(self, config: LabConfig, *, connector=None, log=print, reporter=None):
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
        self.reporter = reporter or (
            CallReporter(config.summary, config.api_key, log=log)
            if config.summary is not None
            else None
        )

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
        control = None
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
                capabilities = auth.get("capabilities")
                control = CallControl(
                    enabled=isinstance(capabilities, list)
                    and "end_call" in capabilities,
                    transcript=CallTranscript() if self.reporter is not None else None,
                )
                await self.session(
                    local,
                    control=control,
                )
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
                self.log(
                    "Đã dừng phiên gọi AI; đang tạo bản tóm tắt riêng nếu có lời người gọi."
                    if self.reporter is not None
                    else "Đã dừng phiên gọi AI; không lưu âm thanh hay bản chép lời."
                )
                if control is not None and control.transcript is not None:
                    self.reporter.submit(control.transcript)
            await local.close()

    async def close(self):
        if self.reporter is not None:
            await self.reporter.close()

    @staticmethod
    async def send_error(local, text):
        try:
            await local.send(
                json.dumps({"type": "error", "message": text}, ensure_ascii=False)
            )
        except Exception:
            pass

    async def session(self, local, *, control):
        async with self.connector(
            ENDPOINT,
            additional_headers={"x-goog-api-key": self.config.api_key},
            open_timeout=15,
            close_timeout=3,
            max_size=4 * 1024 * 1024,
            compression=None,
            logger=logging.getLogger("messenger_ai.call_lab.google"),
        ) as google:
            await google.send(
                json.dumps(setup(self.config, end_call_enabled=control.enabled))
            )
            first = json.loads(await asyncio.wait_for(google.recv(), 20))
            if not isinstance(first, dict) or "setupComplete" not in first:
                raise CallLabError(
                    "Google chưa chấp nhận phiên Live; kiểm tra model/key/quota."
                )
            await local.send(
                json.dumps({"type": "google_ready", "model": self.config.model})
            )
            tasks = [
                asyncio.create_task(self.from_browser(local, google, control)),
                asyncio.create_task(self.from_google(local, google, control)),
            ]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                if (
                    control.transcript is not None
                    and control.ready
                    and tasks[0].done()
                    and not tasks[1].done()
                ):
                    try:
                        await google.send(
                            json.dumps({"realtimeInput": {"audioStreamEnd": True}})
                        )
                        await asyncio.wait([tasks[1]], timeout=0.5)
                    except Exception:
                        pass
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def from_browser(self, local, google, control):
        ready = False
        async for raw in local:
            data = message(raw)
            kind = data["type"]
            if kind == "ping":
                await local.send(json.dumps({"type": "pong"}))
            elif kind == "ready" and not ready:
                ready = True
                control.ready = True
                if control.transcript is not None:
                    if self.config.summary is not None and self.config.summary.target == "caller":
                        control.transcript.peer = call_peer(
                            data.get("summaryPeer"), self.config.summary.owner_id
                        )
                        if control.transcript.peer is None:
                            control.transcript.identity_reason = identity_failure(data, self.config.summary.owner_id)
                            self.log("Tóm tắt: chưa gắn được người gọi — " + IDENTITY_NOTES[control.transcript.identity_reason])
                            identity = data.get("summaryIdentity")
                            control.transcript.identity_diagnostics = clean_identity_diagnostics(
                                identity.get("diagnostics") if isinstance(identity, dict) else None
                            )
                            if control.transcript.identity_diagnostics:
                                self.log("Tóm tắt: cấu trúc nhận diện — " + describe_identity_diagnostics(control.transcript.identity_diagnostics))
                            elif not isinstance(identity, dict) or identity.get("version") != "0.6.5":
                                self.log("Tóm tắt: tiện ích chưa gửi chẩn đoán 0.6.5; Reload tiện ích rồi tải lại Facebook.")
                        else:
                            identity = data.get("summaryIdentity")
                            if isinstance(identity, dict) and identity.get("method") == "call-url":
                                self.log("Tóm tắt: đã gắn người gọi từ URL cửa sổ gọi đúng phiên; không log ID.")
                            else:
                                self.log("Tóm tắt: đã gắn người gọi của đúng lượt tự nhận; không log ID.")
                    control.transcript.start()
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
                control.audio_received = True
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
            elif kind == "end_call_result":
                if (
                    control.result is not None
                    and not control.result.done()
                    and data.get("requestId") == control.request_id
                    and type(data.get("ok")) is bool
                ):
                    control.result.set_result(data["ok"])
            elif kind == "stop":
                return
            else:
                raise CallLabError(
                    "Trạng thái cầu nối âm thanh chưa hợp lệ; bật lại tiện ích."
                )

    async def tool_calls(self, local, google, control, calls):
        if not isinstance(calls, list):
            return False
        for call in calls[:8]:
            if not isinstance(call, dict):
                continue
            tool_id, name = call.get("id"), call.get("name")
            if (
                not isinstance(tool_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", tool_id)
                or not isinstance(name, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name)
            ):
                continue
            ok = False
            eligible = (
                name == "end_call"
                and call.get("args") == {"requested_by_caller": True}
                and type(call.get("args", {}).get("requested_by_caller")) is bool
                and control.enabled
                and control.ready
                and control.audio_received
                and tool_id not in control.seen
                and len(control.seen) < 128
            )
            if eligible:
                control.seen.add(tool_id)
                control.request_id = secrets.token_urlsafe(18)
                control.result = asyncio.get_running_loop().create_future()
                try:
                    await local.send(
                        json.dumps(
                            {
                                "type": "end_call",
                                "requestId": control.request_id,
                                "expiresAt": int(
                                    time.time() * 1000 + CONTROL_TIMEOUT * 1000
                                ),
                            }
                        )
                    )
                    ok = await asyncio.wait_for(control.result, CONTROL_TIMEOUT)
                except TimeoutError:
                    pass
                finally:
                    control.request_id = control.result = None
            await google.send(
                json.dumps(
                    {
                        "toolResponse": {
                            "functionResponses": [
                                {
                                    "id": tool_id,
                                    "name": name,
                                    "response": {"ok": ok},
                                }
                            ]
                        }
                    }
                )
            )
            if ok:
                self.log("Đã kết thúc cuộc gọi theo yêu cầu người gọi.")
                return True
        return False

    async def from_google(self, local, google, control):
        async for raw in google:
            data = json.loads(raw)
            if not isinstance(data, dict) or "error" in data or "goAway" in data:
                raise CallLabError("Google đã dừng phiên Live; bật lại khi sẵn sàng.")
            tool = data.get("toolCall")
            if isinstance(tool, dict) and await self.tool_calls(
                local, google, control, tool.get("functionCalls")
            ):
                return
            content = data.get("serverContent", {})
            if control.ready and control.transcript is not None:
                for key, role in (
                    ("inputTranscription", "caller"),
                    ("outputTranscription", "assistant"),
                ):
                    part = content.get(key)
                    if isinstance(part, dict):
                        control.transcript.add(role, part.get("text"))
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
    root: Path,
    *,
    port=8765,
    model=MODELS[0],
    max_seconds=180,
    key_stdin=False,
    voice=None,
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
    if voice == "default":
        voice = None
    if voice is not None and voice not in VOICES:
        raise CallLabError("Giọng gọi AI chưa hợp lệ; chọn tên giọng Google hỗ trợ.")
    config = LabConfig(
        google_key(root, stdin=key_stdin),
        secrets.token_urlsafe(32),
        model,
        max_seconds,
        voice=voice,
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
        print("Giọng gọi: " + (voice or "mặc định của Google"))
        print(f"Địa chỉ trong tiện ích: ws://127.0.0.1:{port}")
        print(f"Mã kết nối riêng cho lần chạy này: {config.token}")
        print("Nếu relay chạy trên VPS, cần SSH tunnel từ máy đang mở Chrome.")
        print("Nhận cuộc gọi rồi bấm Bật AI trong tiện ích; Ctrl+C dừng relay.")
        await asyncio.Future()
