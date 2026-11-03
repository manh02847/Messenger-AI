import base64
import json
import os
from types import SimpleNamespace

import pytest

from scripts import repair_signal_sessions as recovery


def encoded(size):
    return base64.b64encode(b"x" * size).decode()


@pytest.fixture
def profile(tmp_path):
    data = {
        "noise_key_priv": encoded(32),
        "identity_key_priv": encoded(32),
        "signed_pre_key_priv": encoded(32),
        "signed_pre_key_sig": encoded(64),
        "signed_pre_key_id": 9,
        "registration_id": 100,
        "adv_secret_key": encoded(32),
        "facebook_uuid": "d6bab037-684f-42c0-bb03-10f4e3a74739",
        "jid_user": "111",
        "jid_device": 7,
        "sessions": {"222:1": encoded(20), "333:2": encoded(15)},
        "identities": {"222:1": encoded(32)},
        "pre_keys": {"7": "PRIVATE_PREKEY"},
        "uploaded_pre_keys": [1, 7],
        "next_pre_key_id": 8,
        "sender_keys": {"PRIVATE_GROUP": "PRIVATE_GROUP_KEY"},
        "unknown_future_field": {"preserve": [1, "PRIVATE_VALUE"]},
    }
    path = tmp_path / "data/messenger-device.db"
    path.parent.mkdir()
    path.write_text(json.dumps(data))
    return SimpleNamespace(path=path, data=data, original=path.read_bytes())


def test_default_check_never_changes_profile_or_creates_a_backup(profile):
    result = recovery.repair(profile.path, "111")
    assert result == {"status": "checked", "sessions": 2, "account_matches": True}
    assert profile.path.read_bytes() == profile.original
    assert list(profile.path.parent.iterdir()) == [profile.path]


def test_apply_keeps_identity_and_every_non_session_field_with_exact_private_backup(
    profile,
):
    result = recovery.repair(profile.path, "111", apply=True)
    changed = json.loads(profile.path.read_bytes())
    assert changed == {**profile.data, "sessions": {}}
    backup = profile.path.parents[1] / result["backup"]
    assert backup.read_bytes() == profile.original
    assert backup.stat().st_mode & 0o777 == profile.path.stat().st_mode & 0o777 == 0o600
    assert backup.stat().st_uid == profile.path.stat().st_uid
    assert result["status"] == "applied" and result["sessions_cleared"] == 2
    assert "PRIVATE" not in json.dumps(result) and "111" not in json.dumps(result)
    assert not list(profile.path.parent.glob("session-repair-*"))


def test_second_apply_is_a_noop_without_overwriting_the_backup(profile):
    first = recovery.repair(profile.path, "111", apply=True)
    current = profile.path.read_bytes()
    second = recovery.repair(profile.path, "111", apply=True)
    assert (
        second["status"] == "no_sessions_to_clear"
        and profile.path.read_bytes() == current
    )
    assert len(list(profile.path.parent.glob("*.bak"))) == 1
    assert (profile.path.parents[1] / first["backup"]).read_bytes() == profile.original


def test_wrong_cookie_account_is_blocked_without_touching_any_file(profile):
    with pytest.raises(recovery.RepairError, match="COOKIE_DEVICE_ACCOUNT_MISMATCH"):
        recovery.repair(profile.path, "999", apply=True)
    assert profile.path.read_bytes() == profile.original
    assert not list(profile.path.parent.glob("*.bak"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("identity_key_priv", "PRIVATE_INVALID_KEY"),
        ("noise_key_priv", encoded(5)),
        ("signed_pre_key_sig", encoded(1)),
        ("facebook_uuid", {}),
        ("registration_id", True),
        ("sessions", []),
        ("sessions", {"222:1": None}),
    ],
)
def test_unknown_or_invalid_device_format_is_never_rewritten(profile, field, value):
    profile.path.write_text(json.dumps({**profile.data, field: value}))
    before = profile.path.read_bytes()
    with pytest.raises(recovery.RepairError, match="DEVICE_FORMAT_UNSUPPORTED"):
        recovery.repair(profile.path, "111", apply=True)
    assert profile.path.read_bytes() == before and not list(
        profile.path.parent.glob("*.bak")
    )


def test_duplicate_json_fields_are_rejected_instead_of_dropping_a_key(profile):
    profile.path.write_bytes(
        profile.original[:-1] + b',"identity_key_priv":"PRIVATE_EXTRA"}'
    )
    before = profile.path.read_bytes()
    with pytest.raises(recovery.RepairError, match="DEVICE_FORMAT_UNSUPPORTED"):
        recovery.repair(profile.path, "111", apply=True)
    assert profile.path.read_bytes() == before


def test_symlink_and_hardlink_profiles_are_not_modified(profile):
    link = profile.path.with_name("linked.db")
    link.symlink_to(profile.path)
    with pytest.raises(recovery.RepairError, match="DEVICE_SYMLINK"):
        recovery.repair(link, "111", apply=True)
    link.unlink()
    os.link(profile.path, link)
    with pytest.raises(recovery.RepairError, match="DEVICE_FILE_UNSUPPORTED"):
        recovery.repair(profile.path, "111", apply=True)
    assert profile.path.read_bytes() == profile.original


def test_failed_replace_keeps_original_and_verified_backup(profile, monkeypatch):
    def fail(*args):
        raise PermissionError("PRIVATE_PATH_OR_TOKEN")

    monkeypatch.setattr(recovery.os, "replace", fail)
    with pytest.raises(recovery.RepairError) as caught:
        recovery.repair(profile.path, "111", apply=True)
    assert caught.value.code == "WRITE_FAILED"
    assert profile.path.read_bytes() == profile.original
    assert (profile.path.parent / caught.value.backup).read_bytes() == profile.original
    assert "PRIVATE" not in str(caught.value)
    assert not list(profile.path.parent.glob("session-repair-*"))


def test_concurrent_profile_change_is_not_overwritten(profile, monkeypatch):
    original_write = recovery.write_private
    writes = []

    def change_after_temp(fd, content, info):
        original_write(fd, content, info)
        writes.append(True)
        if len(writes) == 2:
            profile.path.write_bytes(b"OTHER_PRIVATE_PROCESS_STATE")

    monkeypatch.setattr(recovery, "write_private", change_after_temp)
    with pytest.raises(recovery.RepairError, match="DEVICE_CHANGED"):
        recovery.repair(profile.path, "111", apply=True)
    assert profile.path.read_bytes() == b"OTHER_PRIVATE_PROCESS_STATE"
    assert list(profile.path.parent.glob("*.bak"))[0].read_bytes() == profile.original


def test_backup_filename_collision_never_deletes_an_existing_backup(
    profile, monkeypatch
):
    backup = profile.path.with_name(
        "messenger-device.db.before-sessions-fixed-aaaaaaaa.bak"
    )
    backup.write_bytes(b"PRIVATE_PREVIOUS_BACKUP")
    monkeypatch.setattr(
        recovery,
        "datetime",
        SimpleNamespace(now=lambda _: SimpleNamespace(strftime=lambda _: "fixed")),
    )
    monkeypatch.setattr(recovery.uuid, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
    with pytest.raises(recovery.RepairError, match="WRITE_FAILED"):
        recovery.repair(profile.path, "111", apply=True)
    assert backup.read_bytes() == b"PRIVATE_PREVIOUS_BACKUP"
    assert profile.path.read_bytes() == profile.original


@pytest.mark.parametrize(
    "cookie",
    [
        "",
        "c_user=111;",
        "c_user=111; c_user=999; xs=x",
        "c_user=abc; xs=x",
        "c_user=111; xs=x\nPRIVATE",
    ],
)
def test_missing_duplicate_or_invalid_cookie_identity_is_not_used(cookie):
    with pytest.raises(recovery.RepairError, match="COOKIE_INVALID"):
        recovery.cookie_account(cookie)


def test_main_respects_bot_lock_before_any_repair(profile, monkeypatch, capsys):
    from messenger_ai.cli import instance_lock

    root = profile.path.parents[1]
    monkeypatch.setattr("messenger_ai.config.ROOT", root)
    monkeypatch.setattr(
        "messenger_ai.config.load_secrets",
        lambda _: {"facebook_cookie": "c_user=111; xs=PRIVATE"},
    )
    monkeypatch.setattr(recovery.importlib.metadata, "version", lambda _: "2.3.4")
    with instance_lock(root / "data"):
        assert recovery.main(["--apply"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["code"] == "BOT_LOCK_OR_RUNTIME_ERROR"
    assert profile.path.read_bytes() == profile.original


def test_main_apply_reports_only_safe_fields(profile, monkeypatch, capsys):
    monkeypatch.setattr("messenger_ai.config.ROOT", profile.path.parents[1])
    monkeypatch.setattr(
        "messenger_ai.config.load_secrets",
        lambda _: {"facebook_cookie": "c_user=111; xs=PRIVATE_COOKIE"},
    )
    monkeypatch.setattr(recovery.importlib.metadata, "version", lambda _: "2.3.4")
    assert recovery.main(["--apply"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "applied"
    assert "PRIVATE" not in output and "111" not in output
    assert json.loads(profile.path.read_bytes()) == {**profile.data, "sessions": {}}
