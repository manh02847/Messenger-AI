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

from .config import (
    GOOGLE_MODELS,
    NVIDIA_DEFAULT_MODEL,
    ROOT,
    Settings,
    load_persona,
    load_secrets,
    private_json,
)


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
        ROOT / "secrets.json",
        {**old, "groq_api_key": api_key, "facebook_cookie": cookie},
    )
    if not (ROOT / "config.json").exists():
        raw = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        private_json(ROOT / "config.json", raw)
    print(
        "Đã lưu cấu hình. Chạy discover để lấy mã cuộc trò chuyện; chưa bật gửi tự động."
    )


def configure_ai(
    provider: str, daily_limit: int | None = None, fallback: bool | None = None
) -> None:
    path = ROOT / "config.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    Settings.from_dict(raw)
    secrets = load_secrets(ROOT)
    if provider == "cloudflare":
        secrets["cloudflare_account_id"] = (
            input("Cloudflare Account ID (Enter để giữ cũ): ").strip()
            or secrets["cloudflare_account_id"]
        )
        secrets["cloudflare_api_token"] = (
            getpass.getpass("Workers AI API token (Enter để giữ cũ): ").strip()
            or secrets["cloudflare_api_token"]
        )
        model = "@cf/qwen/qwen3-30b-a3b-fp8"
    else:
        secrets["groq_api_key"] = (
            getpass.getpass("Groq API key (Enter để giữ cũ): ").strip()
            or secrets["groq_api_key"]
        )
        model = "openai/gpt-oss-120b"
    if provider != raw.get("ai_provider", "groq") and "fallback_model" in raw:
        raw["fallback_model"] = ""
    raw.update(ai_provider=provider, model=model)
    if fallback is not None:
        raw["ai_fallback"] = fallback
    if daily_limit is not None:
        raw["max_ai_calls_per_day"] = daily_limit
    settings = Settings.from_dict(raw)

    from .ai import provider_configs

    provider_configs(secrets, settings)
    private_json(ROOT / "secrets.json", secrets)
    private_json(path, raw)
    print(
        f"Đã chọn {provider} / {model}; giới hạn cục bộ {settings.max_ai_calls_per_day} lần gọi/ngày."
    )
    print("Tự chuyển nguồn dự phòng:", "BẬT" if settings.ai_fallback else "TẮT")
    print("Chưa kiểm tra API thật. Chạy check-ai rồi khởi động lại bot.")


def configure_google(models: list[str] | None = None, *, disable: bool = False) -> None:
    path = ROOT / "config.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    Settings.from_dict(raw)
    raw["google_models"] = [] if disable else list(models or GOOGLE_MODELS)
    settings = Settings.from_dict(raw)
    if not disable:
        from .ai import provider_configs

        secrets = load_secrets(ROOT)
        secrets["google_api_key"] = (
            getpass.getpass("Google AI Studio API key (Enter để giữ cũ): ").strip()
            or secrets["google_api_key"]
        )
        if not secrets["google_api_key"]:
            raise ValueError("Chưa nhập Google AI Studio API key.")
        provider_configs(secrets, settings)
        private_json(ROOT / "secrets.json", secrets)
    private_json(path, raw)
    if disable:
        print("Đã tắt nguồn Google; giữ API key và các nguồn cũ.")
    else:
        print("Ưu tiên Google:", " → ".join(settings.google_models))
        print(
            "Khi các model Google chờ quota, dùng các nguồn Groq/Cloudflare đang cấu hình."
        )
        print(
            "Giữ nguyên ngân sách gọi AI cục bộ; quota Google có thể dùng chung giữa model."
        )
    print("Chạy check-ai/chat-ai để thử rồi khởi động lại service bot.")


def configure_nvidia(model: str | None = None, *, disable: bool = False) -> None:
    path = ROOT / "config.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    Settings.from_dict(raw)
    current = raw.get("nvidia_model") or NVIDIA_DEFAULT_MODEL
    selected = (
        ""
        if disable
        else (
            model
            or input(f"Mã model NVIDIA (Enter để dùng {current}): ").strip()
            or current
        )
    )
    raw["nvidia_model"] = selected
    settings = Settings.from_dict(raw)
    if not disable:
        from .ai import provider_configs

        secrets = load_secrets(ROOT)
        secrets["nvidia_api_key"] = (
            getpass.getpass("NVIDIA API key (Enter để giữ cũ): ").strip()
            or secrets["nvidia_api_key"]
        )
        provider_configs(secrets, settings)
        private_json(ROOT / "secrets.json", secrets)
    private_json(path, raw)
    print("NVIDIA:", "TẮT" if disable else settings.nvidia_model)
    print(
        "Giữ nguyên Google/Groq/Cloudflare, ngữ cảnh và các giới hạn. Chạy check-nvidia để thử riêng."
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


def upgrade_chat() -> None:
    from .ai import CHAT_MODELS

    path = ROOT / "config.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    settings = Settings.from_dict(raw)
    raw["model"] = CHAT_MODELS[settings.ai_provider]
    if settings.ai_fallback:
        other = "groq" if settings.ai_provider == "cloudflare" else "cloudflare"
        raw["fallback_model"] = CHAT_MODELS[other]
    raw["max_replies_per_thread_per_day"] = max(
        settings.max_replies_per_thread_per_day, 1000
    )
    raw["max_ai_calls_per_day"] = max(settings.max_ai_calls_per_day, 1000)
    Settings.from_dict(raw)
    private_json(path, raw)
    print(f"Đã chọn {raw['model']}; nhà cung cấp và trạng thái dự phòng giữ nguyên.")
    print(
        f"Giới hạn: {raw['max_replies_per_thread_per_day']} câu/chat/ngày; {raw['max_ai_calls_per_day']} lần gọi AI/ngày cho toàn bot."
    )
    print(
        "Quota API không thay đổi. Qwen3.8 dùng nhiều Neurons hơn Qwen3 cũ trên Cloudflare."
    )
    print("Chạy check-ai/chat-ai để thử, rồi khởi động lại service bot để áp dụng.")


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


async def check_ai(*, interactive: bool = False, provider: str | None = None) -> None:
    from .ai import create_ai
    from .state import State
    from .core import VIETNAM
    from datetime import datetime

    settings = Settings.load()
    secrets = load_secrets()
    persona = load_persona(ROOT)
    state = State(ROOT / "data" / "ai-check.sqlite3")
    if provider == "nvidia":
        from .ai import ChatAI

        if not settings.nvidia_model:
            state.close()
            raise ValueError("Chạy configure-nvidia để chọn model và nhập key trước.")
        ai = ChatAI(
            secrets["nvidia_api_key"],
            replace(settings, ai_provider="nvidia", model=settings.nvidia_model),
            persona,
            fail_fast=True,
        )
    else:
        ai = create_ai(secrets, settings, persona)
    started = time.monotonic()
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
        print(
            f"{ai.last_used} đã trả lời:",
            text[: settings.output_char_limit],
        )
        print(f"Thời gian lượt thử: {time.monotonic() - started:.2f} giây.")
        if provider == "nvidia":
            print("Chỉ thử NVIDIA; không chuyển sang nguồn API khác.")
        print("Chưa kết nối hay gửi gì lên Messenger.")
    finally:
        await ai.close()
        state.close()


async def run(*, discovery: bool, live: bool, preview: bool) -> None:
    from scripts.fetch_assets import ensure_bridge
    from .ai import create_ai
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
                persona = load_persona(ROOT)
                ai = create_ai(secrets, settings, persona)
            await transport.connect()
            if discovery:
                print(
                    "DISCOVER: nhờ đúng người bạn muốn thử nhắn một tin mới. Chỉ in mã, không đọc nội dung ra màn hình và không gửi trả lời. Ctrl+C để dừng."
                )
            else:
                bot = ReplyBot(settings, state, ai, transport, transport.own_id)
                print(f"AI: {ai.description}")
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
        description="Bot AI trả lời Messenger cá nhân, dùng Groq hoặc Cloudflare."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("configure", "Nhập API key và cookie tại máy bạn."),
        ("doctor", "Kiểm tra offline thư viện và bridge."),
        ("check-ai", "Gọi thử API đang chọn; không gửi Messenger."),
        ("chat-ai", "Chat thử với AI và ngữ cảnh, không kết nối Messenger."),
        ("upgrade-chat", "Đổi sang Qwen3.8 và nâng giới hạn ít nhất 1000/ngày."),
        ("tune-chat", "Bỏ icon và nâng giới hạn token mỗi câu trả lời."),
        ("discover", "Lấy mã cuộc trò chuyện; không tự rep."),
    ):
        sub.add_parser(name, help=help_text)
    ai_config = sub.add_parser(
        "configure-ai", help="Đổi nguồn AI, giữ cookie và ngữ cảnh."
    )
    ai_config.add_argument("provider", choices=("groq", "cloudflare"))
    ai_config.add_argument(
        "--daily-limit", type=int, help="Giới hạn số lần gọi AI cục bộ mỗi ngày."
    )
    ai_config.add_argument(
        "--fallback",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Tự chuyển giữa Cloudflare và Groq khi lỗi/quota; cần cấu hình cả hai key.",
    )
    google_config = sub.add_parser(
        "configure-google", help="Thêm Google và tự chuyển model khi lỗi/quota."
    )
    google_options = google_config.add_mutually_exclusive_group()
    google_options.add_argument(
        "--models",
        nargs="+",
        choices=GOOGLE_MODELS,
        help="Model Google theo thứ tự ưu tiên.",
    )
    google_options.add_argument(
        "--disable", action="store_true", help="Tắt Google, giữ các nguồn cũ."
    )
    nvidia_config = sub.add_parser(
        "configure-nvidia", help="Thêm NVIDIA NIM làm nguồn ưu tiên thử nghiệm."
    )
    nvidia_options = nvidia_config.add_mutually_exclusive_group()
    nvidia_options.add_argument(
        "--model", help="Mã model NVIDIA tự chọn, ví dụ google/gemma-4-31b-it."
    )
    nvidia_options.add_argument("--disable", action="store_true")
    sub.add_parser(
        "check-nvidia",
        help="Thử riêng NVIDIA; không fallback API, không gửi Messenger.",
    )
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
        elif args.command == "configure-ai":
            configure_ai(args.provider, args.daily_limit, args.fallback)
        elif args.command == "configure-google":
            configure_google(args.models, disable=args.disable)
        elif args.command == "configure-nvidia":
            configure_nvidia(args.model, disable=args.disable)
        elif args.command == "check-nvidia":
            asyncio.run(check_ai(provider="nvidia"))
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
        elif args.command == "upgrade-chat":
            upgrade_chat()
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
        from .ai import AIError, ProviderUnavailable

        detail = (
            str(error)
            if type(error) in (RuntimeError, AIError, ProviderUnavailable)
            else f"{type(error).__name__}; xem README.md để kiểm tra cấu hình/kết nối"
        )
        print(f"Bot đã dừng: {detail}", file=sys.stderr)
        raise SystemExit(1)
