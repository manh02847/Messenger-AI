from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from .call_lab import VOICES
from .config import (
    NVIDIA_DEFAULT_MODEL,
    PROVIDER_KEYS,
    ROOT,
    THREAD_PATTERN,
    VISION_PRESET,
    Settings,
    canonical_config,
    load_persona,
    load_secrets,
    private_json,
    model_target,
    read_config,
    save_config,
)
from .providers import (
    DEFAULT_TEXT_MODELS,
    describe_routes,
    models_for,
    set_models,
    switch_providers,
    validate_routes,
)

AI_SETTINGS = (
    "provider_enabled",
    "text_models",
    "vision_models",
    "max_completion_tokens",
    "max_ai_calls_per_day",
    "ai_retry_enabled",
    "reasoning_mode",
    "search_mode",
    "model_features",
    "minimum_ai_interval_seconds",
    "input_char_limit",
    "output_char_limit",
    "history_messages",
    "history_char_limit",
    "history_idle_seconds",
)
AI_SECRETS = (
    "groq_api_key",
    "cloudflare_account_id",
    "cloudflare_api_token",
    "google_api_key",
    "nvidia_api_key",
)


def _cookie_account(cookie: str) -> str | None:
    fields = {}
    for part in cookie.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator:
            fields[name] = value
    account = fields.get("c_user", "")
    if (
        account.isascii()
        and account.isdigit()
        and fields.get("xs")
        and "\n" not in cookie
        and "\r" not in cookie
    ):
        return account
    return None


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


def _ask_ai_key(secrets: dict, provider: str) -> None:
    if provider == "cloudflare":
        secrets["cloudflare_account_id"] = input(
            "Cloudflare Account ID (Enter để giữ cũ): "
        ).strip() or secrets.get("cloudflare_account_id", "")
    labels = {
        "google": "Google AI Studio",
        "nvidia": "NVIDIA",
        "groq": "Groq",
        "cloudflare": "Workers AI",
    }
    key = PROVIDER_KEYS[provider]
    secrets[key] = getpass.getpass(
        f"{labels[provider]} API key (Enter để giữ cũ): "
    ).strip() or secrets.get(key, "")


def _ask_models(
    provider: str, current: list[str], *, images: bool = False
) -> list[str] | None:
    label = "đọc ảnh" if images else "nhắn chữ"
    print(f"Model {label} {provider} hiện tại: {', '.join(current)}")
    try:
        entered = input(
            "Nhập mã model (nhiều mã cách nhau bằng dấu cách hoặc dấu phẩy; "
            "Enter để giữ danh sách trên): "
        ).strip()
    except EOFError:
        raise ValueError(
            "Chưa nhập mã model; dùng --models/--model hoặc --chain khi chạy không tương tác."
        ) from None
    if not entered:
        return None
    models = [model for model in re.split(r"[\s,]+", entered) if model]
    if not models:
        raise ValueError("Cần nhập ít nhất một mã model hoặc nhấn Enter để giữ cũ.")
    for model in models:
        model_target(f"{provider}:{model}")
    return models


def configure(*, provider: str | None = None, copy_ai_from: Path | None = None) -> None:
    if provider is not None and provider not in PROVIDER_KEYS:
        raise ValueError("Nguồn phải là google/nvidia/groq/cloudflare.")
    if provider is not None and copy_ai_from is not None:
        raise ValueError("Chỉ chọn --provider hoặc --copy-ai-from.")
    path = ROOT / "config.json"
    defaults = canonical_config(
        json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    )
    raw = read_config(ROOT) if path.exists() else dict(defaults)
    secrets = load_secrets(ROOT)
    print(
        "Nhập thông tin tại máy bạn. Không dán cookie hoặc API key vào GitHub/chat công khai."
    )
    if copy_ai_from is not None:
        source = copy_ai_from.expanduser().resolve()
        if source == ROOT.resolve():
            raise ValueError("Thư mục nguồn phải khác thư mục bot đang cấu hình.")
        if not (source / "config.json").is_file():
            raise ValueError(
                "Thư mục nguồn chưa có config.json; chọn bản bot đã cấu hình."
            )
        source_raw = read_config(source)
        source_secrets = load_secrets(source)
        raw.update({name: source_raw.get(name, defaults[name]) for name in AI_SETTINGS})
        secrets.update({name: source_secrets[name] for name in AI_SECRETS})
        cookie = getpass.getpass(
            "Cookie Facebook của acc này (nhập mới, không lấy từ bot nguồn): "
        ).strip()
    else:
        settings = Settings.from_dict(raw)
        targets = (*settings.text_targets, *settings.vision_targets)
        selected = provider or (targets[0][0] if targets else "groq")
        if not path.exists():
            raw["text_models"] = []
            raw["provider_enabled"] = {p: p == selected for p in PROVIDER_KEYS}
        if provider is not None or not path.exists():
            set_models(
                raw,
                selected,
                models_for(raw, selected) or DEFAULT_TEXT_MODELS[selected],
                primary=True,
            )
            raw["provider_enabled"][selected] = True
        if provider is not None or targets or not path.exists():
            _ask_ai_key(secrets, selected)
        cookie = (
            getpass.getpass(
                "Cookie Facebook dạng c_user=...; xs=...; (Enter để giữ cũ): "
            ).strip()
            or secrets["facebook_cookie"]
        )
    if not _cookie_account(cookie):
        raise ValueError("Cookie cần có ít nhất c_user và xs.")
    if os.environ.get("FACEBOOK_COOKIE") and os.environ["FACEBOOK_COOKIE"] != cookie:
        raise ValueError(
            "Biến môi trường FACEBOOK_COOKIE đang ghi đè cookie của acc này. Gỡ biến đó khỏi môi trường rồi cấu hình lại."
        )
    validate_routes(raw, secrets)
    private_json(ROOT / "secrets.json", {**secrets, "facebook_cookie": cookie})
    save_config(ROOT, raw)
    if copy_ai_from is not None:
        print(
            "Đã lấy cấu hình và key AI; cookie, người nhận, persona và data không được sao chép."
        )
    print(
        "Đã lưu cấu hình. Chưa gọi API/đăng nhập Messenger. Chạy providers rồi check-ai để kiểm tra."
    )


def providers(action: str | None = None, names: list[str] | None = None) -> None:
    raw = read_config(ROOT)
    if action is not None:
        switch_providers(raw, action, names or [])
        if action != "disable":
            validate_routes(raw, load_secrets(ROOT))
        save_config(ROOT, raw)
    describe_routes(raw)
    if action is not None:
        print("Đã lưu cờ bật/tắt; giữ model và key. Khởi động lại bot để áp dụng.")


def _ask_feature_mode(label: str, current: str) -> str:
    aliases = {
        "on": "on",
        "bật": "on",
        "bat": "on",
        "1": "on",
        "off": "off",
        "tắt": "off",
        "tat": "off",
        "2": "off",
        "auto": "auto",
        "tự động": "auto",
        "tu dong": "auto",
        "3": "auto",
    }
    try:
        value = (
            input(f"{label}: on=bật, off=tắt, auto=tự động (Enter giữ {current}): ")
            .strip()
            .casefold()
        )
    except EOFError:
        raise ValueError(
            "Chưa chọn tính năng; dùng --reasoning/--search khi chạy không tương tác."
        ) from None
    if not value:
        return current
    if value not in aliases:
        raise ValueError("Chọn on, off hoặc auto.")
    return aliases[value]


def configure_features(
    reasoning: str | None = None,
    search: str | None = None,
    *,
    model: str | None = None,
    show: bool = False,
    reset: bool = False,
) -> None:
    from .features import describe, modes

    raw = read_config(ROOT)
    settings = Settings.from_dict(raw)
    target = model_target(model) if model is not None else None
    if show and (reset or reasoning is not None or search is not None):
        raise ValueError("Dùng --show riêng để chỉ xem tính năng.")
    if show:
        describe(settings, targets=[target] if target else None)
        return
    if reset:
        if target is None or reasoning is not None or search is not None:
            raise ValueError("Dùng --model NGUỒN:MODEL --reset để bỏ cấu hình riêng.")
        overrides = {
            key: dict(options) for key, options in settings.model_features.items()
        }
        overrides.pop(model, None)
        raw["model_features"] = overrides
    else:
        current = (
            modes(settings, *target)
            if target
            else (settings.reasoning_mode, settings.search_mode)
        )
        if reasoning is None and search is None:
            reasoning = _ask_feature_mode("Suy luận", current[0])
            search = _ask_feature_mode("Tra cứu web", current[1])
        options = {
            name: value
            for name, value in (("reasoning", reasoning), ("search", search))
            if value is not None
        }
        if target:
            overrides = {
                key: dict(value) for key, value in settings.model_features.items()
            }
            overrides[model] = {**overrides.get(model, {}), **options}
            raw["model_features"] = overrides
        else:
            raw.update({f"{name}_mode": value for name, value in options.items()})
    settings = Settings.from_dict(raw)
    save_config(ROOT, raw)
    describe(settings, targets=[target] if target else None)
    print("Đã lưu lựa chọn. Chạy chat-ai để thử; khởi động lại bot để áp dụng.")


def configure_reactions(mode: str | None = None) -> None:
    raw = read_config(ROOT)
    if mode is not None:
        raw["reaction_mode"] = mode
        Settings.from_dict(raw)
        save_config(ROOT, raw)
    print("Cảm xúc tin nhắn: " + Settings.from_dict(raw).reaction_mode)
    if mode is not None:
        print("Đã lưu. Khởi động lại bot để áp dụng; chat-ai chỉ xem trước cảm xúc.")


def configure_ai(
    provider: str,
    daily_limit: int | None = None,
    fallback: bool | None = None,
    *,
    models: list[str] | None = None,
    disable: bool = False,
    only: bool = False,
    keep_key: bool = False,
) -> None:
    if provider not in PROVIDER_KEYS:
        raise ValueError("Nguồn phải là google/nvidia/groq/cloudflare.")
    if disable:
        if only or models is not None:
            raise ValueError("Dùng riêng --disable để tắt nguồn.")
        providers("disable", [provider])
        return
    raw = read_config(ROOT)
    previous = models_for(raw, provider)
    selected = list(models or previous or DEFAULT_TEXT_MODELS[provider])
    if models is not None or not previous:
        set_models(raw, provider, selected, primary=not previous)
    switch_providers(raw, "only" if only else "enable", [provider])
    if fallback is not None:
        if provider not in ("groq", "cloudflare"):
            raise ValueError(
                "--fallback chỉ dùng cho cặp Groq/Cloudflare; các nguồn khác dùng providers."
            )
        other = "groq" if provider == "cloudflare" else "cloudflare"
        if fallback and not models_for(raw, other):
            set_models(raw, other, DEFAULT_TEXT_MODELS[other])
        switch_providers(raw, "enable" if fallback else "disable", [other])
    if daily_limit is not None:
        raw["max_ai_calls_per_day"] = daily_limit
    Settings.from_dict(raw)
    secrets = load_secrets(ROOT)
    if not keep_key:
        _ask_ai_key(secrets, provider)
    validate_routes(raw, secrets)
    if not keep_key:
        private_json(ROOT / "secrets.json", secrets)
    save_config(ROOT, raw)
    describe_routes(raw)
    print(
        "Đã lưu model/key và cờ nguồn; chưa gọi API thật. Khởi động lại bot để áp dụng."
    )


async def list_models(provider: str) -> None:
    from .model_catalog import list_google_models

    if provider != "google":
        raise ValueError("Lệnh list-models hiện hỗ trợ Google.")
    models = await list_google_models(load_secrets(ROOT).get("google_api_key", ""))
    print("Google: mã model có generateContent do API trả về:")
    for model in models:
        print(model)
    print(
        "Danh sách này không xác nhận quota/billing hoặc khả năng đọc ảnh. "
        "Chạy configure-ai google rồi nhập mã model; "
        "không tự đổi cấu hình."
    )


def configure_google(
    models: list[str] | None = None, *, disable: bool = False, only: bool = False
) -> None:
    configure_ai("google", models=models, disable=disable, only=only)


def configure_nvidia(model: str | None = None, *, disable: bool = False) -> None:
    if disable:
        configure_ai("nvidia", disable=True)
        return
    raw = read_config(ROOT)
    current = (models_for(raw, "nvidia") or [NVIDIA_DEFAULT_MODEL])[0]
    selected = (
        model
        or input(f"Mã model NVIDIA (Enter để dùng {current}): ").strip()
        or current
    )
    configure_ai("nvidia", models=[selected])


def configure_vision(
    provider: str | None,
    model: str | None,
    *,
    disable: bool = False,
    chain: list[str] | None = None,
) -> None:
    from .ai import validate_connection, vision_configs

    raw = read_config(ROOT)
    if disable:
        if provider is not None or model is not None or chain is not None:
            raise ValueError("Dùng riêng --disable để tắt đọc ảnh.")
        raw["vision_models"] = []
        save_config(ROOT, raw)
        print("Đã tắt đọc ảnh; giữ cờ nguồn, key và cấu hình nhắn chữ.")
        return
    if chain is not None:
        if provider is not None or model is not None:
            raise ValueError(
                "Dùng --chain riêng với danh sách nguồn:model theo thứ tự."
            )
        secrets = load_secrets(ROOT)
        selected, omitted = list(chain), []
        if not selected:
            for target in VISION_PRESET:
                source = target.partition(":")[0]
                if (
                    raw["provider_enabled"][source]
                    and secrets.get(PROVIDER_KEYS[source], "").strip()
                ):
                    selected.append(target)
                elif source not in omitted:
                    omitted.append(source)
            if not selected:
                raise ValueError(
                    "Chưa có nguồn đọc ảnh đang bật và có key; xem providers."
                )
        raw["vision_models"] = selected
        sources = list(dict.fromkeys(model_target(target)[0] for target in selected))
        switch_providers(raw, "enable", sources)
        vision_configs(secrets, Settings.from_dict(raw))
        save_config(ROOT, raw)
        print("Thứ tự đọc ảnh:", " → ".join(selected))
        if omitted:
            print("Bỏ khỏi mẫu vì nguồn đang tắt hoặc chưa có key:", ", ".join(omitted))
        print("Dùng cờ nguồn chung; chạy check-vision --all rồi khởi động lại bot.")
        return
    if not provider or not model:
        raise ValueError(
            "Chọn nguồn và --model hỗ trợ ảnh, hoặc configure-vision --chain."
        )
    raw["vision_models"] = [f"{provider}:{model}"]
    switch_providers(raw, "enable", [provider])
    settings = Settings.from_dict(raw)
    secrets = load_secrets(ROOT)
    _ask_ai_key(secrets, provider)
    validate_connection(
        secrets[PROVIDER_KEYS[provider]],
        replace(settings, ai_provider=provider, model=model),
        secrets.get("cloudflare_account_id", ""),
    )
    vision_configs(secrets, settings)
    private_json(ROOT / "secrets.json", secrets)
    save_config(ROOT, raw)
    print(f"Nguồn đọc ảnh: {provider} / {model}.")
    print("Chưa kiểm tra API thật; chạy check-vision rồi khởi động lại bot.")


async def check_vision(*, all_models: bool = False) -> None:
    from .ai import AIError, VisionFallbackAI, create_vision_ai
    from .images import test_image
    from .state import State
    from .core import VIETNAM
    from datetime import datetime

    settings = Settings.load()
    if not settings.vision_targets:
        raise ValueError("Chưa bật đọc ảnh. Chạy configure-vision trước.")
    ai = create_vision_ai(load_secrets(), settings, load_persona(ROOT))
    state = None
    try:
        image = await asyncio.to_thread(test_image)
        state = State(ROOT / "data" / "ai-check.sqlite3")
        clients = (
            ai.clients if all_models and isinstance(ai, VisionFallbackAI) else (ai,)
        )
        failures = 0
        for candidate in clients:
            started = time.monotonic()
            try:
                text = await candidate.generate(
                    [
                        {
                            "role": "user",
                            "content": "Ảnh này có màu gì? Trả lời một câu ngắn.",
                        }
                    ],
                    lambda: state.reserve_ai(
                        datetime.now(VIETNAM).date().isoformat(),
                        settings.max_ai_calls_per_day,
                    ),
                    images=[image],
                )
                print(
                    f"{candidate.last_used} đã trả lời: {text[: settings.output_char_limit]}"
                )
            except AIError as error:
                if not all_models:
                    raise
                failures += 1
                print(f"{candidate.description}: {error}")
            print(
                f"Ảnh thử là ô màu đỏ. Thời gian: {time.monotonic() - started:.2f} giây."
            )
        print(
            "Chỉ thử chuỗi đọc ảnh, mỗi request tính một lượt thử; không kết nối/gửi Messenger."
        )
        if failures:
            raise AIError(
                f"Có {failures}/{len(clients)} model đọc ảnh chưa qua kiểm tra."
            )
    finally:
        await ai.close()
        if state is not None:
            state.close()


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

    raw = read_config(ROOT)
    settings = Settings.from_dict(raw)
    raw["text_models"] = list(
        dict.fromkeys(
            f"{provider}:{CHAT_MODELS.get(provider, model)}"
            for provider, model in settings.all_text_targets
        )
    )
    raw["max_replies_per_thread_per_day"] = max(
        settings.max_replies_per_thread_per_day, 1000
    )
    raw["max_ai_calls_per_day"] = max(settings.max_ai_calls_per_day, 1000)
    Settings.from_dict(raw)
    save_config(ROOT, raw)
    print(
        "Đã cập nhật model Groq/Cloudflare đang cấu hình; giữ cờ nguồn và model khác."
    )
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


def reset_context(thread: str, *, preview: bool = False) -> None:
    from .state import State

    if not THREAD_PATTERN.fullmatch(thread):
        raise ValueError(
            "Dùng mã cuộc trò chuyện lấy từ discover, dạng e2ee:… hoặc thread:…."
        )
    path = ROOT / "data" / ("preview.sqlite3" if preview else "state.sqlite3")
    if not path.is_file():
        raise ValueError("Chưa có dữ liệu ngữ cảnh trong chế độ đã chọn.")
    with instance_lock(ROOT / "data"):
        state = State(path)
        try:
            count = state.clear_history(thread)
        finally:
            state.close()
    print(f"Đã xóa {count} tin ngữ cảnh của cuộc trò chuyện đã chọn.")
    print("Giữ trạng thái chống gửi trùng, thời gian nhường và bộ đếm giới hạn.")


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

        models = [
            model for source, model in settings.text_targets if source == "nvidia"
        ]
        if not models:
            state.close()
            raise ValueError(
                "Chọn model NVIDIA bằng configure-nvidia và bật nguồn bằng providers enable nvidia trước."
            )
        ai = ChatAI(
            secrets["nvidia_api_key"],
            replace(settings, ai_provider="nvidia", model=models[0]),
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
    from .ai import create_ai, create_vision_ai
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
    image_ai = None
    bot = None
    report_task = None
    report_sender = None
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
                image_ai = create_vision_ai(secrets, settings, persona)
            await transport.connect()
            if discovery:
                print(
                    "DISCOVER: nhờ đúng người bạn muốn thử nhắn một tin mới. Chỉ in mã, không đọc nội dung ra màn hình và không gửi trả lời. Ctrl+C để dừng."
                )
            else:
                bot = ReplyBot(
                    settings, state, ai, transport, transport.own_id, image_ai=image_ai
                )
                if settings.call_summary_inbox:
                    from .call_reports import ReportSender

                    report_sender = ReportSender(settings, state, transport)
                    report_task = asyncio.create_task(report_sender.run())
                print("Cảm xúc tin nhắn:", settings.reaction_mode)
                print(f"AI: {ai.description}")
                from .features import describe

                describe(settings)
                print(
                    "Giữ lượt chờ khi AI lỗi tạm thời:",
                    "BẬT" if settings.ai_retry_enabled else "TẮT",
                )
                print(
                    f"Đọc ảnh: {image_ai.description if image_ai is not None else 'TẮT'}"
                )
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
            if report_task is not None:
                # Allow an already-started notification to finish before closing Messenger.
                report_sender.stop()
                try:
                    await asyncio.wait_for(asyncio.shield(report_task), 16)
                except TimeoutError:
                    report_task.cancel()
                    await asyncio.gather(report_task, return_exceptions=True)
            if bot is not None:
                await bot.close()
            await transport.close()
            if ai is not None:
                await ai.close()
            if image_ai is not None:
                await image_ai.close()
            if state is not None:
                state.close()


def main() -> None:
    os.umask(0o077)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Bot AI trả lời Messenger cá nhân, dùng NVIDIA, Google, Groq hoặc Cloudflare."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    call_lab = sub.add_parser(
        "call-lab", help="Thử Gemini Live với tiện ích Chrome; nhận cuộc gọi thủ công."
    )
    call_lab.add_argument("--port", type=int, default=8765)
    call_lab.add_argument("--model", default="gemini-3.8-live")
    call_lab.add_argument(
        "--voice",
        choices=("default", *VOICES),
        metavar="NAME",
        help="Tên giọng Google, ví dụ Kore, Puck, Aoede; default để dùng mặc định.",
    )
    call_lab.add_argument("--max-seconds", type=int, default=180)
    call_lab.add_argument(
        "--key-stdin",
        action="store_true",
        help="Đọc key Google từ một dòng stdin, không lưu key.",
    )
    initial_config = sub.add_parser(
        "configure", help="Nhập cookie và AI; có thể dùng lại AI của một bản bot khác."
    )
    initial_options = initial_config.add_mutually_exclusive_group()
    initial_options.add_argument(
        "--provider",
        choices=tuple(PROVIDER_KEYS),
        help="Chọn nguồn ngay khi cài mới.",
    )
    initial_options.add_argument(
        "--copy-ai-from",
        type=Path,
        metavar="THU_MUC",
        help="Lấy riêng AI/key từ bản bot khác; nhập cookie riêng.",
    )
    for name, help_text in (
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
    ai_config.add_argument("provider", choices=tuple(PROVIDER_KEYS))
    ai_config.add_argument(
        "--model",
        "--models",
        dest="models",
        nargs="+",
        help="Mã API tự chọn theo thứ tự; Google cũng cho nhập model mới.",
    )
    key_options = ai_config.add_mutually_exclusive_group()
    key_options.add_argument(
        "--keep-key",
        action="store_true",
        help="Dùng key hiện có, không hỏi hoặc ghi lại key.",
    )
    key_options.add_argument(
        "--edit-key", action="store_true", help="Yêu cầu nhập lại key khi chọn model."
    )
    model_list = sub.add_parser(
        "list-models", help="Lấy mã model Google từ API, không đổi cấu hình."
    )
    model_list.add_argument("provider", choices=("google",))
    feature_config = sub.add_parser(
        "features",
        help="Chọn bật/tắt/auto suy luận và tra cứu, chung hoặc riêng từng model.",
    )
    reaction_config = sub.add_parser(
        "reactions", help="Bật/tắt AI tự chọn cảm xúc theo ngữ cảnh."
    )
    reaction_config.add_argument("mode", nargs="?", choices=("auto", "off"))
    feature_config.add_argument("--reasoning", choices=("on", "off", "auto"))
    feature_config.add_argument("--search", choices=("on", "off", "auto"))
    feature_config.add_argument("--model", metavar="NGUỒN:MODEL")
    feature_view = feature_config.add_mutually_exclusive_group()
    feature_view.add_argument(
        "--show", action="store_true", help="Chỉ xem, không hỏi/lưu."
    )
    feature_view.add_argument(
        "--reset", action="store_true", help="Bỏ lựa chọn riêng của --model."
    )
    provider_command = sub.add_parser(
        "providers", help="Xem hoặc bật/tắt nguồn chung cho chữ và ảnh."
    )
    provider_command.add_argument(
        "action", nargs="?", choices=("enable", "disable", "only")
    )
    provider_command.add_argument("names", nargs="*", choices=tuple(PROVIDER_KEYS))
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
        help="Mã API Google tự chọn theo thứ tự ưu tiên.",
    )
    google_options.add_argument(
        "--disable", action="store_true", help="Tắt Google, giữ các nguồn cũ."
    )
    google_config.add_argument(
        "--only",
        action="store_true",
        help="Chỉ dùng Google cho chữ và chuỗi ảnh đang bật; giữ key các nguồn khác.",
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
    vision = sub.add_parser(
        "configure-vision",
        help="Chọn riêng nguồn/model đọc ảnh, giữ cấu hình nhắn chữ.",
    )
    vision.add_argument(
        "provider", nargs="?", choices=("nvidia", "google", "groq", "cloudflare")
    )
    vision.add_argument("--model", help="Mã model hỗ trợ ảnh, nhập thủ công.")
    vision_options = vision.add_mutually_exclusive_group()
    vision_options.add_argument("--disable", action="store_true")
    vision_options.add_argument(
        "--chain",
        nargs="*",
        metavar="NGUỒN:MODEL",
        help="Xoay model theo thứ tự; bỏ danh sách để dùng mẫu với các key hiện có.",
    )
    vision_check = sub.add_parser(
        "check-vision",
        help="Gửi ảnh thử màu đỏ qua chuỗi đọc ảnh, không gửi Messenger.",
    )
    vision_check.add_argument(
        "--all", action="store_true", help="Thử riêng từng model đọc ảnh."
    )
    allow = sub.add_parser(
        "allow", help="Thêm mã cuộc trò chuyện đã xác minh vào danh sách tự rep."
    )
    allow.add_argument("thread")
    scope = sub.add_parser("scope", help="Chọn phạm vi tự rep.")
    scope.add_argument("value", choices=("allowlist", "all_private"))
    reset = sub.add_parser(
        "reset-context",
        help="Xóa ngữ cảnh một chat; cần dừng bot trong thư mục này trước.",
    )
    reset.add_argument("thread", help="Mã cuộc trò chuyện lấy từ discover.")
    reset.add_argument(
        "--preview",
        action="store_true",
        help="Xóa ngữ cảnh xem trước thay vì gửi thật.",
    )
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
        if args.command == "call-lab":
            from .call_lab import CallLabError, run_lab

            try:
                asyncio.run(
                    run_lab(
                        ROOT,
                        port=args.port,
                        model=args.model,
                        max_seconds=args.max_seconds,
                        key_stdin=args.key_stdin,
                        voice=args.voice,
                    )
                )
            except CallLabError as error:
                raise ValueError(str(error)) from None
        elif args.command == "configure":
            configure(provider=args.provider, copy_ai_from=args.copy_ai_from)
        elif args.command == "configure-ai":
            models, keep_key = args.models, args.keep_key
            if models is None:
                raw = read_config(ROOT)
                current = models_for(raw, args.provider) or list(
                    DEFAULT_TEXT_MODELS[args.provider]
                )
                models = _ask_models(args.provider, current)
                secrets = load_secrets(ROOT)
                has_key = bool(secrets.get(PROVIDER_KEYS[args.provider], "").strip())
                if args.provider == "cloudflare":
                    has_key = has_key and bool(
                        secrets.get("cloudflare_account_id", "").strip()
                    )
                if has_key and not args.edit_key:
                    keep_key = True
                    print("Dùng key hiện có. Thêm --edit-key nếu muốn nhập lại key.")
            configure_ai(
                args.provider,
                args.daily_limit,
                args.fallback,
                models=models,
                keep_key=keep_key,
            )
        elif args.command == "list-models":
            asyncio.run(list_models(args.provider))
        elif args.command == "features":
            configure_features(
                args.reasoning,
                args.search,
                model=args.model,
                show=args.show,
                reset=args.reset,
            )
        elif args.command == "reactions":
            configure_reactions(args.mode)
        elif args.command == "providers":
            providers(args.action, args.names)
        elif args.command == "configure-google":
            configure_google(args.models, disable=args.disable, only=args.only)
        elif args.command == "configure-nvidia":
            configure_nvidia(args.model, disable=args.disable)
        elif args.command == "check-nvidia":
            asyncio.run(check_ai(provider="nvidia"))
        elif args.command == "configure-vision":
            if (
                args.provider
                and args.model is None
                and args.chain is None
                and not args.disable
            ):
                raw = read_config(ROOT)
                current = (
                    models_for(raw, args.provider, "vision_models")
                    or models_for(raw, args.provider)
                    or list(DEFAULT_TEXT_MODELS[args.provider])
                )
                models = _ask_models(args.provider, current, images=True) or current
                configure_vision(
                    None, None, chain=[f"{args.provider}:{model}" for model in models]
                )
            else:
                configure_vision(
                    args.provider, args.model, disable=args.disable, chain=args.chain
                )
        elif args.command == "check-vision":
            asyncio.run(check_vision(all_models=args.all))
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
        elif args.command == "reset-context":
            reset_context(args.thread, preview=args.preview)
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
