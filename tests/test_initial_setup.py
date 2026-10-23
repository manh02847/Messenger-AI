import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from messenger_ai import cli
from messenger_ai.config import Settings

NEW_COOKIE = "c_user=222; xs=new-session;"
OLD_COOKIE = "c_user=111; xs=old-session;"


@pytest.fixture
def destination(tmp_path, monkeypatch):
    root = tmp_path / "bot-2"
    root.mkdir()
    example = Path(__file__).resolve().parents[1] / "config.example.json"
    (root / "config.example.json").write_bytes(example.read_bytes())
    monkeypatch.setattr(cli, "ROOT", root)
    for name in (
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "NVIDIA_API_KEY",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN",
        "FACEBOOK_COOKIE",
    ):
        monkeypatch.delenv(name, raising=False)
    return root


def saved(root, filename):
    return json.loads((root / filename).read_text())


def source_bot(tmp_path):
    source = tmp_path / "bot-1"
    source.mkdir()
    raw = {
        "ai_provider": "cloudflare",
        "model": "@cf/qwen/qwen3.8-27b",
        "ai_fallback": True,
        "fallback_model": "qwen/qwen3.8-27b",
        "nvidia_model": "google/gemma-4-31b-it",
        "google_models": ["gemini-3.5-flash-lite", "gemma-4-31b-it"],
        "max_ai_calls_per_day": 1000,
        "history_char_limit": 4000,
        "history_idle_seconds": 1800,
        "max_completion_tokens": 3000,
        "allowed_threads": ["e2ee:999@msgr"],
        "reply_scope": "all_private",
        "reply_prefix": "Owner prefix",
        "manual_pause_seconds": 900,
        "dry_run": False,
        "chatgpt_web": True,
    }
    secret = {
        "groq_api_key": "source-groq-secret",
        "cloudflare_account_id": "a" * 32,
        "cloudflare_api_token": "source-cloudflare-secret",
        "google_api_key": "source-google-secret",
        "nvidia_api_key": "source-nvidia-secret",
        "facebook_cookie": OLD_COOKIE,
        "private_note": "must-not-copy",
    }
    (source / "config.json").write_text(json.dumps(raw))
    (source / "secrets.json").write_text(json.dumps(secret))
    (source / "persona.local.txt").write_text("Private identity, must not copy")
    (source / "data").mkdir()
    (source / "data" / "messenger-device.db").write_bytes(b"private device")
    (source / "data" / "state.sqlite3").write_bytes(b"private history")
    return source, raw, secret


def snapshot(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_first_groq_setup_creates_config_and_allows_followup_commands(
    destination, monkeypatch, capsys
):
    answers = iter(["private-groq-key", NEW_COOKIE])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: next(answers))
    cli.configure()
    assert Settings.load(destination).ai_provider == "groq"
    assert saved(destination, "secrets.json")["facebook_cookie"] == NEW_COOKIE
    cli.set_reply_scope("all_private")
    assert Settings.load(destination).reply_scope == "all_private"
    for name in ("config.json", "secrets.json"):
        assert (destination / name).stat().st_mode & 0o777 == 0o600
    assert "private-groq-key" not in capsys.readouterr().out


def test_first_cloudflare_setup_works_without_groq_key(destination, monkeypatch):
    answers = iter(["private-cloudflare-key", NEW_COOKIE])
    monkeypatch.setattr("builtins.input", lambda _: "b" * 32)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: next(answers))
    cli.configure(provider="cloudflare")
    settings = Settings.load(destination)
    assert settings.ai_provider == "cloudflare"
    assert settings.model == "@cf/qwen/qwen3-30b-a3b-fp8"
    assert saved(destination, "secrets.json")["groq_api_key"] == ""


def test_cookie_update_keeps_existing_cloudflare_model_scope_and_budget(
    destination, monkeypatch
):
    raw = {
        "ai_provider": "cloudflare",
        "model": "@cf/qwen/qwen3.8-27b",
        "reply_scope": "all_private",
        "max_ai_calls_per_day": 1234,
    }
    secret = {
        "cloudflare_account_id": "b" * 32,
        "cloudflare_api_token": "keep-cloudflare-key",
        "facebook_cookie": OLD_COOKIE,
    }
    (destination / "config.json").write_text(json.dumps(raw))
    (destination / "secrets.json").write_text(json.dumps(secret))
    answers = iter(["", NEW_COOKIE])
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: next(answers))
    cli.configure()
    assert saved(destination, "config.json") == raw
    assert saved(destination, "secrets.json")["facebook_cookie"] == NEW_COOKIE


@pytest.mark.parametrize(
    "failure", ["groq_key", "cloudflare_key", "account_id", "cookie"]
)
def test_invalid_first_setup_writes_no_partial_files(destination, monkeypatch, failure):
    provider = "cloudflare" if failure in ("cloudflare_key", "account_id") else "groq"
    key = "" if failure.endswith("key") else "private-key"
    cookie = "c_user=222; xs=;" if failure == "cookie" else NEW_COOKIE
    answers = iter([key, cookie])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: next(answers))
    monkeypatch.setattr(
        "builtins.input", lambda _: "bad/id" if failure == "account_id" else "a" * 32
    )
    before = snapshot(destination)
    with pytest.raises(ValueError):
        cli.configure(provider=provider)
    assert snapshot(destination) == before


def test_copy_ai_creates_separate_account_without_copying_identity_or_device(
    destination, tmp_path, monkeypatch, capsys
):
    source, raw, secret = source_bot(tmp_path)
    before = snapshot(source)
    prompts = []

    def cookie_prompt(prompt):
        prompts.append(prompt)
        return NEW_COOKIE

    monkeypatch.setattr(cli.getpass, "getpass", cookie_prompt)
    cli.configure(copy_ai_from=source)
    assert len(prompts) == 1 and "Cookie Facebook" in prompts[0]
    result = saved(destination, "config.json")
    for name in (
        "ai_provider",
        "model",
        "fallback_model",
        "google_models",
        "nvidia_model",
        "max_ai_calls_per_day",
        "history_char_limit",
        "history_idle_seconds",
    ):
        assert result[name] == raw[name]
    assert result["allowed_threads"] == [] and result["reply_scope"] == "allowlist"
    assert result["dry_run"] is True and result["reply_prefix"] == ""
    assert "chatgpt_web" not in result
    copied = saved(destination, "secrets.json")
    assert copied["facebook_cookie"] == NEW_COOKIE
    for name in cli.AI_SECRETS:
        assert copied[name] == secret[name]
    assert "private_note" not in copied
    assert not (destination / "data").exists()
    assert not (destination / "persona.local.txt").exists()
    assert snapshot(source) == before
    output = capsys.readouterr().out
    assert all(secret[name] not in output for name in cli.AI_SECRETS)
    assert NEW_COOKIE not in output and OLD_COOKIE not in output


def test_copy_ai_preserves_existing_destination_scope_history_and_persona(
    destination, tmp_path, monkeypatch
):
    source, _, _ = source_bot(tmp_path)
    raw = {
        "allowed_threads": ["e2ee:333@msgr"],
        "manual_pause_seconds": 60,
        "dry_run": False,
        "reply_prefix": "Keep destination prefix",
    }
    (destination / "config.json").write_text(json.dumps(raw))
    (destination / "data").mkdir()
    history = destination / "data" / "state.sqlite3"
    history.write_bytes(b"destination history")
    persona = destination / "persona.local.txt"
    persona.write_bytes(b"destination persona")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: NEW_COOKIE)
    cli.configure(copy_ai_from=source)
    result = saved(destination, "config.json")
    assert all(result[name] == value for name, value in raw.items())
    assert history.read_bytes() == b"destination history"
    assert persona.read_bytes() == b"destination persona"


def test_copy_ai_requires_entering_cookie_even_when_destination_has_one(
    destination, tmp_path, monkeypatch
):
    source, _, _ = source_bot(tmp_path)
    (destination / "secrets.json").write_text(
        json.dumps({"facebook_cookie": OLD_COOKIE})
    )
    before = snapshot(destination)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "")
    with pytest.raises(ValueError, match="Cookie"):
        cli.configure(copy_ai_from=source)
    assert snapshot(destination) == before


@pytest.mark.parametrize(
    "failure", ["same_folder", "missing_config", "invalid_config", "missing_key"]
)
def test_bad_copy_source_does_not_modify_destination(
    destination, tmp_path, monkeypatch, failure
):
    source, _, _ = source_bot(tmp_path)
    if failure == "same_folder":
        source = destination
    elif failure == "missing_config":
        (source / "config.json").unlink()
    elif failure == "invalid_config":
        (source / "config.json").write_text('{"reply_scope": "wrong"}')
    else:
        (source / "secrets.json").write_text("{}")
    before = snapshot(destination)
    source_before = snapshot(source)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: NEW_COOKIE)
    with pytest.raises(ValueError):
        cli.configure(copy_ai_from=source)
    assert snapshot(destination) == before
    assert snapshot(source) == source_before


def test_cookie_environment_cannot_silently_select_the_other_account(
    destination, tmp_path, monkeypatch
):
    source, _, _ = source_bot(tmp_path)
    monkeypatch.setenv("FACEBOOK_COOKIE", OLD_COOKIE)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: NEW_COOKIE)
    before = snapshot(destination)
    with pytest.raises(ValueError, match="FACEBOOK_COOKIE") as error:
        cli.configure(copy_ai_from=source)
    assert OLD_COOKIE not in str(error.value) and NEW_COOKIE not in str(error.value)
    assert snapshot(destination) == before


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (
            ["--provider", "cloudflare"],
            {"provider": "cloudflare", "copy_ai_from": None},
        ),
        (
            ["--copy-ai-from", "../bot-1"],
            {"provider": None, "copy_ai_from": Path("../bot-1")},
        ),
    ],
)
def test_configure_cli_accepts_initial_provider_or_copy_source(
    monkeypatch, arguments, expected
):
    configure = Mock()
    monkeypatch.setattr(cli, "configure", configure)
    monkeypatch.setattr("sys.argv", ["messenger_ai", "configure", *arguments])
    cli.main()
    configure.assert_called_once_with(**expected)
