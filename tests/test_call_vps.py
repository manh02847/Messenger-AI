import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest

import setup_call_vps as installer
from messenger_ai import call_vps as host


def configuration():
    return {
        "google_api_key": "PRIVATE_GOOGLE",
        "relay_token": "PRIVATE_TOKEN_" + "x" * 32,
        "browser": "/usr/bin/google-chrome-stable",
        "model": "gemini-3.8-live",
        "max_seconds": 600,
    }


def test_settings_preserve_token_but_never_copy_facebook_or_persona():
    old = {
        **configuration(),
        "facebook_cookie": "DO_NOT_COPY",
        "persona": "DO_NOT_COPY",
    }
    result = installer.settings(old, "NEW_GOOGLE", "/usr/bin/google-chrome-stable")
    assert result["relay_token"] == old["relay_token"]
    assert result["google_api_key"] == "NEW_GOOGLE"
    assert "DO_NOT_COPY" not in json.dumps(result)
    changed = installer.settings(
        old, "NEW_GOOGLE", "/usr/bin/google-chrome-stable", host.MODELS[1], 900
    )
    assert changed["model"] == host.MODELS[1] and changed["max_seconds"] == 900
    assert len(installer.settings(None, "KEY", "/usr/bin/chrome")["relay_token"]) >= 32


def test_voice_survives_updates_can_be_changed_and_reset(tmp_path):
    selected = installer.settings(
        configuration(), "KEY", "/usr/bin/chrome", voice="Puck"
    )
    updated = installer.settings(selected, "KEY", "/usr/bin/chrome", use_persona=True)
    assert updated["voice"] == "Puck"
    changed = installer.settings(updated, "KEY", "/usr/bin/chrome", voice="Kore")
    assert changed["voice"] == "Kore" and changed["use_persona"] is True
    reset = installer.settings(changed, "KEY", "/usr/bin/chrome", voice="default")
    assert reset["voice"] is None and reset["relay_token"] == selected["relay_token"]
    for data in (configuration(), selected, updated, changed, reset):
        installer.private_write(
            tmp_path / "settings.json",
            json.dumps(data).encode(),
            os.getuid(),
            os.getgid(),
        )
        assert host.read_settings(tmp_path) == data


def test_persona_is_only_read_when_explicitly_enabled_and_never_shown_in_repr(tmp_path):
    from messenger_ai.call_lab import SYSTEM, LabConfig, setup

    path = tmp_path / host.PERSONA_NAME
    path.write_text("SYNTHETIC_PRIVATE_PERSONA: thích câu trả lời tự nhiên.")
    assert host.call_instruction(tmp_path, configuration()) == SYSTEM
    selected = host.call_instruction(tmp_path, {**configuration(), "use_persona": True})
    assert selected.startswith(SYSTEM) and "SYNTHETIC_PRIVATE_PERSONA" in selected
    config = LabConfig("PRIVATE_KEY", "PRIVATE_TOKEN", system_instruction=selected)
    assert "PRIVATE" not in repr(config)
    assert (
        "SYNTHETIC_PRIVATE_PERSONA"
        in setup(config)["setup"]["systemInstruction"]["parts"][0]["text"]
    )
    old = {**configuration(), "use_persona": True}
    assert installer.settings(old, "KEY", "/usr/bin/chrome")["use_persona"] is True
    assert (
        installer.settings(old, "KEY", "/usr/bin/chrome", use_persona=False)[
            "use_persona"
        ]
        is False
    )
    path.unlink()
    assert host.call_instruction(tmp_path, configuration()) == SYSTEM
    with pytest.raises(host.HostError):
        host.call_instruction(tmp_path, {**configuration(), "use_persona": True})


@pytest.mark.parametrize("value", [b"", b"\x00BAD", b"\xff", b"a" * 12001])
def test_invalid_persona_does_not_echo_contents(tmp_path, value):
    path = tmp_path / "selected.txt"
    path.write_bytes(value)
    with pytest.raises(host.HostError) as error:
        host.read_persona(path)
    assert "BAD" not in str(error.value)


def test_private_config_write_is_atomic_and_does_not_follow_symlinks(tmp_path):
    target = tmp_path / "settings.json"
    installer.private_write(target, b"PRIVATE", os.getuid(), os.getgid())
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    installer.private_write(target, b"REPLACED", os.getuid(), os.getgid())
    assert target.read_bytes() == b"REPLACED"
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        installer.private_write(link, b"WRONG", os.getuid(), os.getgid())
    assert target.read_bytes() == b"REPLACED"
    assert not list(tmp_path.glob(".call-*"))


@pytest.mark.parametrize(
    "patch",
    [
        {"model": "unknown"},
        {"max_seconds": True},
        {"max_seconds": 0},
        {"max_seconds": 901},
        {"google_api_key": ""},
        {"google_api_key": "a\nPRIVATE"},
        {"google_api_key": 123},
        {"relay_token": "short"},
        {"relay_token": "é" * 40},
        {"browser": "relative/chrome"},
        {"voice": "UNKNOWN_PRIVATE"},
        {"voice": ["Kore"]},
        {"voice": True},
        {"summary_target": "everyone"},
        {"summary_target": "caller", "summary_owner_id": "222@msgr"},
        {"summary_target": "caller", "summary_owner_id": ""},
    ],
)
def test_bad_host_settings_fail_without_echoing_values(tmp_path, patch):
    (tmp_path / "settings.json").write_text(json.dumps({**configuration(), **patch}))
    with pytest.raises(host.HostError) as error:
        host.read_settings(tmp_path)
    assert "PRIVATE" not in str(error.value)


def test_deployment_keeps_desktop_private_and_chrome_sandbox_enabled(tmp_path):
    commands = dict(host.commands(tmp_path, tmp_path / "run", "/usr/bin/chrome"))
    vnc = commands["Màn hình"]
    assert "-localhost" in vnc and vnc[vnc.index("-SecurityTypes") + 1] == "VncAuth"
    assert "-auth" in vnc
    assert commands["Điều khiển"][-2:] == ["127.0.0.1:6080", "127.0.0.1:5977"]
    assert "--no-sandbox" not in commands["Chrome"]
    assert not any(
        "remote-debugging" in arg or "api-key" in arg
        for args in commands.values()
        for arg in args
    )
    assert "--load=module-null-sink sink_name=call_speaker" in commands["Âm thanh"]
    assert "--load=module-null-sink sink_name=call_microphone" in commands["Âm thanh"]
    # Chromium omits monitor sources and rejects a monitor as the default mic.
    # A remapped source must exist independently of both output monitors.
    remapped = next(
        arg
        for arg in commands["Âm thanh"]
        if arg.startswith("--load=module-remap-source ")
    )
    assert "master=call_microphone.monitor" in remapped
    assert f"source_name={host.VIRTUAL_MIC}" in remapped
    assert "device.description=Messenger_Virtual_Mic" in remapped
    assert host.VIRTUAL_MIC != "call_speaker.monitor" and not host.VIRTUAL_MIC.endswith(
        ".monitor"
    )
    unit = (
        Path(__file__).resolve().parents[1] / "deploy/messenger-ai-call.service"
    ).read_text()
    assert "User=messenger-call" in unit and "User=root" not in unit
    assert "Restart=on-failure" in unit and "MemoryMax=2500M" in unit


def test_non_root_installer_never_runs_package_manager(monkeypatch):
    monkeypatch.setattr(installer.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        installer.subprocess, "run", lambda *a, **k: pytest.fail("No mutation")
    )
    with pytest.raises(ValueError, match="root"):
        installer.preflight()


@pytest.mark.asyncio
async def test_child_failure_closes_relay_and_reaps_other_processes(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "settings.json").write_text(json.dumps(configuration()))
    (tmp_path / "vnc.passwd").write_bytes(bytes(8))
    runtime = tmp_path / "run"
    runtime.mkdir()
    monkeypatch.setattr(host.os, "geteuid", lambda: 1000)

    async def authority(*args):
        pass

    monkeypatch.setattr(host, "prepare_authority", authority)
    monkeypatch.setattr(
        host,
        "commands",
        lambda *args: [
            ("Worker", [sys.executable, "-c", "import time; time.sleep(60)"]),
            (
                "Failing worker",
                [
                    sys.executable,
                    "-c",
                    "import time; time.sleep(.15); raise SystemExit(3)",
                ],
            ),
        ],
    )
    created = []
    original = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        created.append(process)
        return process

    monkeypatch.setattr(host.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(host.HostError, match="Failing worker"):
        await asyncio.wait_for(host.run(tmp_path, runtime, port=0), 4)
    assert len(created) == 2 and all(p.returncode is not None for p in created)
    assert "PRIVATE" not in capsys.readouterr().out
