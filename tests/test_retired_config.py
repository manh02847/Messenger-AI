import json
from dataclasses import asdict

import pytest

from messenger_ai.config import Settings


@pytest.mark.parametrize("enabled", [True, False])
def test_retired_flag_cannot_reenable_provider_or_break_existing_config(enabled):
    raw = {
        "chatgpt_web": enabled,
        "reply_scope": "all_private",
        "model": "qwen/qwen3.8-27b",
    }
    settings = Settings.from_dict(raw)
    assert settings.reply_scope == "all_private"
    assert settings.model == raw["model"]
    assert "chatgpt_web" not in asdict(settings)
    assert raw["chatgpt_web"] is enabled


def test_loading_old_config_removes_only_retired_flag_preserving_credentials_and_history(
    tmp_path,
):
    raw = {
        "chatgpt_web": True,
        "reply_scope": "all_private",
        "ai_fallback": True,
        "google_models": ["gemma-4-31b-it", "gemini-3.5-flash-lite"],
        "model": "qwen/qwen3.8-27b",
        "history_char_limit": 3500,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    secrets = tmp_path / "secrets.json"
    secrets.write_bytes(b"private credentials")
    history = tmp_path / "state.sqlite3"
    history.write_bytes(b"history unchanged")
    settings = Settings.load(tmp_path)
    assert json.loads(path.read_text()) == {
        k: v for k, v in raw.items() if k != "chatgpt_web"
    }
    assert settings.google_models == tuple(raw["google_models"])
    assert settings.ai_fallback is True
    assert secrets.read_bytes() == b"private credentials"
    assert history.read_bytes() == b"history unchanged"
    assert path.stat().st_mode & 0o777 == 0o600


def test_unknown_fields_still_rejected_without_rewriting_invalid_config(tmp_path):
    raw = {"chatgpt_web": True, "unknown_setting": "bad"}
    path = tmp_path / "config.json"
    before = json.dumps(raw)
    path.write_text(before)
    with pytest.raises(ValueError, match="không được hỗ trợ"):
        Settings.load(tmp_path)
    assert path.read_text() == before
