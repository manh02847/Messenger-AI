import asyncio
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.diagnose_messenger import (
    HiddenOutput,
    Metrics,
    collect,
    main,
    private_stderr,
    verified_binary,
)


@pytest.mark.parametrize(
    "line,code",
    [
        (
            "Unable to verify ciphertext mac: mismatching MAC in signal message",
            "SIGNAL_MAC_INVALID",
        ),
        ("no valid sessions", "SIGNAL_NO_VALID_SESSION"),
        ("no session found for user PRIVATE_USER", "SIGNAL_NO_VALID_SESSION"),
        ("uninitialized session", "SIGNAL_NO_VALID_SESSION"),
        ("untrusted identity PRIVATE_IDENTITY", "SIGNAL_IDENTITY_UNTRUSTED"),
        ("prekey store didn't return one-time key", "SIGNAL_PREKEY_MISSING"),
        ("no sender key", "SIGNAL_SENDER_KEY_MISSING"),
        ("received message with old counter", "SIGNAL_OLD_COUNTER"),
        ("wrong message version", "SIGNAL_VERSION_UNSUPPORTED"),
        ("[bridge] bad json (122 bytes): PRIVATE_PAYLOAD", "BRIDGE_NON_JSON_LINE"),
    ],
)
def test_public_signal_error_phrases_become_only_fixed_codes(line, code):
    metrics = Metrics()
    hidden = HiddenOutput(metrics)
    hidden.write(line + " c_user=PRIVATE_COOKIE xs=PRIVATE_TOKEN\n")
    result = json.dumps(metrics.report())
    assert metrics.counts[code] == 1
    assert "PRIVATE" not in result and "c_user" not in result


def test_split_and_oversized_log_lines_are_bounded_and_never_echoed(capsys):
    metrics = Metrics()
    hidden = HiddenOutput(metrics)
    with redirect_stdout(hidden), redirect_stderr(hidden):
        sys.stdout.write("mismatching MA")
        sys.stderr.write("C in signal message PRIVATE_KEY\n")
        print("PRIVATE_BODY" * 10000)
        print("completely unrelated PRIVATE_VALUE")
    hidden.finish()
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert hidden.pending == "" and metrics.counts["SIGNAL_MAC_INVALID"] == 1
    assert metrics.counts["OVERSIZED_LOG_LINES_HIDDEN"] == 1
    assert "PRIVATE" not in json.dumps(metrics.report())


def test_raw_event_retains_only_counts_and_bounded_internal_message_ids():
    metrics = Metrics()
    metrics.own_id = "111"
    raw = {
        "type": "raw",
        "data": {
            "from": "whatsmeow",
            "type": "UndecryptableMessage",
            "data": {
                "IsUnavailable": False,
                "Info": {
                    "ID": "PRIVATE_MID",
                    "IsFromMe": False,
                    "Sender": "PRIVATE_JID",
                    "PushName": "PRIVATE_NAME",
                },
                "body": "PRIVATE_BODY",
            },
        },
    }
    metrics.event(raw)
    metrics.event(raw)
    metrics.event({"type": "error", "data": {"code": 2, "message": "PRIVATE_ERROR"}})
    metrics.event(
        {
            "type": "message",
            "data": {"senderId": 111, "threadType": 0, "text": "PRIVATE_TEXT"},
        }
    )
    metrics.event(
        {
            "type": "message",
            "data": {"senderId": 222, "threadType": 13, "text": "PRIVATE_TEXT"},
        }
    )
    report = metrics.report()
    assert report["unique_failed_messages"] == 1
    assert report["counts"]["REMOTE_UNDECRYPTABLE_EVENTS"] == 2
    assert report["counts"]["OWNER_CHAT_TYPE_UNKNOWN_OR_GROUP"] == 1
    assert "PRIVATE" not in json.dumps(report) and "111" not in json.dumps(report)


def test_binary_preflight_checks_only_pinned_original_or_patched_bytes(tmp_path):
    path = tmp_path / "bin/bridge"
    path.parent.mkdir()
    path.write_bytes(b"public fixture binary")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"sha256": {"bridge": digest}}
    assert verified_binary(tmp_path, manifest, "bridge") == path
    manifest["sha256"]["bridge"] = "wrong"
    with pytest.raises(ValueError, match="BRIDGE_NOT_VERIFIED"):
        verified_binary(tmp_path, manifest, "bridge")
    manifest["bridge_patches"] = {"bridge": {"sha256": digest}}
    assert verified_binary(tmp_path, manifest, "bridge") == path


@pytest.mark.asyncio
async def test_observer_uses_existing_device_and_never_exposes_or_sends_content(
    tmp_path, capsys
):
    metrics = Metrics()
    hidden = HiddenOutput(metrics)
    stopped = asyncio.Event()
    ready_calls = []
    metrics.on_ready = lambda: ready_calls.append(True)
    instances = []
    loop = asyncio.get_running_loop()

    class Listener:
        def __init__(self, data, **kwargs):
            self.kwargs = kwargs
            instances.append(self)

        def on_message(self, callback):
            self.callback = callback

        def wait_until_connected(self, *args, **kwargs):
            return True

        async def connect_mqtt(self):
            print(
                "[bridge] bad json (122 bytes): Unable to verify ciphertext mac: PRIVATE_KEY",
                file=sys.stderr,
            )
            self.callback(
                {
                    "type": "message",
                    "data": {"senderId": 222, "text": "PRIVATE_MESSAGE"},
                }
            )
            await stopped.wait()

        def stop(self):
            loop.call_soon_threadsafe(stopped.set)

    sdk = SimpleNamespace(
        dataGetHome=AsyncMock(return_value={"FacebookID": "111"}),
        listeningE2EEEvent=Listener,
    )
    with redirect_stdout(hidden), redirect_stderr(hidden):
        await collect(
            sdk,
            "PRIVATE_COOKIE",
            tmp_path / "existing-device.db",
            tmp_path / "bridge",
            metrics,
            0.01,
        )
    hidden.finish()
    assert metrics.ready and metrics.closed
    assert ready_calls == [True]
    assert instances[0].kwargs == {
        "binary_path": str(tmp_path / "bridge"),
        "device_path": str(tmp_path / "existing-device.db"),
        "e2ee_memory_only": False,
        "log_level": "warn",
        "debug_errors": True,
    }
    assert "PRIVATE" not in json.dumps(metrics.report())
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.asyncio
async def test_startup_failure_closes_the_listener_without_printing_the_exception(
    tmp_path,
):
    metrics = Metrics()

    class Listener:
        def __init__(self, *args, **kwargs):
            pass

        def on_message(self, callback):
            pass

        def wait_until_connected(self, *args, **kwargs):
            raise ValueError("PRIVATE_STARTUP_ERROR")

        async def connect_mqtt(self):
            await asyncio.Future()

        def stop(self):
            # Cancellation of an inactive mock listener is handled by the worker.
            pass

    listener_task = None

    class StoppingListener(Listener):
        async def connect_mqtt(self):
            nonlocal listener_task
            listener_task = asyncio.current_task()
            await asyncio.Future()

        def stop(self):
            loop.call_soon_threadsafe(listener_task.cancel)

    loop = asyncio.get_running_loop()
    sdk = SimpleNamespace(
        dataGetHome=AsyncMock(return_value={"FacebookID": "111"}),
        listeningE2EEEvent=StoppingListener,
    )
    with pytest.raises((ValueError, asyncio.CancelledError)):
        await collect(
            sdk,
            "PRIVATE_COOKIE",
            tmp_path / "device",
            tmp_path / "bridge",
            metrics,
            0.01,
        )
    assert metrics.closed and "PRIVATE" not in json.dumps(metrics.report())


def test_main_emits_only_a_safe_report_when_preflight_fails(monkeypatch, capsys):
    monkeypatch.setattr(
        "scripts.diagnose_messenger.importlib.metadata.version", lambda _: "unsupported"
    )
    assert main(["--seconds", "10"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed" and report["step"] == "preflight"
    assert report["counts"]["SDK_NOT_PINNED"] == 1


@pytest.mark.asyncio
async def test_actual_pinned_sdk_bridge_reader_reports_mac_without_exposing_raw_payload(
    tmp_path, capsys
):
    from fbchat_v2._messaging._listening_e2ee import _BridgeProcess

    # Run the real SDK's pipe readers/validator against a synthetic executable.
    path = tmp_path / "fake_bridge.py"
    path.write_text("""import json, sys, time
for line in sys.stdin:
    r = json.loads(line)
    data = {'protocolVersion': 1, 'bridgeVersion': '2.3.4', 'capabilities': ['newClient', 'connect', 'connectE2EE', 'isConnected', 'events', 'structuredConnectionStatus']}
    if r['method'] != 'hello':
        data = {'connected': True, 'e2eeConnected': True}
    print(json.dumps({'id': r['id'], 'ok': True, 'data': data}), flush=True)
    if r['method'] == 'hello':
        print('[ERROR] 2026-11-03T08:55:48Z SessionCipher.go:123 Unable to verify ciphertext mac: mismatching MAC in signal message PRIVATE_ID PRIVATE_COOKIE', flush=True)
        sys.stderr.write('Error decrypting message PRIVATE_MESSAGE from PRIVATE_JID: no valid sessions\\n')
        sys.stderr.flush()
""")
    metrics, hidden = Metrics(), None
    hidden = HiddenOutput(metrics)
    previous_stderr = vars(_BridgeProcess)["_log_stderr_line"]
    with redirect_stdout(hidden), redirect_stderr(hidden), private_stderr(metrics):
        bridge = _BridgeProcess(
            Path(sys.executable), command=[sys.executable, str(path)], log_stderr=True
        )
        try:
            await asyncio.to_thread(bridge._validate_contract)
            for _ in range(100):
                if (
                    metrics.counts["SIGNAL_MAC_INVALID"]
                    and metrics.counts["SIGNAL_NO_VALID_SESSION"]
                ):
                    break
                await asyncio.sleep(0.005)
        finally:
            await asyncio.to_thread(bridge.close)
    hidden.finish()
    assert vars(_BridgeProcess)["_log_stderr_line"] is previous_stderr
    report = metrics.report()
    assert report["counts"]["BRIDGE_NON_JSON_LINE"] == 1
    assert report["counts"]["SIGNAL_MAC_INVALID"] == 1
    assert report["counts"]["SIGNAL_NO_VALID_SESSION"] == 1
    assert "PRIVATE" not in json.dumps(report)
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def prepare_main(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.fetch_assets.ROOT", tmp_path)
    monkeypatch.setattr("scripts.fetch_assets.bridge_name", lambda: "fixture")
    monkeypatch.setattr(
        "scripts.diagnose_messenger.verified_binary",
        lambda root, manifest, name: root / "fixture",
    )
    monkeypatch.setattr(
        "scripts.diagnose_messenger.importlib.metadata.version", lambda _: "2.3.4"
    )
    monkeypatch.setattr(
        "messenger_ai.config.load_secrets",
        lambda root: {"facebook_cookie": "PRIVATE_COOKIE"},
    )


def test_main_hides_stdout_stderr_and_reports_only_codes(monkeypatch, tmp_path, capsys):
    prepare_main(monkeypatch, tmp_path)

    async def fake_collect(sdk, cookie, device, binary, metrics, seconds):
        assert (
            cookie == "PRIVATE_COOKIE"
            and device == tmp_path / "data/messenger-device.db"
        )
        assert seconds == 10
        print("mismatching MAC in signal message PRIVATE_PAYLOAD c_user=PRIVATE_COOKIE")
        print("PRIVATE_SECRET PRIVATE_MESSAGE", file=sys.stderr)
        metrics.ready = metrics.closed = True

    monkeypatch.setattr("scripts.diagnose_messenger.collect", fake_collect)
    assert main(["--seconds", "10"]) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and "PRIVATE" not in captured.out
    report = json.loads(captured.out)
    assert report["status"] == "complete" and report["listener_closed"]
    assert report["counts"]["SIGNAL_MAC_INVALID"] == 1


def test_main_refuses_an_existing_bot_lock_before_connecting(
    monkeypatch, tmp_path, capsys
):
    from messenger_ai.cli import instance_lock

    prepare_main(monkeypatch, tmp_path)
    collect_mock = AsyncMock()
    monkeypatch.setattr("scripts.diagnose_messenger.collect", collect_mock)
    with instance_lock(tmp_path / "data"):
        assert main(["--seconds", "10"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["step"] == "lock" and report["counts"]["LOCK_BUSY"] == 1
    assert not collect_mock.called
