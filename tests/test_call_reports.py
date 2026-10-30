import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import httpx
import pytest

import setup_call_vps as installer
from messenger_ai.call_lab import setup
from messenger_ai.call_reports import (
    CallReporter,
    CallTranscript,
    ReportSender,
    SummaryOptions,
    read_report,
    write_report,
    MAX_TRANSCRIPT,
)
from messenger_ai.config import Settings
from messenger_ai.facebook import FacebookTransport
from messenger_ai.state import State
from test_call_lab import CONFIG, ORIGIN, PCM, authorize, receive, server


def transcript():
    value = CallTranscript()
    value.start()
    value.add("caller", "Nhắc Mạnh xem lịch hẹn ngày mai giúp mình.")
    value.add("assistant", "Mình chưa thể xác nhận lịch thay Mạnh.")
    return value


def test_transcription_is_explicit_opt_in_and_private_path_never_goes_to_google(
    tmp_path,
):
    assert "inputAudioTranscription" not in setup(CONFIG)["setup"]
    selected = replace(CONFIG, summary=SummaryOptions(tmp_path))
    data = setup(selected)["setup"]
    assert data["inputAudioTranscription"] == data["outputAudioTranscription"] == {}
    assert str(tmp_path) not in json.dumps(data)
    assert "PRIVATE" not in repr(selected)
    memory = CallTranscript()
    memory.add("caller", "Must ignore before ready")
    assert not memory.turns
    memory.start()
    memory.add("caller", "a" * (MAX_TRANSCRIPT + 100))
    assert memory.truncated and len(memory.text()) < MAX_TRANSCRIPT + 30
    assert "aaaa" not in repr(memory)


@pytest.mark.asyncio
async def test_google_summary_is_one_bounded_request_without_tools_or_persona(tmp_path):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        assert (
            request.url
            == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
        )
        assert request.headers["x-goog-api-key"] == "PRIVATE_KEY"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {"thought": True, "text": "PRIVATE_THOUGHT"},
                                {
                                    "text": "Người gọi đề nghị Mạnh kiểm tra lịch hẹn ngày mai; chưa xác nhận lịch."
                                },
                            ]
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reporter = CallReporter(
            SummaryOptions(tmp_path), "PRIVATE_KEY", client=client, log=lambda _: None
        )
        memory = transcript()
        await reporter.finish(memory, 20)
    reports = list(tmp_path.glob("*.json"))
    assert len(captured) == len(reports) == 1
    assert "tools" not in captured[0]
    report = read_report(reports[0])
    assert "chưa xác nhận lịch" in report["body"] and "PRIVATE" not in report["body"]
    assert stat.S_IMODE(reports[0].stat().st_mode) == 0o640
    assert not memory.turns


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,reason", [(429, None), (200, "MAX_TOKENS"), (302, None)]
)
async def test_failed_or_redirected_summary_preserves_a_labeled_excerpt_without_retrying(
    tmp_path, status, reason
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"location": "https://example.com/"},
            json={"candidates": [{"finishReason": reason}]},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    ) as client:
        reporter = CallReporter(
            SummaryOptions(tmp_path), "KEY", client=client, log=lambda _: None
        )
        await reporter.finish(transcript(), 2)
    assert len(calls) == 1
    body = read_report(next(tmp_path.glob("*.json")))["body"]
    assert "Chưa tạo được tóm tắt bằng AI" in body and "xem lịch hẹn" in body


@pytest.mark.asyncio
async def test_queue_sends_only_to_verified_self_once_and_ignores_echo(tmp_path):
    path = write_report(tmp_path, "Tóm tắt thử công khai", 1800000000, 20)
    state = State(tmp_path / "state/db.sqlite3")
    calls = []

    async def send(jid, text):
        calls.append((jid, text))
        return {"messageId": "notice-1"}

    transport = FacebookTransport("", tmp_path / "device", tmp_path / "bridge")
    transport.own_id = "111"
    transport.listener = SimpleNamespace(send_e2ee_message=send)
    settings = Settings(
        call_summary_inbox=str(tmp_path), call_summary_owner_id="111", dry_run=False
    )
    sender = ReportSender(settings, state, transport, log=lambda _: None)
    await sender.tick()
    await sender.tick()
    assert calls == [("111@msgr", "Tóm tắt thử công khai")] and not path.exists()
    assert state.bot_echo(
        "e2ee:111@msgr", "notice-1", "Tóm tắt thử công khai", 1800000000
    )
    state.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run,owner", [(True, "111"), (False, "222")])
async def test_preview_or_changed_account_never_sends_summary(tmp_path, dry_run, owner):
    path = write_report(tmp_path, "PRIVATE_REPORT", 1800000000, 1)
    state = State(tmp_path / "data/db")

    async def forbidden(*args):
        pytest.fail("Must not send")

    settings = Settings(
        call_summary_inbox=str(tmp_path), call_summary_owner_id=owner, dry_run=dry_run
    )
    logs = []
    sender = ReportSender(
        settings,
        state,
        SimpleNamespace(own_id="111", notify_owner=forbidden),
        log=logs.append,
    )
    await sender.tick()
    assert path.exists() and "PRIVATE_REPORT" not in " ".join(logs)
    state.close()


@pytest.mark.asyncio
async def test_reconnecting_transport_keeps_summary_pending_without_attempting_send(
    tmp_path,
):
    path = write_report(tmp_path, "Report", 1800000000, 1)
    state = State(tmp_path / "data/db")

    async def forbidden(*args):
        pytest.fail("Must wait for Messenger to reconnect")

    transport = SimpleNamespace(
        own_id="111",
        listener=SimpleNamespace(connection_state="reconnecting"),
        notify_owner=forbidden,
    )
    settings = Settings(
        call_summary_inbox=str(tmp_path), call_summary_owner_id="111", dry_run=False
    )
    await ReportSender(settings, state, transport).tick()
    assert path.exists() and state.report_status(path.stem) is None
    state.close()


@pytest.mark.asyncio
async def test_unknown_delivery_is_kept_for_review_and_never_replayed_even_after_restart(
    tmp_path,
):
    original = write_report(tmp_path, "Private report", 1800000000, 10)
    original_bytes = original.read_bytes()
    state = State(tmp_path / "data/db")
    calls = []

    async def timeout(text):
        calls.append(text)
        raise TimeoutError("PRIVATE_FAILURE")

    settings = Settings(
        call_summary_inbox=str(tmp_path), call_summary_owner_id="111", dry_run=False
    )
    transport = SimpleNamespace(own_id="111", notify_owner=timeout)
    sender = ReportSender(settings, state, transport, log=lambda _: None)
    await sender.tick()
    assert len(list(tmp_path.glob("*.unknown.json"))) == 1 and not original.exists()
    original.write_bytes(original_bytes)
    state.close()
    state = State(tmp_path / "data/db")
    await ReportSender(settings, state, transport, log=lambda _: None).tick()
    assert len(calls) == 1
    state.close()


@pytest.mark.asyncio
async def test_two_consumers_cannot_send_one_report_twice(tmp_path):
    write_report(tmp_path, "Summary", 1800000000, 10)
    states = [State(tmp_path / f"data{i}/db") for i in range(2)]
    calls = []

    async def send(text):
        calls.append(text)
        await asyncio.sleep(0)
        return {"id": "sent"}

    settings = Settings(
        call_summary_inbox=str(tmp_path), call_summary_owner_id="111", dry_run=False
    )
    transport = SimpleNamespace(own_id="111", notify_owner=send)
    await asyncio.gather(
        *(ReportSender(settings, state, transport).tick() for state in states)
    )
    assert calls == ["Summary"]
    for state in states:
        state.close()


def test_invalid_summary_files_and_symlinks_are_rejected(tmp_path):
    path = write_report(tmp_path, "Summary", 1800000000, 1)
    link = tmp_path / ("a" * 32 + ".json")
    link.symlink_to(path)
    with pytest.raises((ValueError, OSError)):
        read_report(link)
    data = json.loads(path.read_text())
    data["id"] = "wrong"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_report(path)


@pytest.mark.asyncio
async def test_real_relay_captures_only_after_ready_and_enqueues_after_stop_without_blocking_next_call(
    tmp_path, monkeypatch
):
    captured = []

    async def summarize(self, memory):
        captured.append(memory.text())
        return "Người gọi đề nghị xem lịch; chưa xác nhận."

    monkeypatch.setattr(CallReporter, "summarize", summarize)
    config = replace(CONFIG, summary=SummaryOptions(tmp_path))
    async with server(config=config) as (url, relay, created, logs):
        from websockets.asyncio.client import connect

        async with connect(url, origin=ORIGIN, proxy=None) as ws:
            await authorize(ws)
            await receive(ws)
            created[0].queue.put_nowait(
                json.dumps(
                    {
                        "serverContent": {
                            "inputTranscription": {"text": "PRIVATE_BEFORE_READY"}
                        }
                    }
                )
            )
            await ws.send(json.dumps({"type": "ping"}))
            await receive(ws)
            await ws.send(json.dumps({"type": "ready"}))
            await receive(ws)
            await receive(ws)
            await ws.send(
                json.dumps({"type": "audio", "sampleRate": 16000, "data": PCM})
            )
            created[0].queue.put_nowait(
                json.dumps(
                    {
                        "serverContent": {
                            "inputTranscription": {"text": "Nhờ xem lịch ngày mai."}
                        }
                    }
                )
            )
            await ws.send(json.dumps({"type": "ping"}))
            await receive(ws)
            await ws.send(json.dumps({"type": "stop"}))
            await ws.wait_closed()
        assert not relay.active
        await relay.close()
        assert (
            captured
            and "xem lịch" in captured[0]
            and "PRIVATE_BEFORE_READY" not in captured[0]
        )
        assert len(list(tmp_path.glob("*.json"))) == 1
        assert all("xem lịch" not in line for line in logs)


def test_installer_creates_isolated_delivery_route_without_copying_cookie(
    tmp_path, monkeypatch
):
    root = tmp_path / "bot"
    root.mkdir()
    (root / "config.json").write_text("{}")
    (root / "secrets.json").write_text(
        json.dumps({"facebook_cookie": "c_user=111; xs=PRIVATE_SECRET;"})
    )
    monkeypatch.setattr(installer, "ROOT", root)
    monkeypatch.setattr(installer, "REPORT_SPOOL", tmp_path / "spool")
    account = SimpleNamespace(pw_uid=os.getuid())
    route = Path(installer.prepare_summary_route(account))
    raw = json.loads((root / "config.json").read_text())
    assert raw["call_summary_owner_id"] == "111" and raw["call_summary_inbox"] == str(
        route
    )
    assert "PRIVATE_SECRET" not in json.dumps(raw)
    assert stat.S_IMODE(route.stat().st_mode) == 0o2770
    assert installer.prepare_summary_route(account) == str(route)
    enabled = installer.settings(
        {}, "KEY", "/bin/chrome", summary_enabled=True, summary_outbox=str(route)
    )
    assert installer.settings(enabled, "KEY", "/bin/chrome")["summary_enabled"] is True
    assert (
        installer.settings(enabled, "KEY", "/bin/chrome", summary_enabled=False)[
            "summary_enabled"
        ]
        is False
    )
