import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from messenger_ai import cli
from messenger_ai.call_reports import CallPeer, ReportSender, write_report
from messenger_ai.config import Settings
from messenger_ai.facebook import FacebookTransport
from messenger_ai.state import State


@pytest.fixture
def case(tmp_path):
    inbox = tmp_path / "reports"
    inbox.mkdir()
    state = State(tmp_path / "state.sqlite3")
    calls, logs = [], []

    async def send(jid, text):
        calls.append((jid, text))
        return {"messageId": "summary-" + str(len(calls))}

    transport = FacebookTransport("", tmp_path / "device", tmp_path / "bridge")
    transport.own_id = "111"
    transport.listener = SimpleNamespace(
        connection_state="connected", send_e2ee_message=send
    )
    settings = Settings(
        call_summary_inbox=str(inbox),
        call_summary_owner_id="111",
        call_summary_target="caller",
        dry_run=False,
    )
    yield SimpleNamespace(
        root=tmp_path,
        inbox=inbox,
        state=state,
        calls=calls,
        logs=logs,
        transport=transport,
        settings=settings,
    )
    state.close()


def pending(case):
    return write_report(
        case.inbox,
        "PRIVATE_CALL_WORDS",
        1800000000,
        40,
        target="caller",
        peer=CallPeer("111", "222"),
    )


@pytest.mark.asyncio
async def test_enabling_summary_route_during_a_live_process_sends_without_restart(case):
    loaded = {"settings": Settings()}
    initial = replace(
        case.settings,
        call_summary_inbox="",
        call_summary_owner_id="",
        call_summary_target="self",
    )
    sender = ReportSender(
        initial,
        case.state,
        case.transport,
        log=case.logs.append,
        settings_loader=lambda: loaded["settings"],
    )
    path = pending(case)
    await sender.tick()
    assert path.exists() and not case.calls
    loaded["settings"] = replace(case.settings, dry_run=True, model="OTHER_MODEL")
    await sender.tick()
    await sender.tick()
    assert case.calls == [("222@msgr", "PRIVATE_CALL_WORDS")] and not path.exists()
    assert sender.settings.dry_run is False and sender.settings.model != "OTHER_MODEL"
    assert sum("đã nạp lại cấu hình hộp gửi" in line for line in case.logs) == 1
    assert "PRIVATE_CALL_WORDS" not in " ".join(case.logs)


@pytest.mark.asyncio
async def test_live_routing_reload_cannot_override_an_explicit_preview_process(case):
    sender = ReportSender(
        replace(case.settings, dry_run=True),
        case.state,
        case.transport,
        log=case.logs.append,
        settings_loader=lambda: case.settings,
    )
    path = pending(case)
    await sender.tick()
    assert path.exists() and not case.calls and sender.settings.dry_run is True


@pytest.mark.asyncio
async def test_changed_account_pauses_then_resumes_the_same_recipient_without_rebinding(
    case,
):
    loaded = {"settings": replace(case.settings, call_summary_owner_id="333")}
    sender = ReportSender(
        case.settings,
        case.state,
        case.transport,
        log=case.logs.append,
        settings_loader=lambda: loaded["settings"],
    )
    path = pending(case)
    await sender.tick()
    assert path.exists() and not case.calls
    loaded["settings"] = case.settings
    await sender.tick()
    assert case.calls == [("222@msgr", "PRIVATE_CALL_WORDS")] and not path.exists()


@pytest.mark.asyncio
async def test_disabling_route_keeps_a_report_pending_until_enabled_again(case):
    loaded = {"settings": replace(case.settings, call_summary_inbox="")}
    sender = ReportSender(
        case.settings,
        case.state,
        case.transport,
        log=case.logs.append,
        settings_loader=lambda: loaded["settings"],
    )
    path = pending(case)
    await sender.tick()
    assert path.exists() and case.state.report_status(path.stem) is None
    loaded["settings"] = case.settings
    await sender.tick()
    assert len(case.calls) == 1 and not path.exists()


@pytest.mark.asyncio
async def test_changing_target_does_not_redirect_a_queued_caller_report_to_self(case):
    sender = ReportSender(
        case.settings,
        case.state,
        case.transport,
        log=case.logs.append,
        settings_loader=lambda: replace(case.settings, call_summary_target="self"),
    )
    path = pending(case)
    await sender.tick()
    assert not case.calls and path.with_suffix(".unrouted.json").exists()


@pytest.mark.asyncio
async def test_invalid_config_pauses_sending_and_logs_no_raw_error_or_repeated_spam(
    case,
):
    def invalid():
        raise ValueError("PRIVATE_CONFIG_SECRET")

    sender = ReportSender(
        case.settings,
        case.state,
        case.transport,
        log=case.logs.append,
        settings_loader=invalid,
    )
    path = pending(case)
    await sender.tick()
    await sender.tick()
    assert not case.calls and path.exists() and len(case.logs) == 1
    assert "PRIVATE_CONFIG_SECRET" not in " ".join(case.logs)
    sender.settings_loader = lambda: case.settings
    await sender.tick()
    assert len(case.calls) == 1 and not path.exists()
    assert any("cấu hình đã hợp lệ trở lại" in line for line in case.logs)


@pytest.mark.asyncio
async def test_live_e2ee_readiness_controls_waiting_and_resumes_without_restarting(
    case,
):
    handshake = {"ready": False}
    probes = []

    def check(timeout, *, require_e2ee):
        probes.append((timeout, require_e2ee))
        return handshake["ready"]

    case.transport.listener.wait_until_connected = check
    sender = ReportSender(
        case.settings, case.state, case.transport, log=case.logs.append
    )
    path = pending(case)
    for _ in range(3):
        await sender.tick()
    assert (
        not case.calls and path.exists() and case.state.report_status(path.stem) is None
    )
    assert sum("đợi kết nối Messenger mã hóa" in line for line in case.logs) == 1
    case.transport.listener.connection_state = "reconnecting"
    handshake["ready"] = True
    await sender.tick()
    await sender.tick()
    assert case.calls == [("222@msgr", "PRIVATE_CALL_WORDS")] and not path.exists()
    assert all(probe == (0, True) for probe in probes)
    assert any("đã sẵn sàng trở lại" in line for line in case.logs)


@pytest.mark.parametrize("status", ["auth_required", "fatal", "stopped", {}])
def test_terminal_or_invalid_sdk_state_cannot_be_overridden_by_stale_ready_events(
    case, status
):
    case.transport.listener.connection_state = status
    case.transport.listener.wait_until_connected = lambda *args, **kwargs: True
    assert not case.transport.notification_ready()


@pytest.mark.asyncio
async def test_disconnect_between_queued_reports_keeps_remaining_reports_unclaimed(
    case,
):
    handshake = {"ready": True}
    case.transport.listener.wait_until_connected = lambda *args, **kwargs: handshake[
        "ready"
    ]
    send = case.transport.listener.send_e2ee_message

    async def disconnect_after_send(jid, text):
        result = await send(jid, text)
        handshake["ready"] = False
        return result

    case.transport.listener.send_e2ee_message = disconnect_after_send
    paths = sorted([pending(case), pending(case)])
    sender = ReportSender(
        case.settings, case.state, case.transport, log=case.logs.append
    )
    await sender.tick()
    assert len(case.calls) == 1 and not paths[0].exists() and paths[1].exists()
    assert case.state.report_status(paths[1].stem) is None
    assert not list(case.inbox.glob("*.unknown.json"))
    handshake["ready"] = True
    await sender.tick()
    await sender.tick()
    assert len(case.calls) == 2 and not paths[1].exists()


@pytest.mark.asyncio
async def test_stopped_or_closed_listener_cannot_send_even_with_ready_events(case):
    case.transport.listener.wait_until_connected = lambda *args, **kwargs: True
    case.transport.task = asyncio.get_running_loop().create_future()
    case.transport.task.set_result(None)
    assert not case.transport.notification_ready()
    case.transport.task = None
    case.transport.closing = True
    assert not case.transport.notification_ready()
    case.transport.closing = False
    case.transport.listener = None
    assert not case.transport.notification_ready()


@pytest.mark.asyncio
async def test_sdk_handshake_failure_keeps_report_unclaimed_without_exposing_errors(
    case,
):
    def failed(*args, **kwargs):
        raise RuntimeError("PRIVATE_SDK_SECRET")

    case.transport.listener.wait_until_connected = failed
    path = pending(case)
    await ReportSender(
        case.settings, case.state, case.transport, log=case.logs.append
    ).tick()
    assert (
        path.exists() and not case.calls and case.state.report_status(path.stem) is None
    )
    assert "PRIVATE_SDK_SECRET" not in " ".join(case.logs)


@pytest.mark.asyncio
async def test_invalid_report_is_visible_but_private_and_is_sent_once_after_repair(
    case,
):
    bad = case.inbox / ("a" * 32 + ".json")
    bad.write_text("PRIVATE_BROKEN_JSON")
    sender = ReportSender(
        case.settings, case.state, case.transport, log=case.logs.append
    )
    await sender.tick()
    await sender.tick()
    assert not case.calls and len(case.logs) == 1
    assert "PRIVATE_BROKEN_JSON" not in " ".join(case.logs)
    good = pending(case)
    data = json.loads(good.read_text())
    data["id"] = bad.stem
    bad.write_text(json.dumps(data))
    good.unlink()
    await sender.tick()
    await sender.tick()
    assert len(case.calls) == 1 and not bad.exists()


@pytest.mark.asyncio
async def test_unreadable_inbox_logs_safe_reason_then_resumes_after_access_is_restored(
    case, monkeypatch
):
    path = pending(case)
    sender = ReportSender(
        case.settings, case.state, case.transport, log=case.logs.append
    )

    def forbidden(*args):
        raise PermissionError("PRIVATE_PATH_OR_KEY")

    with monkeypatch.context() as patch:
        patch.setattr("messenger_ai.call_reports.os.scandir", forbidden)
        await sender.tick()
        await sender.tick()
    assert path.exists() and not case.calls and len(case.logs) == 1
    assert "PRIVATE_PATH_OR_KEY" not in " ".join(case.logs)
    await sender.tick()
    assert len(case.calls) == 1 and not path.exists()


@pytest.mark.asyncio
async def test_cli_keeps_the_reader_alive_when_call_routing_is_enabled_after_start(
    case, monkeypatch, capsys
):
    loaded = {
        "settings": replace(
            case.settings,
            reply_scope="all_private",
            dry_run=True,
            call_summary_inbox="",
            call_summary_owner_id="",
            call_summary_target="self",
        )
    }
    sent = asyncio.Event()
    paths = []

    async def notify(recipient, body):
        case.calls.append((recipient, body))
        sent.set()
        return {"messageId": "cli-summary"}

    async def events():
        loaded["settings"] = replace(case.settings, dry_run=True)
        paths.append(pending(case))
        await asyncio.wait_for(sent.wait(), 1)
        if False:
            yield {}

    transport = SimpleNamespace(
        own_id="111",
        connect=AsyncMock(),
        close=AsyncMock(),
        listener=SimpleNamespace(connection_state="connected"),
        events=events,
        notify_caller=notify,
    )
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: loaded["settings"]))
    monkeypatch.setattr(cli, "ROOT", case.root)
    monkeypatch.setattr(cli, "load_persona", lambda _: "Test persona")
    monkeypatch.setattr(
        cli, "load_secrets", lambda: {"facebook_cookie": "PRIVATE_COOKIE"}
    )
    monkeypatch.setattr(
        "scripts.fetch_assets.ensure_bridge", lambda: case.root / "bridge"
    )
    monkeypatch.setattr(
        "messenger_ai.facebook.FacebookTransport", lambda *args: transport
    )
    monkeypatch.setattr(
        "messenger_ai.ai.create_ai",
        lambda *args: SimpleNamespace(description="Test AI", close=AsyncMock()),
    )
    monkeypatch.setattr("messenger_ai.ai.create_vision_ai", lambda *args: None)
    await asyncio.wait_for(cli.run(discovery=False, live=True, preview=False), 2)
    assert case.calls == [("222", "PRIVATE_CALL_WORDS")] and not paths[0].exists()
    output = capsys.readouterr().out
    assert "bộ gửi nền đã khởi động" in output
    assert "PRIVATE_CALL_WORDS" not in output and "PRIVATE_COOKIE" not in output
