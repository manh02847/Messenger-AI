import json
from dataclasses import asdict
from unittest.mock import Mock

import httpx
import pytest

from messenger_ai import ai as module, cli
from messenger_ai.ai import (
    AIError,
    ChatAI,
    create_ai,
    create_vision_ai,
    provider_configs,
)
from messenger_ai.config import VISION_PRESET, Settings, load_secrets
from messenger_ai.images import test_image as red_image

MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    for name in (
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "NVIDIA_API_KEY",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
        "FACEBOOK_COOKIE",
    ):
        monkeypatch.delenv(name, raising=False)
    raw = {
        "ai_provider": "cloudflare",
        "model": "@cf/qwen/qwen3.8-27b",
        "ai_fallback": True,
        "fallback_model": "qwen/qwen3.8-27b",
        "nvidia_model": "google/gemma-4-31b-it",
        "google_models": MODELS,
        "vision_models": list(VISION_PRESET),
        "reply_scope": "all_private",
        "max_ai_calls_per_day": 1000,
        "history_messages": 18,
    }
    secrets = {
        "google_api_key": "PRIVATE_GOOGLE_KEY",
        "facebook_cookie": "c_user=111; xs=PRIVATE;",
    }
    (tmp_path / "config.json").write_text(json.dumps(raw))
    (tmp_path / "secrets.json").write_text(json.dumps(secrets))
    (tmp_path / "config.example.json").write_text(json.dumps({}))
    (tmp_path / "persona.local.txt").write_text("PRIVATE PERSONA")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "state.sqlite3").write_bytes(b"PRIVATE HISTORY")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "")
    return tmp_path, raw


@pytest.mark.parametrize("previous_vision", ["chain", "single", "off"])
def test_only_google_removes_every_other_route_and_preserves_private_data(
    account, monkeypatch, capsys, previous_vision
):
    root, raw = account
    if previous_vision != "chain":
        raw.pop("vision_models")
        if previous_vision == "single":
            raw.update(vision_provider="nvidia", vision_model="google/gemma-4-31b-it")
        (root / "config.json").write_text(json.dumps(raw))
    factory = Mock(side_effect=AssertionError("Configuration must not call APIs"))
    monkeypatch.setattr(module, "ChatAI", factory)
    cli.configure_google(only=True)
    settings = Settings.load(root)
    configs = provider_configs(load_secrets(root), settings)
    assert [c.model for _, c, _ in configs] == MODELS
    assert all(c.ai_provider == "google" for _, c, _ in configs)
    assert settings.provider_flags == {
        "nvidia": False,
        "google": True,
        "groq": False,
        "cloudflare": False,
    }
    if previous_vision in ("off", "single"):
        assert not settings.vision_targets
    else:
        assert settings.vision_targets == tuple(("google", model) for model in MODELS)
    result = json.loads((root / "config.json").read_text())
    for name in ("reply_scope", "max_ai_calls_per_day", "history_messages"):
        assert result[name] == raw[name]
    assert (root / "persona.local.txt").read_text() == "PRIVATE PERSONA"
    assert (root / "data" / "state.sqlite3").read_bytes() == b"PRIVATE HISTORY"
    assert load_secrets(root)["facebook_cookie"] == "c_user=111; xs=PRIVATE;"
    assert "PRIVATE" not in capsys.readouterr().out
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_images", [False, True])
@pytest.mark.parametrize("all_down", [False, True])
async def test_only_google_runtime_never_sends_to_other_hosts_even_after_all_google_models_fail(
    account, monkeypatch, with_images, all_down
):
    root, _ = account
    cli.configure_google(only=True)
    settings = Settings.load(root)
    settings = Settings(**{**asdict(settings), "minimum_ai_interval_seconds": 0})
    requests, budget = [], []

    def handler(request):
        requests.append(request)
        assert request.url.host == "generativelanguage.googleapis.com"
        if all_down or len(requests) == 1:
            return httpx.Response(
                503, headers={"retry-after": "3"}, text="PRIVATE SERVER BODY"
            )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "Màu đỏ."}]},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(
            module,
            "ChatAI",
            lambda *args, **kwargs: ChatAI(*args, client=client, **kwargs),
        )
        factory = create_vision_ai if with_images else create_ai
        ai = factory(load_secrets(root), settings, "PRIVATE PERSONA")
        options = {"images": [red_image()]} if with_images else {}

        def reserve():
            budget.append(True)
            return True

        if all_down:
            with pytest.raises(AIError):
                await ai.generate(
                    [{"role": "user", "content": "Ảnh gì đây?"}], reserve, **options
                )
        else:
            assert (
                await ai.generate(
                    [{"role": "user", "content": "Ảnh gì đây?"}], reserve, **options
                )
                == "Màu đỏ."
            )
        await ai.close()
    assert len(requests) == len(budget) == 2
    assert all(model in str(request.url) for model, request in zip(MODELS, requests))


def test_only_google_keeps_other_provider_keys_available_for_later(account):
    root, _ = account
    secrets = load_secrets(root)
    secrets.update(
        groq_api_key="PRIVATE_GROQ",
        nvidia_api_key="PRIVATE_NVIDIA",
        cloudflare_api_token="PRIVATE_CF",
        cloudflare_account_id="a" * 32,
    )
    (root / "secrets.json").write_text(json.dumps(secrets))
    cli.configure_google(MODELS, only=True)
    assert load_secrets(root) == secrets


def test_only_without_models_keeps_the_independently_selected_google_vision_order(
    account,
):
    root, raw = account
    raw["vision_models"] = [
        "groq:qwen/qwen3.8-27b",
        *[f"google:{m}" for m in reversed(MODELS)],
    ]
    (root / "config.json").write_text(json.dumps(raw))
    cli.configure_google(only=True)
    settings = Settings.load(root)
    assert settings.text_targets == tuple(("google", model) for model in MODELS)
    assert settings.vision_targets == tuple(("google", m) for m in reversed(MODELS))


def test_failed_google_key_does_not_leave_partially_disabled_sources(account):
    root, _ = account
    (root / "secrets.json").write_text("{}")
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="Google"):
        cli.configure_google(MODELS, only=True)
    assert {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_cookie_update_in_google_only_mode_never_asks_for_other_keys(
    account, monkeypatch
):
    root, _ = account
    cli.configure_google(MODELS, only=True)
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return ""

    monkeypatch.setattr(cli.getpass, "getpass", answer)
    cli.configure()
    assert len(prompts) == 2
    assert "Google" in prompts[0] and "Cookie" in prompts[1]
    assert all(provider == "google" for provider, _ in Settings.load(root).text_targets)


def test_google_only_can_be_disabled_without_losing_models(account):
    root, _ = account
    cli.configure_google(MODELS, only=True)
    before = Settings.load(root).all_text_targets
    cli.configure_google(disable=True)
    settings = Settings.load(root)
    assert not settings.text_targets and not settings.vision_targets
    assert settings.all_text_targets == before


def test_only_flag_conflicts_with_disable_without_writing_files(account):
    root, _ = account
    before = (root / "config.json").read_bytes()
    with pytest.raises(ValueError, match="Dùng riêng"):
        cli.configure_google(only=True, disable=True)
    assert (root / "config.json").read_bytes() == before


def test_google_only_cli_dispatches_selected_model_order(account, monkeypatch):
    configure = Mock()
    monkeypatch.setattr(cli, "configure_google", configure)
    monkeypatch.setattr(
        "sys.argv", ["messenger_ai", "configure-google", "--only", "--models", *MODELS]
    )
    cli.main()
    configure.assert_called_once_with(MODELS, disable=False, only=True)


def test_single_google_primary_does_not_require_another_provider_key():
    settings = Settings.from_dict({"ai_provider": "google", "model": MODELS[0]})
    configs = provider_configs({"google_api_key": "PRIVATE"}, settings)
    assert len(configs) == 1 and configs[0][1].ai_provider == "google"
