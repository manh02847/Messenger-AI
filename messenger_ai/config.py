from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOOGLE_MODELS = (
    "gemma-4-31b-it",
    "gemma-4-26b-a4b-it",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
)
NVIDIA_DEFAULT_MODEL = "google/gemma-4-31b-it"
NVIDIA_MODEL_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z"
)
VISION_PRESET = (
    "google:gemini-3.5-flash-lite",
    "google:gemini-3.1-flash-lite",
    "nvidia:google/gemma-4-31b-it",
    "groq:qwen/qwen3.8-27b",
    "cloudflare:@cf/qwen/qwen3.8-27b",
)
PROVIDER_KEYS = {
    "nvidia": "nvidia_api_key",
    "google": "google_api_key",
    "groq": "groq_api_key",
    "cloudflare": "cloudflare_api_token",
}


def valid_nvidia_model(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 200
        and bool(NVIDIA_MODEL_PATTERN.fullmatch(value))
    )


def vision_target(value: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ValueError("vision_models phải chứa mã nguồn:model.")
    provider, _, model = value.partition(":")
    if (
        provider not in PROVIDER_KEYS
        or not model
        or len(model) > 200
        or not re.fullmatch(r"[@A-Za-z0-9][A-Za-z0-9@._/-]*", model)
        or (provider == "nvidia" and not valid_nvidia_model(model))
        or (provider == "google" and model not in GOOGLE_MODELS)
        or (provider == "cloudflare" and not model.startswith("@cf/"))
    ):
        raise ValueError(
            "Model đọc ảnh chưa hợp lệ; dùng nguồn:model trong configure-vision --chain."
        )
    return provider, model


THREAD_PATTERN = re.compile(
    r"(?:e2ee:[0-9][0-9A-Za-z:._-]*@[A-Za-z0-9._-]+|thread:[1-9][0-9]*)\Z"
)


def load_persona(root: Path = ROOT) -> str:
    local = root / "persona.local.txt"
    path = local if local.exists() else root / "persona.txt"
    try:
        persona = path.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError):
        raise ValueError(
            f"Không đọc được {path.name}; kiểm tra file và mã hóa UTF-8."
        ) from None
    if not persona:
        raise ValueError(f"{path.name} đang rỗng.")
    return persona


def private_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix="config-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
        Path(temp).chmod(0o600)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


@dataclass(frozen=True)
class Settings:
    allowed_threads: tuple[str, ...] = ()
    reply_scope: str = "allowlist"
    ai_provider: str = "groq"
    ai_fallback: bool = False
    fallback_model: str = ""
    google_models: tuple[str, ...] = ()
    nvidia_model: str = ""
    vision_provider: str = ""
    vision_model: str = ""
    vision_models: tuple[str, ...] = ()
    model: str = "openai/gpt-oss-120b"
    dry_run: bool = True
    reply_prefix: str = ""
    debounce_seconds: float = 2.5
    reply_cooldown_seconds: float = 8
    manual_pause_seconds: float = 300
    max_message_age_seconds: float = 120
    history_messages: int = 12
    history_char_limit: int = 3500
    history_idle_seconds: float = 3600
    input_char_limit: int = 1200
    output_char_limit: int = 4000
    max_completion_tokens: int = 4096
    max_ai_calls_per_day: int = 150
    max_replies_per_thread_per_day: int = 1000
    minimum_ai_interval_seconds: float = 6
    retention_days: int = 7

    @property
    def vision_targets(self) -> tuple[tuple[str, str], ...]:
        if self.vision_models:
            return tuple(vision_target(value) for value in self.vision_models)
        if self.vision_provider:
            return ((self.vision_provider, self.vision_model),)
        return ()

    @classmethod
    def from_dict(cls, raw: dict) -> "Settings":
        if not isinstance(raw, dict):
            raise ValueError("config.json phải là một đối tượng JSON.")
        # Discard the retired experiment's flag when loading an existing config.
        value = dict(raw)
        value.pop("chatgpt_web", None)
        names = {field.name for field in fields(cls)}
        if set(value) - names:
            raise ValueError("config.json có tên tùy chọn không được hỗ trợ.")
        allowed = value.get("allowed_threads", [])
        if not isinstance(allowed, list) or any(
            not isinstance(item, str) or not THREAD_PATTERN.fullmatch(item)
            for item in allowed
        ):
            raise ValueError(
                "allowed_threads phải chứa mã cuộc trò chuyện lấy từ lệnh discover."
            )
        if len(allowed) != len(set(allowed)):
            raise ValueError("allowed_threads có mã bị trùng.")
        value["allowed_threads"] = tuple(allowed)
        google_models = value.get("google_models", [])
        if (
            not isinstance(google_models, list)
            or any(
                not isinstance(model, str) or model not in GOOGLE_MODELS
                for model in google_models
            )
            or len(set(google_models)) != len(google_models)
        ):
            raise ValueError(
                "google_models phải là danh sách model Google được hỗ trợ, không trùng."
            )
        value["google_models"] = tuple(google_models)
        vision_models = value.get("vision_models", [])
        if not isinstance(vision_models, list) or len(vision_models) > 12:
            raise ValueError("vision_models phải là danh sách tối đa 12 model đọc ảnh.")
        targets = [vision_target(model) for model in vision_models]
        if len(set(targets)) != len(targets):
            raise ValueError("vision_models có model bị trùng.")
        value["vision_models"] = tuple(vision_models)
        result = cls(**value)
        if (
            not isinstance(result.vision_provider, str)
            or not isinstance(result.vision_model, str)
            or result.vision_provider
            not in ("", "nvidia", "google", "groq", "cloudflare")
            or bool(result.vision_provider) != bool(result.vision_model)
            or (result.vision_models and result.vision_provider)
        ):
            raise ValueError(
                "vision_provider/vision_model phải cùng được chọn hoặc cùng rỗng; "
                "để rỗng khi dùng vision_models."
            )
        if result.vision_model:
            try:
                vision_target(f"{result.vision_provider}:{result.vision_model}")
            except ValueError:
                raise ValueError(
                    "vision_model chưa hợp lệ cho nguồn đã chọn; xem configure-vision."
                ) from None
        if result.nvidia_model != "" and not valid_nvidia_model(result.nvidia_model):
            raise ValueError(
                "nvidia_model phải là mã model dạng hãng/tên-model, hoặc chuỗi rỗng để tắt."
            )
        if result.reply_scope not in ("allowlist", "all_private"):
            raise ValueError("reply_scope phải là allowlist hoặc all_private.")
        if not isinstance(result.ai_fallback, bool):
            raise ValueError("ai_fallback phải là true hoặc false.")
        if not isinstance(result.fallback_model, str):
            raise ValueError("fallback_model phải là chuỗi.")
        if not isinstance(result.dry_run, bool):
            raise ValueError("dry_run phải là true hoặc false.")
        if result.ai_provider not in ("groq", "cloudflare", "google"):
            raise ValueError("ai_provider phải là groq, cloudflare hoặc google.")
        if result.ai_provider == "google" and result.ai_fallback:
            raise ValueError(
                "Nguồn chính Google không dùng ai_fallback Groq/Cloudflare."
            )
        if not isinstance(result.model, str) or not result.model.strip():
            raise ValueError("model phải là chuỗi không rỗng.")
        if result.ai_provider == "google" and result.model not in GOOGLE_MODELS:
            raise ValueError("model Google chưa được hỗ trợ.")
        if not isinstance(result.reply_prefix, str) or len(result.reply_prefix) > 40:
            raise ValueError("reply_prefix dài tối đa 40 ký tự.")
        for name in (
            "history_messages",
            "history_char_limit",
            "input_char_limit",
            "output_char_limit",
            "max_completion_tokens",
            "max_ai_calls_per_day",
            "max_replies_per_thread_per_day",
            "retention_days",
        ):
            number = getattr(result, name)
            if type(number) is not int or number <= 0:
                raise ValueError(f"{name} phải là số nguyên lớn hơn 0.")
        for name in (
            "debounce_seconds",
            "reply_cooldown_seconds",
            "manual_pause_seconds",
            "max_message_age_seconds",
            "minimum_ai_interval_seconds",
            "history_idle_seconds",
        ):
            number = getattr(result, name)
            if (
                isinstance(number, bool)
                or not isinstance(number, (float, int))
                or not math.isfinite(number)
                or number < 0
            ):
                raise ValueError(f"{name} phải là số hữu hạn không âm.")
        if (
            result.max_message_age_seconds <= 0
            or result.history_char_limit > 12000
            or result.max_completion_tokens > 4096
        ):
            raise ValueError("Giới hạn tuổi tin, lịch sử hoặc token chưa phù hợp.")
        return result

    @classmethod
    def load(cls, root: Path = ROOT) -> "Settings":
        path = root / "config.json"
        if not path.exists():
            raise ValueError("Chạy lệnh configure để tạo cấu hình trước.")
        raw = json.loads(path.read_text(encoding="utf-8"))
        result = cls.from_dict(raw)
        if "chatgpt_web" in raw:
            raw.pop("chatgpt_web")
            private_json(path, raw)
        return result


def load_secrets(root: Path = ROOT) -> dict[str, str]:
    path = root / "secrets.json"
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(raw, dict):
        raise ValueError("secrets.json phải là một đối tượng JSON.")
    secrets = {
        "nvidia_api_key": os.environ.get("NVIDIA_API_KEY")
        or raw.get("nvidia_api_key", ""),
        "google_api_key": os.environ.get("GEMINI_API_KEY")
        or raw.get("google_api_key", ""),
        "cloudflare_api_token": os.environ.get("CLOUDFLARE_API_TOKEN")
        or raw.get("cloudflare_api_token", ""),
        "cloudflare_account_id": os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        or raw.get("cloudflare_account_id", ""),
        "groq_api_key": os.environ.get("GROQ_API_KEY") or raw.get("groq_api_key", ""),
        "facebook_cookie": os.environ.get("FACEBOOK_COOKIE")
        or raw.get("facebook_cookie", ""),
    }
    if any(not isinstance(value, str) for value in secrets.values()):
        raise ValueError("API key và cookie phải là chuỗi.")
    return secrets
