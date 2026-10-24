import json
from copy import deepcopy
from unittest.mock import Mock

import httpx
import pytest

from messenger_ai import ai as module, cli
from messenger_ai.ai import AIError, ChatAI, create_ai, create_vision_ai
from messenger_ai.config import (
    PROVIDER_KEYS,
    Settings,
    canonical_config,
    read_config,
)
from messenger_ai.images import test_image as red_image

MODELS = {
    "nvidia": "google/gemma-4-31b-it",
    "google": "gemini-3.5-flash-lite",
    "groq": "qwen/qwen3.8-27b",
    "cloudflare": "@cf/qwen/qwen3.8-27b",
}
SECRETS = {key: "PRIVATE_" + key for key in PROVIDER_KEYS.values()}
SECRETS.update(
    cloudflare_account_id="a" * 32, facebook_cookie="c_user=111; xs=PRIVATE;"
)


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "load_secrets", lambda *_: dict(SECRETS))
    raw = {
        "provider_enabled": {provider: True for provider in PROVIDER_KEYS},
        "text_models": [f"{p}:{m}" for p, m in MODELS.items()],
        "vision_models": [
            f"{p}:{MODELS[p]}" for p in ("google", "nvidia", "groq", "cloudflare")
        ],
        "reply_scope": "all_private",
        "history_messages": 17,
        "minimum_ai_interval_seconds": 0,
    }
    (tmp_path / "config.json").write_text(json.dumps(raw))
    (tmp_path / "secrets.json").write_text(json.dumps(SECRETS))
    (tmp_path / "persona.local.txt").write_text("PRIVATE PERSONA")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "state.sqlite3").write_bytes(b"PRIVATE HISTORY")
    return tmp_path, raw


@pytest.mark.parametrize("provider", PROVIDER_KEYS)
def test_disable_enable_is_identical_for_all_sources_and_never_erases_models_or_keys(
    account, provider
):
    root, raw = account
    before = {
        str(p): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and p.name != "config.json"
    }
    cli.providers("disable", [provider])
    settings = Settings.load(root)
    assert settings.provider_flags[provider] is False
    assert provider not in {
        p for p, _ in (*settings.text_targets, *settings.vision_targets)
    }
    assert list(settings.text_models) == raw["text_models"]
    assert list(settings.vision_models) == raw["vision_models"]
    cli.providers("enable", [provider])
    assert json.loads((root / "config.json").read_text()) == raw
    assert {
        str(p): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and p.name != "config.json"
    } == before


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDER_KEYS)
@pytest.mark.parametrize("images", [False, True])
@pytest.mark.parametrize("failed", [False, True])
async def test_only_source_controls_both_real_payload_paths_even_on_failures(
    account, monkeypatch, provider, images, failed
):
    root, _ = account
    cli.providers("only", [provider])
    settings = Settings.load(root)
    only_secret = {
        PROVIDER_KEYS[provider]: SECRETS[PROVIDER_KEYS[provider]],
        "cloudflare_account_id": "a" * 32,
    }
    requests, reserved = [], []

    async def no_wait(_):
        pass

    monkeypatch.setattr(module.asyncio, "sleep", no_wait)

    def handler(request):
        requests.append(request)
        expected = {
            "google": "generativelanguage.googleapis.com",
            "nvidia": "integrate.api.nvidia.com",
            "groq": "api.groq.com",
            "cloudflare": "api.cloudflare.com",
        }[provider]
        assert request.url.host == expected
        if failed:
            return httpx.Response(
                429, headers={"retry-after": "1"}, text="PRIVATE RESPONSE"
            )
        if provider == "google":
            body = {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "Màu đỏ."}]},
                    }
                ]
            }
        else:
            body = {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "Màu đỏ."}}
                ]
            }
        return httpx.Response(200, json=body)

    def reserve():
        reserved.append(True)
        return True

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(
            module,
            "ChatAI",
            lambda *args, **kwargs: ChatAI(*args, client=client, **kwargs),
        )
        ai = (create_vision_ai if images else create_ai)(
            only_secret, settings, "PRIVATE PERSONA"
        )
        options = {"images": [red_image()]} if images else {}
        if failed:
            with pytest.raises(AIError):
                await ai.generate(
                    [{"role": "user", "content": "Ảnh này có gì?"}], reserve, **options
                )
        else:
            assert (
                await ai.generate(
                    [{"role": "user", "content": "Ảnh này có gì?"}], reserve, **options
                )
                == "Màu đỏ."
            )
        await ai.close()
    assert 1 <= len(requests) == len(reserved) <= 3


@pytest.mark.asyncio
async def test_all_disabled_creates_no_http_clients_or_budget_reservations(
    account, monkeypatch
):
    root, _ = account
    cli.providers("disable", list(PROVIDER_KEYS))
    factory = Mock(side_effect=AssertionError("Disabled sources cannot create clients"))
    monkeypatch.setattr(module, "ChatAI", factory)
    settings, reserve = Settings.load(root), Mock()
    ai = create_ai({}, settings, "Persona")
    assert create_vision_ai({}, settings, "Persona") is None
    with pytest.raises(AIError, match="Chưa bật nguồn"):
        await ai.generate([], reserve)
    await ai.close()
    factory.assert_not_called()
    reserve.assert_not_called()


@pytest.mark.parametrize(
    "old,expected_text,expected_vision",
    [
        ({}, [("groq", "openai/gpt-oss-120b")], []),
        (
            {"ai_provider": "cloudflare", "model": "@cf/custom", "ai_fallback": True},
            [("cloudflare", "@cf/custom"), ("groq", "openai/gpt-oss-120b")],
            [],
        ),
        (
            {"nvidia_model": MODELS["nvidia"], "google_models": [MODELS["google"]]},
            [
                ("nvidia", MODELS["nvidia"]),
                ("google", MODELS["google"]),
                ("groq", "openai/gpt-oss-120b"),
            ],
            [],
        ),
        (
            {
                "ai_provider": "google",
                "model": MODELS["google"],
                "google_models": [MODELS["google"]],
                "vision_models": [f"google:{MODELS['google']}"],
            },
            [("google", MODELS["google"])],
            [("google", MODELS["google"])],
        ),
        (
            {
                "ai_provider": "cloudflare",
                "model": "@cf/custom",
                "vision_provider": "groq",
                "vision_model": MODELS["groq"],
            },
            [("cloudflare", "@cf/custom")],
            [("groq", MODELS["groq"])],
        ),
    ],
)
def test_legacy_conversion_preserves_exact_text_and_image_order_without_enabling_extra_routes(
    old, expected_text, expected_vision
):
    before = deepcopy(old)
    modern = canonical_config(old)
    settings = Settings.from_dict(modern)
    assert settings.text_targets == tuple(expected_text)
    assert settings.vision_targets == tuple(expected_vision)
    assert old == before
    assert canonical_config(modern) == modern
    assert not {
        "ai_provider",
        "model",
        "nvidia_model",
        "ai_fallback",
        "vision_provider",
    }.intersection(modern)


def test_migration_backup_is_private_created_once_and_changes_only_route_schema(
    account,
):
    root, _ = account
    old = {
        "ai_provider": "google",
        "model": MODELS["google"],
        "reply_scope": "all_private",
        "history_messages": 17,
    }
    (root / "config.json").write_text(json.dumps(old))
    cli.providers("only", ["google"])
    backup = root / "config.before-providers.bak"
    assert json.loads(backup.read_text()) == old
    assert backup.stat().st_mode & 0o777 == 0o600
    assert (root / "config.json").stat().st_mode & 0o777 == 0o600
    cli.providers("disable", ["google"])
    assert json.loads(backup.read_text()) == old
    assert Settings.load(root).history_messages == 17
    assert (root / "persona.local.txt").read_text() == "PRIVATE PERSONA"
    assert (root / "data" / "state.sqlite3").read_bytes() == b"PRIVATE HISTORY"


def test_show_is_read_only_offline_and_never_reads_or_prints_secrets(
    account, monkeypatch, capsys
):
    root, _ = account
    before = (root / "config.json").read_bytes()
    monkeypatch.setattr(
        cli,
        "load_secrets",
        Mock(side_effect=AssertionError("No credential access for show")),
    )
    cli.providers()
    assert (root / "config.json").read_bytes() == before
    assert "PRIVATE" not in capsys.readouterr().out


def test_enable_without_key_or_models_never_writes_partial_state(account, monkeypatch):
    root, raw = account
    raw["provider_enabled"]["nvidia"] = False
    (root / "config.json").write_text(json.dumps(raw))
    monkeypatch.setattr(cli, "load_secrets", lambda *_: {})
    before = (root / "config.json").read_bytes()
    with pytest.raises(ValueError, match="NVIDIA"):
        cli.providers("only", ["nvidia"])
    assert (root / "config.json").read_bytes() == before
    raw["text_models"] = [t for t in raw["text_models"] if not t.startswith("nvidia:")]
    raw["vision_models"] = [
        t for t in raw["vision_models"] if not t.startswith("nvidia:")
    ]
    (root / "config.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="chưa có model"):
        cli.providers("enable", ["nvidia"])
    assert read_config(root) == raw


@pytest.mark.parametrize(
    "flags",
    [
        None,
        {"google": True},
        {**dict.fromkeys(PROVIDER_KEYS, False), "unknown": True},
        dict.fromkeys(PROVIDER_KEYS, "false"),
    ],
)
def test_flags_are_explicit_booleans_for_known_providers(flags):
    with pytest.raises(ValueError, match="provider_enabled"):
        Settings.from_dict({"text_models": [], "provider_enabled": flags})


@pytest.mark.parametrize("all_disabled", [False, True])
def test_cookie_update_never_reorders_models_or_reenables_disabled_providers(
    account, monkeypatch, all_disabled
):
    root, raw = account
    raw["text_models"] = list(reversed(raw["text_models"]))
    if all_disabled:
        raw["provider_enabled"] = dict.fromkeys(PROVIDER_KEYS, False)
    (root / "config.json").write_text(json.dumps(raw))
    (root / "config.example.json").write_text(json.dumps(raw))
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "")
    monkeypatch.setattr("builtins.input", lambda _: "")
    cli.configure()
    assert read_config(root) == raw


@pytest.mark.parametrize("provider", ["google", "nvidia"])
def test_fresh_setup_with_any_provider_never_requires_an_unrelated_main_api(
    account, monkeypatch, provider
):
    root, _ = account
    (root / "config.json").unlink()
    (root / "config.example.json").write_text(json.dumps(canonical_config({})))
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda *_: {
            key: ""
            for key in (
                *PROVIDER_KEYS.values(),
                "cloudflare_account_id",
                "facebook_cookie",
            )
        },
    )
    answers = iter(["PRIVATE_SELECTED_KEY", "c_user=222; xs=PRIVATE_NEW;"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: next(answers))
    cli.configure(provider=provider)
    settings = Settings.load(root)
    assert settings.provider_flags == {
        source: source == provider for source in PROVIDER_KEYS
    }
    assert settings.text_targets and all(
        source == provider for source, _ in settings.text_targets
    )
    secrets = json.loads((root / "secrets.json").read_text())
    assert secrets[PROVIDER_KEYS[provider]] == "PRIVATE_SELECTED_KEY"
    assert not secrets["groq_api_key"]


@pytest.mark.asyncio
async def test_interleaved_provider_order_does_not_spend_googles_pool_time_on_other_apis():
    from messenger_ai.ai import FallbackAI, ProviderUnavailable

    now, calls = [100.0], []

    class Source:
        def __init__(self, provider, model, delay, available):
            self.provider = provider
            self.settings = Settings(ai_provider=provider, model=model)
            self.label = self.description = model
            self.delay, self.available = delay, available

        async def generate(self, history, reserve):
            calls.append(self.description)
            assert reserve()
            now[0] += self.delay
            if not self.available:
                raise ProviderUnavailable("Temporarily unavailable", 30)
            return "OK"

    sources = [
        Source("google", "gemini-3.5-flash-lite", 1, False),
        Source("nvidia", "owner/model", 30, False),
        Source("google", "gemini-3.1-flash-lite", 1, True),
    ]
    ai = FallbackAI(*sources, clock=lambda: now[0], log=lambda _: None)
    assert await ai.generate([{"role": "user", "content": "Hi"}], lambda: True) == "OK"
    assert calls == [source.description for source in sources]


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ([], (None, [])),
        (["only", "google"], ("only", ["google"])),
        (["disable", "nvidia", "groq"], ("disable", ["nvidia", "groq"])),
    ],
)
def test_generic_cli_dispatch_is_the_same_for_every_provider(
    monkeypatch, arguments, expected
):
    handler = Mock()
    monkeypatch.setattr(cli, "providers", handler)
    monkeypatch.setattr("sys.argv", ["messenger_ai", "providers", *arguments])
    cli.main()
    handler.assert_called_once_with(*expected)
