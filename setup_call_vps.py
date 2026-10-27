"""Install the optional full VPS call host on Ubuntu/Debian; run as root."""

from __future__ import annotations

import argparse
import json
import os
import platform
import pwd
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

from messenger_ai.call_lab import MODELS, google_key
from messenger_ai.call_vps import read_settings

ROOT = Path(__file__).resolve().parent
APP = Path("/opt/messenger-ai-call")
STATE = Path("/var/lib/messenger-ai-call")
SERVICE = "messenger-ai-call"
USER = "messenger-call"
EXTENSION_FILES = (
    "manifest.json",
    "background.js",
    "bridge-main.js",
    "pcm.js",
    "content.js",
    "incoming.js",
    "popup.js",
    "popup.html",
    "popup.css",
)


def command(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def private_write(path: Path, content: bytes, uid: int, gid: int):
    if path.is_symlink():
        raise ValueError("Từ chối ghi cấu hình qua symlink.")
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".call-")
    try:
        os.fchmod(fd, 0o600)
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def settings(old: dict | None, key: str, browser: str, model=None, max_seconds=None):
    data = dict(old or {})
    return {
        "google_api_key": key,
        "relay_token": data.get("relay_token") or secrets.token_urlsafe(32),
        "browser": browser,
        "model": model or data.get("model", MODELS[0]),
        "max_seconds": max_seconds
        if max_seconds is not None
        else data.get("max_seconds", 600),
    }


def password(uid, gid):
    value = "".join(
        secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789")
        for _ in range(8)
    )
    executable = shutil.which("tigervncpasswd") or shutil.which("vncpasswd")
    if not executable:
        raise ValueError("Thiếu tigervncpasswd; chạy lại lệnh install.")
    result = command(
        executable, "-f", input=(value + "\n").encode(), capture_output=True
    )
    if len(result.stdout) != 8:
        raise ValueError("Chưa tạo được mật khẩu màn hình.")
    private_write(STATE / "vnc.passwd", result.stdout, uid, gid)
    print("Mật khẩu noVNC mới (chỉ hiện lần này): " + value)


def preflight():
    if os.geteuid() != 0 or sys.version_info < (3, 11):
        raise ValueError("Chạy bằng root với Python 3.11 trở lên trong venv của bot.")
    if (
        not Path("/etc/debian_version").exists()
        or not Path("/run/systemd/system").is_dir()
    ):
        raise ValueError("Bộ cài cần Ubuntu/Debian chạy systemd.")
    if platform.machine() not in ("x86_64", "amd64"):
        raise ValueError("Bộ cài hiện hỗ trợ Linux x86-64; chưa cài Chrome cho ARM.")
    active = (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", SERVICE], check=False
        ).returncode
        == 0
    )
    if not active:
        for port in (8765, 5977, 6080):
            with socket.socket() as listener:
                try:
                    listener.bind(("127.0.0.1", port))
                except OSError:
                    raise ValueError(
                        f"Cổng {port} đang dùng. Dừng relay call-lab cũ bằng Ctrl+C trước; không cần dừng bot text."
                    ) from None


def install(args):
    preflight()
    old = read_settings(STATE) if (STATE / "settings.json").exists() else None
    key = google_key(ROOT) if not old or args.update_key else old["google_api_key"]
    if not key.isascii() or any(c.isspace() for c in key):
        raise ValueError("Key Google trong thư mục bot chưa hợp lệ.")
    print("Đang cài desktop Chrome, âm thanh ảo và noVNC...", flush=True)
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    command("apt-get", "update", env=env)
    command(
        "apt-get",
        "install",
        "-y",
        "tigervnc-standalone-server",
        "tigervnc-tools",
        "openbox",
        "dbus-x11",
        "pulseaudio",
        "pulseaudio-utils",
        "novnc",
        "websockify",
        "x11-utils",
        "xauth",
        "fonts-dejavu-core",
        "fonts-noto-color-emoji",
        "curl",
        "ca-certificates",
        "python3-venv",
        env=env,
    )
    browser = shutil.which("google-chrome-stable") or shutil.which("google-chrome")
    if not browser:
        with tempfile.TemporaryDirectory(
            prefix="messenger-chrome-", dir="/var/tmp"
        ) as folder:
            os.chmod(folder, 0o755)
            package = Path(folder) / "google-chrome.deb"
            command(
                "curl",
                "--fail",
                "--location",
                "--proto",
                "=https",
                "--tlsv1.2",
                "--output",
                str(package),
                "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb",
            )
            command("apt-get", "install", "-y", str(package), env=env)
        browser = shutil.which("google-chrome-stable") or shutil.which("google-chrome")
    if not browser:
        raise ValueError("Chưa tìm thấy Chrome sau cài đặt.")
    try:
        account = pwd.getpwnam(USER)
    except KeyError:
        command(
            "useradd",
            "--system",
            "--user-group",
            "--home-dir",
            str(STATE),
            "--create-home",
            "--shell",
            "/usr/sbin/nologin",
            USER,
        )
        account = pwd.getpwnam(USER)
    if account.pw_uid == 0 or account.pw_dir != str(STATE):
        raise ValueError(
            "User messenger-call đã tồn tại với cấu hình khác; dừng để kiểm tra."
        )
    STATE.mkdir(parents=True, exist_ok=True)
    os.chown(STATE, account.pw_uid, account.pw_gid)
    os.chmod(STATE, 0o700)
    subprocess.run(["systemctl", "stop", SERVICE], check=False, capture_output=True)
    code = APP / "app/messenger_ai"
    extension = APP / "app/experimental/call-lab-extension"
    code.mkdir(parents=True, exist_ok=True)
    extension.mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "call_lab.py", "call_vps.py"):
        shutil.copyfile(ROOT / "messenger_ai" / name, code / name)
        os.chmod(code / name, 0o644)
    for name in EXTENSION_FILES:
        shutil.copyfile(
            ROOT / "experimental/call-lab-extension" / name, extension / name
        )
        os.chmod(extension / name, 0o644)
    python = APP / ".venv/bin/python"
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(APP / ".venv")
    command(
        str(python),
        "-m",
        "pip",
        "install",
        "-r",
        str(ROOT / "requirements-call-lab.txt"),
    )
    data = settings(old, key, browser, args.model, args.max_seconds)
    private_write(
        STATE / "settings.json",
        json.dumps(data).encode(),
        account.pw_uid,
        account.pw_gid,
    )
    if not (STATE / "vnc.passwd").exists():
        password(account.pw_uid, account.pw_gid)
    shutil.copyfile(
        ROOT / "deploy/messenger-ai-call.service",
        "/etc/systemd/system/messenger-ai-call.service",
    )
    os.chmod("/etc/systemd/system/messenger-ai-call.service", 0o644)
    command("systemctl", "daemon-reload")
    command("systemctl", "enable", "--now", SERVICE)
    print("Đã cài service messenger-ai-call. Google model: " + data["model"])
    print("Mã kết nối để dán vào tiện ích trên Chrome VPS: " + data["relay_token"])
    print(
        "Mở SSH tunnel 6080 từ máy bạn rồi vào http://127.0.0.1:6080/vnc.html để đăng nhập Facebook."
    )
    print("Thư mục Load unpacked: " + str(extension))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("install", "token", "password"), nargs="?", default="install"
    )
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument(
        "--max-seconds", type=int, choices=range(15, 901), metavar="15..900"
    )
    parser.add_argument("--update-key", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError("Lệnh này cần chạy bằng root.")
    os.umask(0o022)
    if args.action == "install":
        install(args)
    elif args.action == "token":
        print(read_settings(STATE)["relay_token"])
    else:
        account = pwd.getpwnam(USER)
        password(account.pw_uid, account.pw_gid)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as error:
        print("Chưa hoàn tất: " + str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, subprocess.SubprocessError):
        print(
            "Chưa hoàn tất: kiểm tra gói cài đặt/quyền hoặc journalctl -u messenger-ai-call.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
