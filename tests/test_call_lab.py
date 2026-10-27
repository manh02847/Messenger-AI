import asyncio
import base64
import io
import json
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

from messenger_ai import call_lab as lab

ORIGIN = "chrome-extension://" + "a" * 32
CONFIG = lab.LabConfig("PRIVATE_GOOGLE_KEY", "PRIVATE_LOCAL_TOKEN_123456789")
PCM = base64.b64encode(bytes(3200)).decode()


class FakeGoogle:
    def __init__(self, *, error=None):
        self.queue = asyncio.Queue()
        self.queue.put_nowait(json.dumps({"setupComplete": {}}))
        self.sent, self.closed, self.error = [], False, error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def send(self, raw):
        data = json.loads(raw)
        self.sent.append(data)
        if "clientContent" in data:
            self.queue.put_nowait(
                json.dumps(
                    {
                        "serverContent": {
                            "modelTurn": {
                                "parts": [
                                    {
                                        "thought": True,
                                        "text": "PRIVATE_THOUGHT",
                                        "inlineData": {
                                            "mimeType": "audio/pcm",
                                            "data": "PRIVATE_THOUGHT",
                                        },
                                    },
                                    {
                                        "inlineData": {
                                            "mimeType": "audio/pcm;rate=24000",
                                            "data": PCM,
                                        }
                                    },
                                ]
                            },
                            "outputTranscription": {"text": "PRIVATE_TRANSCRIPT"},
                        },
                        "usageMetadata": {
                            "promptTokenCount": 100,
                            "responseTokenCount": 20,
                            "thoughtsTokenCount": 30,
                            "bad": "PRIVATE_EXTRA",
                        },
                    }
                )
            )

    async def recv(self):
        return await self.queue.get()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.recv()


@asynccontextmanager
async def server(*, config=CONFIG, google_error=None):
    created, logs = [], []

    def connector(url, **options):
        assert url == lab.ENDPOINT
        assert options["additional_headers"] == {"x-goog-api-key": "PRIVATE_GOOGLE_KEY"}
        item = FakeGoogle(error=google_error)
        created.append(item)
        return item

    relay = lab.CallRelay(config, connector=connector, log=logs.append)
    async with serve(
        relay.handle,
        "127.0.0.1",
        0,
        process_request=relay.origin_check,
        close_timeout=0.1,
    ) as listener:
        port = listener.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}/", relay, created, logs


async def receive(ws):
    return json.loads(await asyncio.wait_for(ws.recv(), 1))


async def authorize(ws, token=CONFIG.token, **details):
    await ws.send(json.dumps({"type": "auth", "token": token, **details}))


@pytest.mark.parametrize(
    "raw", [None, b"{}", "bad", "[]", "{}", '{"type":3}', "x" * 16001]
)
def test_bad_local_message(raw):
    with pytest.raises(lab.CallLabError):
        lab.message(raw)


@pytest.mark.parametrize(
    "patch",
    [
        {"sampleRate": 24000},
        {"sampleRate": True},
        {"sampleRate": "16000"},
        {"data": "!"},
        {"data": ""},
        {"data": None},
        {"data": base64.b64encode(b"x").decode()},
        {"data": base64.b64encode(bytes(6402)).decode()},
        {"data": "a" * 9001},
    ],
)
def test_pcm_is_bounded_and_validated(patch):
    with pytest.raises(lab.CallLabError):
        lab.audio_frame({"type": "audio", "sampleRate": 16000, "data": PCM, **patch})


def test_setup_has_no_web_private_persona_text_output_or_exposed_key():
    data = lab.setup(CONFIG)
    assert data["setup"]["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert "tools" not in data["setup"]
    assert "PRIVATE" not in json.dumps(data)
    assert "PRIVATE" not in repr(CONFIG)
    assert "speechConfig" not in data["setup"]["generationConfig"]


def test_only_google_key_is_loaded_and_no_persona_is_read(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    path = tmp_path / "secrets.json"
    original = '{"google_api_key":"TEST_GOOGLE","facebook_cookie":"PRIVATE_COOKIE"}'
    path.write_text(original)
    (tmp_path / "persona.local.txt").write_text("DO_NOT_READ_PERSONA")
    assert lab.google_key(tmp_path) == "TEST_GOOGLE"
    assert path.read_text() == original
    monkeypatch.setenv("GEMINI_API_KEY", "ENV_GOOGLE")
    assert lab.google_key(tmp_path) == "ENV_GOOGLE"
    monkeypatch.setattr(lab.sys, "stdin", io.StringIO("STDIN_GOOGLE\n"))
    assert lab.google_key(tmp_path, stdin=True) == "STDIN_GOOGLE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin",
    [
        None,
        "https://www.facebook.com",
        "https://example.com",
        "chrome-extension://evil",
        "null",
    ],
)
async def test_non_extension_origins_never_open_google(origin):
    async with server() as (url, relay, created, logs):
        with pytest.raises(InvalidStatus) as caught:
            async with connect(url, origin=origin, proxy=None):
                pass
        assert caught.value.response.status_code == 403
        assert not created and not relay.active


@pytest.mark.asyncio
async def test_wrong_token_cannot_open_google_or_leak_it():
    async with server() as (url, relay, created, logs):
        for token in ("WRONG_PRIVATE_TOKEN", "mã không hợp lệ", 123):
            async with connect(url, origin=ORIGIN, proxy=None) as ws:
                await authorize(ws, token)
                response = await receive(ws)
                assert response["type"] == "error" and "PRIVATE" not in json.dumps(
                    response
                )
                assert "Mã kết nối" in response["message"]
        assert not created and not relay.active


@pytest.mark.asyncio
@pytest.mark.parametrize("voice", [None, "Kore", "Puck", "Aoede"])
async def test_authenticated_audio_routes_both_ways_and_filters_all_private_thoughts(
    voice,
):
    config = replace(CONFIG, voice=voice)
    async with server(config=config) as (url, relay, created, logs):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws)
            assert (await receive(ws))["type"] == "google_ready"
            assert created[0].sent == [lab.setup(config)]
            speech = created[0].sent[0]["setup"]["generationConfig"].get("speechConfig")
            assert speech == (
                {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}
                if voice
                else None
            )
            await ws.send(json.dumps({"type": "ready"}))
            audio, usage = await receive(ws), await receive(ws)
            assert audio == {"type": "audio", "data": PCM, "sampleRate": 24000}
            assert usage == {
                "type": "usage",
                "promptTokenCount": 100,
                "responseTokenCount": 20,
                "thoughtsTokenCount": 30,
            }
            assert "PRIVATE" not in json.dumps([audio, usage])
            await ws.send(
                json.dumps({"type": "audio", "data": PCM, "sampleRate": 16000})
            )
            await ws.send(json.dumps({"type": "ping"}))
            assert await receive(ws) == {"type": "pong"}
            assert created[0].sent[-1] == {
                "realtimeInput": {
                    "audio": {"data": PCM, "mimeType": "audio/pcm;rate=16000"}
                }
            }
            await ws.send(json.dumps({"type": "stop"}))
            await asyncio.wait_for(ws.wait_closed(), 1)
        assert not relay.active and created[0].closed
        assert "PRIVATE" not in " ".join(logs)


@pytest.mark.asyncio
async def test_interruption_clears_audio_and_never_turns_into_a_transcript():
    async with server() as (url, relay, created, logs):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws)
            await receive(ws)
            created[0].queue.put_nowait(
                json.dumps(
                    {
                        "serverContent": {
                            "interrupted": True,
                            "inputTranscription": {"text": "PRIVATE_INPUT"},
                        }
                    }
                )
            )
            assert await receive(ws) == {"type": "clear"}
            await ws.send(json.dumps({"type": "stop"}))
            await ws.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", [{"type": "audio", "data": PCM, "sampleRate": 16000}, {"type": "unknown"}]
)
async def test_no_audio_before_browser_is_ready(bad):
    async with server() as (url, relay, created, logs):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws)
            await receive(ws)
            await ws.send(json.dumps(bad))
            assert (await receive(ws))["type"] == "error"
            await ws.wait_closed()
        assert created[0].sent == [lab.setup(CONFIG)]
        assert not relay.active


@pytest.mark.asyncio
async def test_second_call_cannot_share_context_or_create_another_google_session():
    async with server() as (url, relay, created, logs):
        async with connect(url, origin=ORIGIN, proxy=None) as one:
            await authorize(one)
            await receive(one)
            async with connect(url, origin=ORIGIN, proxy=None) as two:
                await authorize(two)
                assert (await receive(two))["type"] == "error"
            assert len(created) == 1 and relay.active
            await one.send(json.dumps({"type": "stop"}))
            await one.wait_closed()
        async with connect(url, origin=ORIGIN, proxy=None) as three:
            await authorize(three)
            assert (await receive(three))["type"] == "google_ready"
            await three.send(json.dumps({"type": "stop"}))
            await three.wait_closed()
        assert len(created) == 2 and all(item.closed for item in created)


@pytest.mark.asyncio
async def test_deadline_releases_google_session_and_stops_the_call():
    async with server(config=replace(CONFIG, max_seconds=0.08)) as (
        url,
        relay,
        created,
        logs,
    ):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws)
            await receive(ws)
            assert (await receive(ws))["type"] == "error"
            await ws.wait_closed()
        assert created[0].closed and not relay.active


@pytest.mark.asyncio
async def test_google_errors_are_sanitized_and_browser_disconnect_cleans_up():
    async with server(google_error=RuntimeError("PRIVATE_KEY_AND_COOKIE")) as (
        url,
        relay,
        created,
        logs,
    ):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws)
            response = await receive(ws)
            assert response["type"] == "error" and "PRIVATE" not in json.dumps(response)
        assert not relay.active
    async with server() as (url, relay, created, logs):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws)
            await receive(ws)
        for _ in range(20):
            if not relay.active:
                break
            await asyncio.sleep(0.005)
        assert not relay.active and created[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options",
    [
        {"port": 80},
        {"port": 0},
        {"model": "gemini-3.8-live-extended-thinking"},
        {"max_seconds": 1},
        {"max_seconds": 901},
        {"voice": "UNKNOWN"},
        {"voice": ["Kore"]},
    ],
)
async def test_invalid_lab_parameters_do_not_read_credentials(
    tmp_path, options, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("No credential reads")

    monkeypatch.setattr(lab, "google_key", forbidden)
    with pytest.raises(lab.CallLabError):
        await lab.run_lab(tmp_path, **options)


def end_request(tool_id="end-1", **patch):
    return {
        "toolCall": {
            "functionCalls": [
                {
                    "id": tool_id,
                    "name": "end_call",
                    "args": {"requested_by_caller": True},
                    **patch,
                }
            ]
        }
    }


async def caller_ready(ws):
    await ws.send(json.dumps({"type": "ready"}))
    assert (await receive(ws))["type"] == "audio"
    assert (await receive(ws))["type"] == "usage"
    await ws.send(json.dumps({"type": "audio", "data": PCM, "sampleRate": 16000}))
    await ws.send(json.dumps({"type": "ping"}))
    assert (await receive(ws))["type"] == "pong"


async def tool_response(google, count=1):
    for _ in range(100):
        responses = [
            item["toolResponse"] for item in google.sent if "toolResponse" in item
        ]
        if len(responses) >= count:
            return responses[-1]["functionResponses"][0]
        await asyncio.sleep(0.001)
    raise AssertionError("No tool response")


@pytest.mark.parametrize("model", lab.MODELS)
def test_end_call_is_only_declared_for_a_capable_browser(model):
    config = replace(CONFIG, model=model)
    assert "tools" not in lab.setup(config)["setup"]
    data = lab.setup(config, end_call_enabled=True)["setup"]
    assert data["tools"][0]["functionDeclarations"][0]["name"] == "end_call"
    assert data["systemInstruction"]["parts"][0]["text"].startswith(lab.SYSTEM)
    assert "PRIVATE" not in json.dumps(data)


@pytest.mark.asyncio
async def test_end_call_uses_an_opaque_request_and_waits_for_the_matching_browser_result():
    async with server() as (url, relay, created, logs):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws, capabilities=["end_call"])
            assert (await receive(ws))["type"] == "google_ready"
            assert created[0].sent == [lab.setup(CONFIG, end_call_enabled=True)]
            await caller_ready(ws)
            created[0].queue.put_nowait(json.dumps(end_request("PRIVATE_GOOGLE_ID")))
            request = await receive(ws)
            assert (
                set(request) == {"type", "requestId", "expiresAt"}
                and request["type"] == "end_call"
            )
            assert "PRIVATE" not in json.dumps(request)
            await ws.send(
                json.dumps(
                    {"type": "end_call_result", "requestId": "wrong", "ok": True}
                )
            )
            await ws.send(json.dumps({"type": "ping"}))
            assert await receive(ws) == {"type": "pong"}
            await ws.send(
                json.dumps(
                    {
                        "type": "end_call_result",
                        "requestId": request["requestId"],
                        "ok": True,
                    }
                )
            )
            await asyncio.wait_for(ws.wait_closed(), 1)
            result = await tool_response(created[0])
            assert result == {
                "id": "PRIVATE_GOOGLE_ID",
                "name": "end_call",
                "response": {"ok": True},
            }
        assert not relay.active and created[0].closed
        assert "PRIVATE" not in " ".join(logs)


@pytest.mark.asyncio
@pytest.mark.parametrize("capabilities", [None, [], ["other"], "end_call"])
async def test_old_or_incapable_browser_is_never_sent_a_hangup(capabilities):
    async with server() as (url, relay, created, logs):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws, capabilities=capabilities)
            await receive(ws)
            await caller_ready(ws)
            created[0].queue.put_nowait(json.dumps(end_request()))
            assert (await tool_response(created[0]))["response"] == {"ok": False}
            await ws.send(json.dumps({"type": "ping"}))
            assert await receive(ws) == {"type": "pong"}
            await ws.send(json.dumps({"type": "stop"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("ready", [False, True])
async def test_tool_cannot_hang_up_before_the_browser_has_sent_caller_audio(ready):
    async with server() as (url, relay, created, logs):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws, capabilities=["end_call"])
            await receive(ws)
            if ready:
                await ws.send(json.dumps({"type": "ready"}))
                await receive(ws)
                await receive(ws)
            created[0].queue.put_nowait(json.dumps(end_request()))
            assert (await tool_response(created[0]))["response"] == {"ok": False}
            await ws.send(json.dumps({"type": "ping"}))
            assert await receive(ws) == {"type": "pong"}
            await ws.send(json.dumps({"type": "stop"}))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch",
    [
        {"name": "other_function"},
        {"args": {}},
        {"args": None},
        {"args": {"requested_by_caller": False}},
        {"args": {"requested_by_caller": 1}},
        {"args": {"requested_by_caller": "true"}},
        {"args": {"requested_by_caller": True, "PRIVATE_TEXT": "DO_NOT_FORWARD"}},
    ],
)
async def test_unknown_tools_or_invalid_arguments_leave_the_call_running(patch):
    async with server() as (url, relay, created, logs):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws, capabilities=["end_call"])
            await receive(ws)
            await caller_ready(ws)
            created[0].queue.put_nowait(json.dumps(end_request(**patch)))
            assert (await tool_response(created[0]))["response"] == {"ok": False}
            await ws.send(json.dumps({"type": "ping"}))
            assert await receive(ws) == {"type": "pong"}
            assert relay.active
            await ws.send(json.dumps({"type": "stop"}))


@pytest.mark.asyncio
async def test_missing_hangup_button_and_duplicate_tool_id_do_not_close_the_ai_session():
    async with server() as (url, relay, created, logs):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws, capabilities=["end_call"])
            await receive(ws)
            await caller_ready(ws)
            created[0].queue.put_nowait(json.dumps(end_request()))
            request = await receive(ws)
            await ws.send(
                json.dumps(
                    {
                        "type": "end_call_result",
                        "requestId": request["requestId"],
                        "ok": False,
                    }
                )
            )
            assert (await tool_response(created[0]))["response"] == {"ok": False}
            created[0].queue.put_nowait(json.dumps(end_request()))
            assert (await tool_response(created[0], 2))["response"] == {"ok": False}
            await ws.send(json.dumps({"type": "ping"}))
            assert await receive(ws) == {"type": "pong"}
            assert relay.active
            await ws.send(json.dumps({"type": "stop"}))


@pytest.mark.asyncio
async def test_timed_out_control_and_late_acknowledgement_cannot_end_a_call(
    monkeypatch,
):
    monkeypatch.setattr(lab, "CONTROL_TIMEOUT", 0.01)
    async with server() as (url, relay, created, logs):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws, capabilities=["end_call"])
            await receive(ws)
            await caller_ready(ws)
            created[0].queue.put_nowait(json.dumps(end_request()))
            request = await receive(ws)
            assert (await tool_response(created[0]))["response"] == {"ok": False}
            await ws.send(
                json.dumps(
                    {
                        "type": "end_call_result",
                        "requestId": request["requestId"],
                        "ok": True,
                    }
                )
            )
            await ws.send(json.dumps({"type": "ping"}))
            assert await receive(ws) == {"type": "pong"}
            assert relay.active
            await ws.send(json.dumps({"type": "stop"}))


@pytest.mark.asyncio
async def test_plain_text_transcripts_or_inline_function_parts_never_hang_up_a_call():
    async with server() as (url, relay, created, logs):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws, capabilities=["end_call"])
            await receive(ws)
            await caller_ready(ws)
            created[0].queue.put_nowait(
                json.dumps(
                    {
                        "serverContent": {
                            "inputTranscription": {"text": "ngắt cuộc gọi đi"},
                            "outputTranscription": {"text": "end_call"},
                            "modelTurn": {
                                "parts": [
                                    {
                                        "functionCall": end_request()["toolCall"][
                                            "functionCalls"
                                        ][0]
                                    }
                                ]
                            },
                        }
                    }
                )
            )
            await ws.send(json.dumps({"type": "ping"}))
            assert await receive(ws) == {"type": "pong"}
            await ws.send(json.dumps({"type": "stop"}))


@pytest.mark.asyncio
async def test_stop_cancels_a_pending_end_request_without_waiting_for_its_timeout():
    async with server() as (url, relay, created, logs):
        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws, capabilities=["end_call"])
            await receive(ws)
            await caller_ready(ws)
            created[0].queue.put_nowait(json.dumps(end_request()))
            assert (await receive(ws))["type"] == "end_call"
            await ws.send(json.dumps({"type": "stop"}))
            await asyncio.wait_for(ws.wait_closed(), 1)
        assert not relay.active and created[0].closed
