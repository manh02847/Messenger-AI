import base64
import io
import json
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

from messenger_ai import cli
from messenger_ai.ai import AIError
from messenger_ai.config import Settings


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
    assert json.loads((root / "config.json").read_text()) == dict(
        raw,
        vision_provider="nvidia",
        vision_model="owner/manually-selected-vision-model",
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
    assert json.loads((root / "config.json").read_text()) == dict(
        raw, vision_provider="", vision_model=""
    )
    assert (root / "secrets.json").read_bytes() == secret_before


@pytest.mark.parametrize(
    "provider,model,disable",
    [
        (None, None, False),
        ("nvidia", "bad model", False),
        ("google", "unknown", False),
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
    configure.assert_called_once_with("nvidia", "google/gemma-4-31b-it", disable=False)
