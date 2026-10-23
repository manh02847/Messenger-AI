import json
from copy import deepcopy

import pytest

from messenger_ai.config import Settings
from messenger_ai.handoff import requests_human
from messenger_ai.preview import chat_loop, bounded_history


@pytest.mark.parametrize(
    "text",
    [
        "đang lag gì thế",
        "ngáo l",
        "Mạnh đang làm gì",
        "không cần Mạnh trả lời",
        "tại sao bạn nói cho mình gặp Mạnh",
    ],
)
def test_casual_messages_do_not_request_handoff(text):
    assert not requests_human(text)


@pytest.mark.parametrize(
    "text",
    [
        "Cho mình gặp Mạnh nhé!",
        "cho minh gap manh",
        "Mạnh tự rep đi",
        "Đừng trả lời nữa",
        "Mình không muốn nói chuyện với bot nữa",
    ],
)
def test_explicit_requests(text):
    assert requests_human(text)


@pytest.mark.asyncio
async def test_terminal_conversation_passes_both_roles_and_reset():
    calls, output = [], []

    class AI:
        async def generate(self, history, reserve):
            assert reserve()
            calls.append(deepcopy(history))
            return "Câu trả lời"

    inputs = iter(["chao", "y la sao", "/context", "/reset", "thu lai", "/quit"])
    await chat_loop(
        AI(), Settings(), lambda: True, read=lambda _: next(inputs), write=output.append
    )
    assert calls[1] == [
        {"role": "user", "content": "chao"},
        {"role": "assistant", "content": "Câu trả lời"},
        {"role": "user", "content": "y la sao"},
    ]
    assert calls[2] == [{"role": "user", "content": "thu lai"}]
    assert any("Ngữ cảnh: 4 tin" in line for line in output)


def test_preview_preserves_latest_message_within_limits():
    settings = Settings(history_messages=2, history_char_limit=10)
    result = bounded_history(
        [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "abcdefghi"},
            {"role": "user", "content": "latest"},
        ],
        settings,
    )
    assert result == [{"role": "user", "content": "latest"}]


def test_tune_preserves_secrets_recipients_and_larger_budget(tmp_path, monkeypatch):
    from messenger_ai import cli

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    config = {
        "allowed_threads": ["e2ee:222@msgr"],
        "max_completion_tokens": 4096,
        "output_char_limit": 6000,
        "history_messages": 20,
        "reply_prefix": "old",
    }
    (tmp_path / "config.json").write_text(json.dumps(config))
    (tmp_path / "secrets.json").write_text("private")
    cli.tune_chat()
    updated = json.loads((tmp_path / "config.json").read_text())
    assert updated == dict(config, reply_prefix="")
    assert (tmp_path / "secrets.json").read_text() == "private"
    config["max_completion_tokens"] = 768
    config["output_char_limit"] = 500
    (tmp_path / "config.json").write_text(json.dumps(config))
    cli.tune_chat()
    assert (
        json.loads((tmp_path / "config.json").read_text())["max_completion_tokens"]
        == 4096
    )

    assert (
        json.loads((tmp_path / "config.json").read_text())["output_char_limit"] == 4000
    )
