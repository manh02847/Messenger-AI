import base64
import io
import json
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image
import httpx

from messenger_ai import cli
from messenger_ai.ai import AIError
from messenger_ai.config import VISION_PRESET, Settings, canonical_config


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda *args: {
            "nvidia_api_key": "PRIVATE_NVIDIA_KEY",
            "groq_api_key": "PRIVATE_GROQ_KEY",
            "google_api_key": "PRIVATE_GOOGLE_KEY",
            "cloudflare_api_token": "PRIVATE_CF_KEY",
            "cloudflare_account_id": "a" * 32,
            "facebook_cookie": "c_user=111; xs=PRIVATE;",
        },
    )
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "")
    raw = {
        "ai_provider": "groq",
        "model": "custom-text-model",
        "nvidia_model": "owner/custom-model",
        "history_idle_seconds": 1800,
        "reply_scope": "all_private",
        "dry_run": False,
    }
    (tmp_path / "config.json").write_text(json.dumps(raw))
    (tmp_path / "persona.local.txt").write_text("PRIVATE PERSONA")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "messenger-device.db").write_bytes(b"PRIVATE DEVICE")
    return tmp_path, raw


def test_configure_vision_manual_model_keeps_text_models_persona_and_data(
    account, monkeypatch, capsys
):
    root, raw = account
    factory = Mock(side_effect=AssertionError("Must not call API or construct client"))
    monkeypatch.setattr("messenger_ai.ai.ChatAI", factory)
    cli.configure_vision("nvidia", "owner/manually-selected-vision-model")
    assert json.loads((root / "config.json").read_text()) == canonical_config(
        dict(
            raw,
            vision_provider="nvidia",
            vision_model="owner/manually-selected-vision-model",
        )
    )
    assert (root / "persona.local.txt").read_text() == "PRIVATE PERSONA"
    assert (root / "data" / "messenger-device.db").read_bytes() == b"PRIVATE DEVICE"
    assert (root / "secrets.json").stat().st_mode & 0o777 == 0o600
    assert "PRIVATE" not in capsys.readouterr().out
    factory.assert_not_called()


def test_disable_vision_does_not_require_key_or_change_text_provider(
    account, monkeypatch
):
    root, raw = account
    cli.configure_vision("nvidia", "google/gemma-4-31b-it")
    secret_before = (root / "secrets.json").read_bytes()
    monkeypatch.setattr(
        cli, "load_secrets", Mock(side_effect=AssertionError("No credentials needed"))
    )
    cli.configure_vision(None, None, disable=True)
    assert json.loads((root / "config.json").read_text()) == canonical_config(raw)
    assert (root / "secrets.json").read_bytes() == secret_before


@pytest.mark.parametrize(
    "provider,model,disable",
    [
        (None, None, False),
        ("nvidia", "bad model", False),
        ("google", "bad model", False),
        ("nvidia", None, True),
    ],
)
def test_invalid_vision_configuration_does_not_write_files(
    account, provider, model, disable
):
    root, _ = account
    before = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    with pytest.raises(ValueError):
        cli.configure_vision(provider, model, disable=disable)
    after = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_check_vision_uses_private_persona_red_sample_shared_check_budget_and_closes(
    account, monkeypatch, capsys, failure
):
    root, _ = account
    settings = Settings(vision_provider="nvidia", vision_model="google/gemma-4-31b-it")
    monkeypatch.setattr(Settings, "load", lambda: settings)
    calls = []

    async def generate(history, reserve, *, images):
        calls.append((history, images))
        assert reserve()
        assert len(images) == 1
        with Image.open(io.BytesIO(base64.b64decode(images[0].data))) as image:
            red, green, blue = image.getpixel((0, 0))
            assert red > 240 and green < 10 and blue < 10
        if failure:
            raise AIError("Test vision failure")
        return "Màu đỏ."

    ai = Mock(last_used="Test image source", generate=generate, close=AsyncMock())
    factory = Mock(return_value=ai)
    monkeypatch.setattr("messenger_ai.ai.create_vision_ai", factory)
    if failure:
        with pytest.raises(AIError, match="vision failure"):
            await cli.check_vision()
    else:
        await cli.check_vision()
        assert "Màu đỏ." in capsys.readouterr().out
    assert factory.call_args.args[2] == "PRIVATE PERSONA"
    assert (root / "data" / "ai-check.sqlite3").is_file()
    assert not (root / "data" / "state.sqlite3").exists()
    assert (root / "data" / "messenger-device.db").read_bytes() == b"PRIVATE DEVICE"
    assert len(calls) == 1
    ai.close.assert_awaited_once()


def test_vision_cli_dispatch(account, monkeypatch):
    configure = Mock()
    monkeypatch.setattr(cli, "configure_vision", configure)
    monkeypatch.setattr(
        "sys.argv",
        [
            "messenger_ai",
            "configure-vision",
            "nvidia",
            "--model",
            "google/gemma-4-31b-it",
        ],
    )
    cli.main()
    configure.assert_called_once_with(
        "nvidia", "google/gemma-4-31b-it", disable=False, chain=None
    )


def test_configure_chain_uses_existing_keys_without_prompting_or_changing_other_files(
    account, monkeypatch, capsys
):
    root, raw = account
    secret = root / "secrets.json"
    secret.write_bytes(b"PRIVATE EXISTING FILE")
    monkeypatch.setattr(
        cli.getpass, "getpass", Mock(side_effect=AssertionError("No prompt"))
    )
    factory = Mock(side_effect=AssertionError("No HTTP client needed"))
    monkeypatch.setattr("messenger_ai.ai.ChatAI", factory)
    cli.configure_vision(None, None, chain=[])
    selected = [
        target
        for target in VISION_PRESET
        if target.partition(":")[0] in ("nvidia", "groq")
    ]
    assert json.loads((root / "config.json").read_text()) == canonical_config(
        dict(raw, vision_models=selected)
    )
    assert secret.read_bytes() == b"PRIVATE EXISTING FILE"
    assert (root / "config.json").stat().st_mode & 0o777 == 0o600
    assert (root / "persona.local.txt").read_text() == "PRIVATE PERSONA"
    assert (root / "data" / "messenger-device.db").read_bytes() == b"PRIVATE DEVICE"
    assert "PRIVATE" not in capsys.readouterr().out
    factory.assert_not_called()


def test_preset_omits_unconfigured_providers_and_reports_them(
    account, monkeypatch, capsys
):
    root, raw = account
    raw["google_models"] = ["gemini-3.5-flash-lite"]
    (root / "config.json").write_text(json.dumps(raw))
    monkeypatch.setattr(cli, "load_secrets", lambda _: {"google_api_key": "PRIVATE"})
    cli.configure_vision(None, None, chain=[])
    settings = Settings.load(root)
    assert settings.vision_models == VISION_PRESET[:2]
    output = capsys.readouterr().out
    assert (
        "Bỏ khỏi mẫu vì nguồn đang tắt hoặc chưa có key: nvidia, groq, cloudflare"
        in output
    )
    assert "PRIVATE" not in output


def test_manual_chain_preserves_exact_model_priority(account):
    root, _ = account
    chosen = [VISION_PRESET[3], VISION_PRESET[0], "nvidia:owner/custom-image-model"]
    cli.configure_vision(None, None, chain=chosen)
    assert Settings.load(root).vision_models == tuple(chosen)


@pytest.mark.parametrize(
    "failure", ["no_keys", "missing_key", "bad_cf", "ambiguous", "duplicate"]
)
def test_invalid_chain_does_not_write_any_files(account, monkeypatch, failure):
    root, _ = account
    options = {"chain": list(VISION_PRESET)}
    provider = None
    if failure == "no_keys":
        monkeypatch.setattr(cli, "load_secrets", lambda _: {})
        options["chain"] = []
    elif failure == "missing_key":
        monkeypatch.setattr(
            cli, "load_secrets", lambda _: {"google_api_key": "PRIVATE"}
        )
    elif failure == "bad_cf":
        monkeypatch.setattr(
            cli, "load_secrets", lambda _: {"cloudflare_api_token": "PRIVATE"}
        )
        options["chain"] = []
    elif failure == "ambiguous":
        provider = "nvidia"
    else:
        options["chain"] = [VISION_PRESET[0]] * 2
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        cli.configure_vision(provider, None, **options)
    assert {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("disable", [False, True])
def test_switching_back_to_single_source_or_disabling_removes_the_chain(
    account, disable
):
    root, raw = account
    cli.configure_vision(None, None, chain=[])
    cli.configure_vision(
        None if disable else "nvidia",
        None if disable else "google/gemma-4-31b-it",
        disable=disable,
    )
    assert json.loads((root / "config.json").read_text()) == canonical_config(
        dict(
            raw,
            vision_models=[] if disable else ["nvidia:google/gemma-4-31b-it"],
        )
    )


def test_chain_cli_dispatch_uses_empty_list_for_preset(account, monkeypatch):
    configure = Mock()
    monkeypatch.setattr(cli, "configure_vision", configure)
    monkeypatch.setattr("sys.argv", ["messenger_ai", "configure-vision", "--chain"])
    cli.main()
    configure.assert_called_once_with(None, None, disable=False, chain=[])


@pytest.mark.asyncio
@pytest.mark.parametrize("all_models", [False, True])
async def test_check_vision_all_tests_later_models_even_after_an_earlier_success(
    account, monkeypatch, capsys, all_models
):
    from messenger_ai.ai import ChatAI, VisionFallbackAI

    root, _ = account
    settings = Settings(vision_models=(VISION_PRESET[0], VISION_PRESET[3]))
    monkeypatch.setattr(Settings, "load", lambda: settings)
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if len(calls) == 1:
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
        return httpx.Response(503, text="PRIVATE RESPONSE")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        clients = [
            ChatAI(
                "PRIVATE_KEY",
                Settings(ai_provider=p, model=m, minimum_ai_interval_seconds=0),
                "PRIVATE PERSONA",
                client=client,
            )
            for p, m in settings.vision_targets
        ]
        pool = VisionFallbackAI(*clients)
        pool.close = AsyncMock(wraps=pool.close)
        monkeypatch.setattr("messenger_ai.ai.create_vision_ai", lambda *_: pool)
        if all_models:
            with pytest.raises(AIError, match="1/2"):
                await cli.check_vision(all_models=True)
        else:
            await cli.check_vision()
        pool.close.assert_awaited_once()
    assert len(calls) == (2 if all_models else 1)
    output = capsys.readouterr().out
    assert "Màu đỏ." in output and "PRIVATE" not in output
    assert not (root / "data" / "state.sqlite3").exists()
