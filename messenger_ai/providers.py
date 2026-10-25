"""Shared provider switches and model lists; credentials stay in secrets.json."""

from .config import (
    DEFAULT_MODELS,
    GOOGLE_DEFAULT_MODELS,
    NVIDIA_DEFAULT_MODEL,
    PROVIDER_KEYS,
    Settings,
)


DEFAULT_TEXT_MODELS = {
    **{provider: (model,) for provider, model in DEFAULT_MODELS.items()},
    "google": GOOGLE_DEFAULT_MODELS,
    "nvidia": (NVIDIA_DEFAULT_MODEL,),
}


def models_for(raw: dict, provider: str, kind: str = "text_models") -> list[str]:
    return [
        target.partition(":")[2]
        for target in raw[kind]
        if target.partition(":")[0] == provider
    ]


def set_models(
    raw: dict, provider: str, models, kind: str = "text_models", *, primary=False
) -> None:
    targets = [f"{provider}:{model}" for model in models]
    previous = raw[kind]
    positions = [
        i for i, target in enumerate(previous) if target.partition(":")[0] == provider
    ]
    others = [target for target in previous if target.partition(":")[0] != provider]
    position = min(positions[0], len(others)) if positions else len(others)
    if primary and kind == "text_models":
        prefix = (
            ("nvidia", "google")
            if provider in ("groq", "cloudflare")
            else (("nvidia",) if provider == "google" else ())
        )
        position = next(
            (
                i
                for i, target in enumerate(others)
                if target.partition(":")[0] not in prefix
            ),
            len(others),
        )
    raw[kind] = others[:position] + targets + others[position:]


def switch_providers(raw: dict, action: str, providers: list[str]) -> None:
    if (
        not providers
        or len(set(providers)) != len(providers)
        or any(p not in PROVIDER_KEYS for p in providers)
    ):
        raise ValueError("Chọn tên nguồn google/nvidia/groq/cloudflare, không trùng.")
    if action not in ("enable", "disable", "only"):
        raise ValueError("Dùng providers enable, disable hoặc only.")
    for provider in providers:
        if action != "disable" and not any(
            models_for(raw, provider, kind) for kind in ("text_models", "vision_models")
        ):
            raise ValueError(
                f"{provider} chưa có model; chạy configure-ai {provider} --model MÃ_MODEL trước."
            )
    if action == "only":
        raw["provider_enabled"] = {p: p in providers for p in PROVIDER_KEYS}
    else:
        for provider in providers:
            raw["provider_enabled"][provider] = action == "enable"
    Settings.from_dict(raw)


def validate_routes(raw: dict, secrets: dict) -> None:
    from .ai import provider_configs, vision_configs

    settings = Settings.from_dict(raw)
    provider_configs(secrets, settings)
    vision_configs(secrets, settings)


def describe_routes(raw: dict, log=print) -> None:
    settings = Settings.from_dict(raw)
    for provider, enabled in settings.provider_flags.items():
        text = ", ".join(models_for(raw, provider)) or "chưa chọn"
        images = ", ".join(models_for(raw, provider, "vision_models")) or "chưa chọn"
        log(f"{provider}: {'BẬT' if enabled else 'TẮT'} | chữ: {text} | ảnh: {images}")
    for label, targets in (
        ("Chữ đang dùng", settings.text_targets),
        ("Ảnh đang dùng", settings.vision_targets),
    ):
        log(f"{label}: " + (" → ".join(f"{p}:{m}" for p, m in targets) or "TẮT"))
