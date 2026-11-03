"""Back up a stopped bot's existing device, then clear only cached Signal sessions."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid


class RepairError(Exception):
    def __init__(self, code, backup=None):
        self.code, self.backup = code, backup
        super().__init__(code)


def cookie_account(cookie):
    if not isinstance(cookie, str) or "\n" in cookie or "\r" in cookie:
        raise RepairError("COOKIE_INVALID")
    fields = []
    for part in cookie.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep:
            fields.append((name, value))
    accounts = [value for name, value in fields if name == "c_user"]
    if (
        len(accounts) != 1
        or not re.fullmatch(r"[1-9][0-9]{0,24}", accounts[0])
        or not any(name == "xs" and value for name, value in fields)
    ):
        raise RepairError("COOKIE_INVALID")
    return accounts[0]


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RepairError("DEVICE_FORMAT_UNSUPPORTED")
        result[key] = value
    return result


def read_device(path, account):
    if path.is_symlink():
        raise RepairError("DEVICE_SYMLINK")
    fd = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_size > 32 * 1024 * 1024
        ):
            raise RepairError("DEVICE_FILE_UNSUPPORTED")
        original = handle.read(32 * 1024 * 1024 + 1)
    if len(original) > 32 * 1024 * 1024:
        raise RepairError("DEVICE_FILE_UNSUPPORTED")
    try:
        device = json.loads(original, object_pairs_hook=unique_fields)
        if not isinstance(device, dict):
            raise ValueError
        for field, size in {
            "noise_key_priv": 32,
            "identity_key_priv": 32,
            "signed_pre_key_priv": 32,
            "signed_pre_key_sig": 64,
            "adv_secret_key": 32,
        }.items():
            value = device.get(field)
            if (
                not isinstance(value, str)
                or len(base64.b64decode(value, validate=True)) != size
            ):
                raise ValueError
        if (
            not isinstance(device.get("facebook_uuid"), str)
            or not uuid.UUID(device["facebook_uuid"]).int
        ):
            raise ValueError
        if (
            type(device.get("registration_id")) is not int
            or not 1 <= device["registration_id"] <= 16380
        ):
            raise ValueError
        sessions = device.get("sessions", {})
        if not isinstance(sessions, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in sessions.items()
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise RepairError("DEVICE_FORMAT_UNSUPPORTED") from None
    if not isinstance(device.get("jid_user"), str) or device["jid_user"] != account:
        raise RepairError("COOKIE_DEVICE_ACCOUNT_MISMATCH")
    return original, info, device


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_private(fd, content, info):
    with os.fdopen(fd, "wb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            os.fchown(handle.fileno(), info.st_uid, info.st_gid)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def repair(path: Path, account: str, *, apply=False):
    original, info, device = read_device(path, account)
    count = len(device.get("sessions", {}))
    result = {"status": "checked", "sessions": count, "account_matches": True}
    if not apply:
        return result
    if not count:
        return {**result, "status": "no_sessions_to_clear"}
    updated = dict(device)
    updated["sessions"] = {}
    # Preserve every field except the cached pairwise session records.
    content = (
        json.dumps(updated, ensure_ascii=False, allow_nan=False, indent=2).encode(
            "utf-8"
        )
        + b"\n"
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(
        path.name + ".before-sessions-" + stamp + "-" + uuid.uuid4().hex[:8] + ".bak"
    )
    temporary = None
    backup_created, backup_complete, replaced = False, False, False
    try:
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        backup_created = True
        write_private(fd, original, info)
        if backup.read_bytes() != original:
            raise OSError("backup verification failed")
        backup_complete = True
        sync_directory(path.parent)
        fd, filename = tempfile.mkstemp(prefix="session-repair-", dir=path.parent)
        temporary = Path(filename)
        write_private(fd, content, info)
        current = path.stat(follow_symlinks=False)
        if (
            current.st_ino != info.st_ino
            or current.st_dev != info.st_dev
            or path.is_symlink()
            or path.read_bytes() != original
        ):
            raise RepairError("DEVICE_CHANGED", backup.name)
        os.replace(temporary, path)
        replaced = True
        sync_directory(path.parent)
    except OSError:
        raise RepairError(
            "WRITE_UNCERTAIN" if replaced else "WRITE_FAILED",
            backup.name if backup_complete else None,
        ) from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if backup_created and not backup_complete:
            backup.unlink(missing_ok=True)
    return {
        **result,
        "status": "applied",
        "backup": "data/" + backup.name,
        "sessions_cleared": count,
        "identity_preserved": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Back up and clear sessions; default only checks.",
    )
    args = parser.parse_args(argv)
    try:
        from messenger_ai.cli import instance_lock
        from messenger_ai.config import ROOT, load_secrets

        if importlib.metadata.version("fbchat-v2") != "2.3.4":
            raise RepairError("SDK_NOT_PINNED")
        with instance_lock(ROOT / "data"):
            account = cookie_account(load_secrets(ROOT).get("facebook_cookie", ""))
            result = repair(
                ROOT / "data/messenger-device.db", account, apply=args.apply
            )
    except RepairError as error:
        result = {"status": "blocked", "code": error.code}
        if error.backup:
            result["backup"] = "data/" + error.backup
    except FileNotFoundError:
        result = {"status": "blocked", "code": "DEVICE_OR_CONFIG_MISSING"}
    except PermissionError:
        result = {"status": "blocked", "code": "FILE_PERMISSION_ERROR"}
    except RuntimeError:
        result = {"status": "blocked", "code": "BOT_LOCK_OR_RUNTIME_ERROR"}
    except Exception:
        result = {"status": "blocked", "code": "DEVICE_CHECK_FAILED"}
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return (
        0 if result["status"] in ("checked", "applied", "no_sessions_to_clear") else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
