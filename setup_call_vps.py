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

from messenger_ai.call_lab import MODELS, VOICES, google_key
from messenger_ai.call_vps import PERSONA_NAME, read_persona, read_settings
from messenger_ai.call_reports import DEFAULT_SUMMARY_MODEL, valid_summary_model

ROOT = Path(__file__).resolve().parent
APP = Path("/opt/messenger-ai-call")
STATE = Path("/var/lib/messenger-ai-call")
SERVICE = "messenger-ai-call"
USER = "messenger-call"
REPORT_SPOOL = Path("/var/spool/messenger-ai-call")
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


def settings(
    old: dict | None,
    key: str,
    browser: str,
    model=None,
    max_seconds=None,
    use_persona=None,
    voice=None,
    summary_enabled=None,
    summary_model=None,
    summary_outbox=None,
):
    data = dict(old or {})
    selected_voice = data.get("voice") if voice is None else voice
    if selected_voice == "default":
        selected_voice = None
    return {
        "google_api_key": key,
        "relay_token": data.get("relay_token") or secrets.token_urlsafe(32),
        "browser": browser,
        "model": model or data.get("model", MODELS[0]),
        "max_seconds": max_seconds
        if max_seconds is not None
        else data.get("max_seconds", 600),
        "use_persona": data.get("use_persona", False)
        if use_persona is None
        else use_persona,
        "voice": selected_voice,
        "summary_enabled": data.get("summary_enabled", False)
        if summary_enabled is None
        else summary_enabled,
        "summary_model": summary_model
        or data.get("summary_model", DEFAULT_SUMMARY_MODEL),
        "summary_outbox": summary_outbox or data.get("summary_outbox", ""),
    }


def summary_source():
    from messenger_ai.config import Settings

    config_path = ROOT / "config.json"
    if config_path.is_symlink():
        raise ValueError("Từ chối cấu hình bot qua symlink.")
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    Settings.from_dict(raw)
    secrets_data = json.loads((ROOT / "secrets.json").read_text(encoding="utf-8"))
    cookie = secrets_data.get("facebook_cookie", "")
    owner = (
        next(
            (
                piece.partition("=")[2].strip()
                for piece in cookie.split(";")
                if piece.partition("=")[0].strip() == "c_user"
            ),
            "",
        )
        if isinstance(cookie, str)
        else ""
    )
    if not owner.isascii() or not owner.isdigit() or not owner or owner.startswith("0"):
        raise ValueError(
            "Chưa xác định được chính tài khoản bot từ cấu hình Facebook hiện có."
        )
    info = config_path.stat()
    return raw, info, owner


def prepare_summary_route(account):
    from messenger_ai.config import Settings

    raw, info, owner = summary_source()
    config_path = ROOT / "config.json"
    REPORT_SPOOL.mkdir(mode=0o711, parents=True, exist_ok=True)
    if REPORT_SPOOL.is_symlink():
        raise ValueError("Từ chối hộp tóm tắt qua symlink.")
    os.chown(REPORT_SPOOL, 0, 0)
    os.chmod(REPORT_SPOOL, 0o711)
    current = raw.get("call_summary_inbox", "")
    route = (
        Path(current)
        if isinstance(current, str)
        and Path(current).parent == REPORT_SPOOL
        and len(Path(current).name) == 32
        and all(c in "0123456789abcdef" for c in Path(current).name)
        else REPORT_SPOOL / secrets.token_hex(16)
    )
    if route.is_symlink():
        raise ValueError("Từ chối hộp tóm tắt qua symlink.")
    route.mkdir(mode=0o2770, exist_ok=True)
    os.chown(route, account.pw_uid, pwd.getpwuid(info.st_uid).pw_gid)
    os.chmod(route, 0o2770)
    raw.update(call_summary_inbox=str(route), call_summary_owner_id=owner)
    Settings.from_dict(raw)
    private_write(
        config_path,
        (json.dumps(raw, ensure_ascii=False, indent=2) + "\n").encode(),
        info.st_uid,
        info.st_gid,
    )
    return str(route)


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
    if args.summary_model is not None and not valid_summary_model(args.summary_model):
        raise ValueError("Mã model tóm tắt chưa hợp lệ.")
    if args.call_summaries:
        summary_source()
    chosen_persona = (
        read_persona(Path(args.persona).expanduser()) if args.persona else None
    )
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
    for name in ("__init__.py", "call_lab.py", "call_vps.py", "call_reports.py"):
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
    use_persona = (
        True if chosen_persona is not None else False if args.no_persona else None
    )
    data = settings(
        old,
        key,
        browser,
        args.model,
        args.max_seconds,
        use_persona,
        voice=args.voice,
        summary_enabled=True
        if args.call_summaries
        else False
        if args.no_call_summaries
        else None,
        summary_model=args.summary_model,
        summary_outbox=prepare_summary_route(account) if args.call_summaries else None,
    )
    if chosen_persona is not None:
        private_write(
            STATE / PERSONA_NAME,
            chosen_persona.encode("utf-8"),
            account.pw_uid,
            account.pw_gid,
        )
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
    print("Giọng gọi: " + (data["voice"] or "mặc định của Google"))
    print(
        "Tóm tắt sau gọi: "
        + (
            "BẬT; khởi động lại bot nhắn tin của thư mục này để nhận tin cho chính mình."
            if data["summary_enabled"]
            else "TẮT"
        )
    )
    print(
        "Persona cuộc gọi: "
        + (
            "bản riêng đã chọn; nội dung được gửi Google trong mỗi phiên"
            if data["use_persona"]
            else "mẫu chung"
        )
    )
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
        "--voice",
        choices=("default", *VOICES),
        metavar="NAME",
        help="Tên giọng Google, ví dụ Kore, Puck, Aoede; default để dùng mặc định.",
    )
    parser.add_argument(
        "--max-seconds", type=int, choices=range(15, 901), metavar="15..900"
    )
    parser.add_argument("--update-key", action="store_true")
    summary = parser.add_mutually_exclusive_group()
    summary.add_argument(
        "--call-summaries",
        action="store_true",
        help="Tóm tắt phần AI nghe, gửi cho chính tài khoản bot của thư mục hiện tại.",
    )
    summary.add_argument(
        "--no-call-summaries",
        action="store_true",
        help="Tắt nhận dạng/tóm tắt cuộc gọi mới.",
    )
    parser.add_argument(
        "--summary-model",
        metavar="MODEL",
        help="Model Google dùng cho một lượt tóm tắt sau gọi.",
    )
    persona = parser.add_mutually_exclusive_group()
    persona.add_argument(
        "--persona",
        metavar="FILE",
        help="Dùng bản sao riêng của file UTF-8 cho cuộc gọi; nội dung được gửi Google.",
    )
    persona.add_argument(
        "--no-persona",
        action="store_true",
        help="Dùng mẫu chung, ngừng gửi persona riêng.",
    )
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
