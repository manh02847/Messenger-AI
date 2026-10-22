from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.metadata
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from .config import ROOT, Settings, load_secrets, private_json


@contextmanager
def instance_lock(data_dir: Path):
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = data_dir / "bot.lock"
    with path.open("a+b") as handle:
        path.chmod(0o600)
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                if not handle.read(1):
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError(
                "Đang có một bot/discover chạy trong thư mục này. Dừng phiên đó trước."
            ) from None
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def configure() -> None:
    old = load_secrets()
    print(
        "Nhập thông tin tại máy bạn. Không dán cookie hoặc API key vào GitHub/chat công khai."
    )
    api_key = (
        getpass.getpass("Groq API key (Enter để giữ giá trị cũ): ").strip()
        or old["groq_api_key"]
    )
    cookie = (
        getpass.getpass(
            "Cookie Facebook dạng c_user=...; xs=...; (Enter để giữ cũ): "
        ).strip()
        or old["facebook_cookie"]
    )
    if not api_key:
        raise ValueError("Chưa nhập API key Groq.")
    if "c_user=" not in cookie or "xs=" not in cookie:
        raise ValueError("Cookie cần có ít nhất c_user và xs.")
    private_json(
        ROOT / "secrets.json", {"groq_api_key": api_key, "facebook_cookie": cookie}
    )
    if not (ROOT / "config.json").exists():
        raw = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        private_json(ROOT / "config.json", raw)
    print(
        "Đã lưu cấu hình. Chạy discover để lấy mã cuộc trò chuyện; chưa bật gửi tự động."
    )


def doctor() -> None:
    from scripts.fetch_assets import ensure_bridge

    if sys.version_info < (3, 11):
        raise RuntimeError("Cần Python 3.11+.")
    if importlib.metadata.version("fbchat-v2") != "2.3.4":
        raise RuntimeError("Sai phiên bản fbchat-v2; chạy lại setup_bot.py.")
    binary = ensure_bridge()
    request = json.dumps({"id": 1, "method": "hello", "params": {}}) + "\n"
    process = subprocess.run(
        [str(binary)],
        input=request,
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    responses = [
        json.loads(line) for line in process.stdout.splitlines() if line.strip()
    ]
    response = next((item for item in responses if item.get("id") == 1), {})
    data = response.get("data", {})
    if (
        not response.get("ok")
        or data.get("bridgeVersion") != "2.3.4"
        or data.get("protocolVersion") != 1
    ):
        raise RuntimeError("Bridge không vượt qua bước kiểm tra phiên bản/giao thức.")
    capabilities = set(data.get("capabilities", []))
    if (
        not {"newClient", "connect", "connectE2EE", "isConnected", "events"}
        <= capabilities
    ):
        raise RuntimeError("Bridge thiếu các hàm cần thiết.")
    print("OK: Python, thư viện Messenger, SHA-256 và giao thức bridge E2EE 2.3.4.")
    print("Kiểm tra này không đăng nhập, không gọi AI và không gửi tin nhắn.")


def tune_chat() -> None:
    path = ROOT / "config.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    Settings.from_dict(raw)
    raw["max_completion_tokens"] = max(raw.get("max_completion_tokens", 768), 4096)
    raw["output_char_limit"] = max(raw.get("output_char_limit", 500), 4000)
    raw["reply_prefix"] = ""
    Settings.from_dict(raw)
    private_json(path, raw)
    print(
        "Đã bỏ tiền tố, nâng ngân sách tạo câu trả lời lên 4096 token và giới hạn văn bản ít nhất 4000 ký tự. Khởi động lại bot để áp dụng."
    )


def set_reply_scope(scope: str) -> None:
    path = ROOT / "config.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    Settings.from_dict(raw)
    raw["reply_scope"] = scope
    Settings.from_dict(raw)
    private_json(path, raw)
    print(
        "Đã chọn tự rep tất cả chat riêng; bỏ qua nhóm và loại chat chưa xác định."
        if scope == "all_private"
        else "Đã chọn chỉ rep các cuộc trò chuyện trong allowed_threads."
    )
    print("Khởi động lại bot để áp dụng.")


async def check_ai(*, interactive: bool = False) -> None:
    from .ai import GroqAI
    from .state import State
    from .core import VIETNAM
    from datetime import datetime

    settings = Settings.load()
    secrets = load_secrets()
    state = State(ROOT / "data" / "ai-check.sqlite3")
    persona = (ROOT / "persona.txt").read_text(encoding="utf-8").strip()
    if not persona:
        state.close()
        raise ValueError("persona.txt đang rỗng.")
    ai = GroqAI(secrets["groq_api_key"], settings, persona)
    try:

        def reserve():
            return state.reserve_ai(
                datetime.now(VIETNAM).date().isoformat(), settings.max_ai_calls_per_day
            )

        if interactive:
            from .preview import chat_loop

            await chat_loop(ai, settings, reserve)
            return
        text = await ai.generate(
            [
                {
                    "role": "user",
                    "content": "Chào bạn, hãy xác nhận kết nối bằng một câu ngắn.",
                }
            ],
            reserve,
        )
        print("Groq đã trả lời:", text[: settings.output_char_limit])
        print("Chưa kết nối hay gửi gì lên Messenger.")
    finally:
        await ai.close()
        state.close()


async def run(*, discovery: bool, live: bool, preview: bool) -> None:
    from scripts.fetch_assets import ensure_bridge
    from .ai import GroqAI
    from .core import ReplyBot, parse_event
    from .facebook import FacebookTransport
    from .state import State

    settings = Settings.load()
    if live:
        settings = replace(settings, dry_run=False)
    elif preview:
        settings = replace(settings, dry_run=True)
    if (
        not discovery
        and settings.reply_scope == "allowlist"
        and not settings.allowed_threads
    ):
        raise ValueError(
            "Danh sách allowed_threads đang rỗng. Dùng discover rồi allow, hoặc scope all_private."
        )
    secrets = load_secrets()
    transport = FacebookTransport(
        secrets["facebook_cookie"],
        ROOT / "data" / "messenger-device.db",
        ensure_bridge(),
    )
    state = None
    ai = None
    bot = None
    started_at = time.time()
    with instance_lock(ROOT / "data"):
        try:
            if not discovery:
                state = State(
                    ROOT
                    / "data"
                    / ("preview.sqlite3" if settings.dry_run else "state.sqlite3")
                )
                state.prune(time.time(), settings.retention_days)
                persona = (ROOT / "persona.txt").read_text(encoding="utf-8").strip()
                if not persona:
                    raise ValueError("persona.txt đang rỗng.")
                ai = GroqAI(secrets["groq_api_key"], settings, persona)
            await transport.connect()
            if discovery:
                print(
                    "DISCOVER: nhờ đúng người bạn muốn thử nhắn một tin mới. Chỉ in mã, không đọc nội dung ra màn hình và không gửi trả lời. Ctrl+C để dừng."
                )
            else:
                bot = ReplyBot(settings, state, ai, transport, transport.own_id)
                print(
                    "Chế độ: XEM TRƯỚC, chưa gửi tin."
                    if settings.dry_run
                    else "Chế độ: GỬI THẬT."
                )
                print(
                    "Phạm vi: TẤT CẢ CHAT RIÊNG; bỏ qua nhóm và loại chat chưa xác định."
                    if settings.reply_scope == "all_private"
                    else "Phạm vi: các cuộc trò chuyện trong allowed_threads."
                )
            reported = set()
            async for event in transport.events():
                message = parse_event(event)
                if message is None:
                    continue
                if discovery:
                    if (
                        message.timestamp >= started_at - 2
                        and message.sender_id != transport.own_id
                        and message.thread not in reported
                    ):
                        reported.add(message.thread)
                        print(
                            f"Mã cuộc trò chuyện: {message.thread} | người gửi: {message.sender_id}"
                            f" | loại: {'chat riêng' if message.is_private else 'nhóm/khác/chưa xác định'}",
                            flush=True,
                        )
                elif bot is not None:
                    bot.receive(message)
        finally:
            if bot is not None:
                await bot.close()
            await transport.close()
            if ai is not None:
                await ai.close()
            if state is not None:
                state.close()


def main() -> None:
    os.umask(0o077)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Bot AI trả lời Messenger cá nhân, dùng Groq."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("configure", "Nhập API key và cookie tại máy bạn."),
        ("doctor", "Kiểm tra offline thư viện và bridge."),
        ("check-ai", "Gọi thử Groq; không gửi Messenger."),
        ("chat-ai", "Chat thử với AI và ngữ cảnh, không kết nối Messenger."),
        ("tune-chat", "Bỏ icon và nâng giới hạn token mỗi câu trả lời."),
        ("discover", "Lấy mã cuộc trò chuyện; không tự rep."),
    ):
        sub.add_parser(name, help=help_text)
    allow = sub.add_parser(
        "allow", help="Thêm mã cuộc trò chuyện đã xác minh vào danh sách tự rep."
    )
    allow.add_argument("thread")
    scope = sub.add_parser("scope", help="Chọn phạm vi tự rep.")
    scope.add_argument("value", choices=("allowlist", "all_private"))
    command = sub.add_parser(
        "run", help="Chạy bot; mặc định theo dry_run trong cấu hình."
    )
    group = command.add_mutually_exclusive_group()
    group.add_argument("--live", action="store_true", help="Gửi câu trả lời thật.")
    group.add_argument(
        "--dry-run", action="store_true", help="Chỉ xem trước câu trả lời."
    )
    args = parser.parse_args()
    try:
        if args.command == "configure":
            configure()
        elif args.command == "doctor":
            doctor()
        elif args.command == "allow":
            path = ROOT / "config.json"
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["allowed_threads"] = list(
                dict.fromkeys([*raw.get("allowed_threads", []), args.thread])
            )
            Settings.from_dict(raw)
            private_json(path, raw)
            print(
                "Đã thêm cuộc trò chuyện. Bot đang chạy cần khởi động lại để nhận cấu hình mới."
            )
        elif args.command == "tune-chat":
            tune_chat()
        elif args.command == "scope":
            set_reply_scope(args.value)
        elif args.command in ("check-ai", "chat-ai"):
            asyncio.run(check_ai(interactive=args.command == "chat-ai"))
        else:
            asyncio.run(
                run(
                    discovery=args.command == "discover",
                    live=getattr(args, "live", False),
                    preview=getattr(args, "dry_run", False),
                )
            )
    except KeyboardInterrupt:
        print("\nĐã dừng bot.")
    except (ValueError, FileNotFoundError) as error:
        print(f"Cần cấu hình: {error}", file=sys.stderr)
        raise SystemExit(2)
    except Exception as error:
        # Never print untrusted server responses, cookie data or tracebacks.
        from .ai import AIError

        detail = (
            str(error)
            if type(error) in (RuntimeError, AIError)
            else f"{type(error).__name__}; xem README.md để kiểm tra cấu hình/kết nối"
        )
        print(f"Bot đã dừng: {detail}", file=sys.stderr)
        raise SystemExit(1)
