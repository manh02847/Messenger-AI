import asyncio
import json
from copy import deepcopy
from unittest.mock import Mock

import httpx
import pytest

from messenger_ai import cli
from messenger_ai.ai import ChatAI
from messenger_ai.config import Settings
from messenger_ai.context import recent_history
from messenger_ai.core import Message, ReplyBot
from messenger_ai.preview import chat_loop
from messenger_ai.state import State

THREAD = "e2ee:222@msgr"


def test_context_keeps_whole_pairs_and_drops_unexplained_answer():
    history = [
        {"role": "user", "content": "Older question"},
        {"role": "assistant", "content": "Older answer"},
        {"role": "user", "content": "New question"},
        {"role": "assistant", "content": "New answer"},
        {"role": "user", "content": "More?"},
    ]
    original = deepcopy(history)
    expected = history[2:]
    assert recent_history(history, 3, 1000) == expected
    assert recent_history(history, 4, 1000) == expected
    assert recent_history(history, 12, 30) == expected
    assert history == original


def test_large_old_answer_does_not_leave_partial_words_in_context():
    history = [
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": "Unsupported claim " * 30},
        {"role": "user", "content": "Really?"},
    ]
    assert recent_history(history, 12, 50) == history[-1:]
    assert recent_history([{"role": "user", "content": "abcdef"}], 12, 3) == [
        {"role": "user", "content": "abc"}
    ]


@pytest.mark.parametrize("gap,expected_count", [(3599, 3), (3600, 1), (7200, 1)])
def test_idle_context_boundary_survives_restart_and_keeps_stored_history(
    tmp_path, gap, expected_count
):
    path = tmp_path / "state.sqlite3"
    state = State(path)
    state.remember(THREAD, "user", "Old question", 1000, 12)
    state.remember(THREAD, "assistant", "Old answer", 1001, 12)
    state.close()
    state = State(path)
    state.remember(THREAD, "user", "New question", 1001 + gap, 12)
    state.remember("thread:999", "user", "OTHER CHAT", 1002 + gap, 12)
    assert len(state.history(THREAD, 12, 3500, idle_seconds=3600)) == expected_count
    assert len(state.history(THREAD, 12, 3500, idle_seconds=0)) == 3
    assert state.history("thread:999", 12, 3500, idle_seconds=3600) == [
        {"role": "user", "content": "OTHER CHAT"}
    ]
    state.close()


@pytest.mark.asyncio
async def test_live_reply_uses_new_session_after_idle(tmp_path):
    state = State(tmp_path / "state.sqlite3")
    state.remember(THREAD, "user", "Old question", 100, 12)
    state.remember(THREAD, "assistant", "Old answer", 101, 12)
    calls = []

    class AI:
        async def generate(self, history, reserve):
            assert reserve()
            calls.append(history)
            return "New answer"

    settings = Settings(
        allowed_threads=(THREAD,),
        dry_run=True,
        debounce_seconds=0,
        reply_cooldown_seconds=0,
        history_idle_seconds=100,
    )
    bot = ReplyBot(
        settings, state, AI(), Mock(), "111", clock=lambda: 1000, log=lambda _: None
    )
    bot.receive(Message(THREAD, "new", "222", "New question", 1000, is_private=True))
    await asyncio.gather(*bot.tasks.values())
    assert calls == [[{"role": "user", "content": "New question"}]]
    await bot.close()
    state.close()


@pytest.mark.parametrize("value", [-1, True, None, "3600", float("inf"), float("nan")])
def test_invalid_idle_setting_rejected(value):
    with pytest.raises(ValueError, match="history_idle_seconds"):
        Settings.from_dict({"history_idle_seconds": value})


def test_old_config_defaults_to_one_hour_and_can_disable_idle_boundary():
    assert Settings.from_dict({}).history_idle_seconds == 3600
    assert Settings.from_dict({"history_idle_seconds": 0}).history_idle_seconds == 0


def test_active_conversation_keeps_context_even_if_session_is_older_than_one_hour(
    tmp_path,
):
    state = State(tmp_path / "state.sqlite3")
    for i, role in enumerate(("user", "assistant", "user", "assistant", "user")):
        state.remember(THREAD, role, f"Message {i}", i * 1800, 12)
    history = state.history(THREAD, 12, 3500, idle_seconds=3600)
    assert [message["content"] for message in history] == [
        f"Message {i}" for i in range(5)
    ]
    state.close()


@pytest.mark.asyncio
async def test_terminal_context_expires_without_changing_persona_or_extra_ai_calls():
    calls, output = [], []

    class AI:
        async def generate(self, history, reserve):
            assert reserve()
            calls.append(deepcopy(history))
            return "Answer"

    times = iter([0, 1, 11, 12])
    inputs = iter(["Old", "New", "/quit"])
    await chat_loop(
        AI(),
        Settings(history_idle_seconds=10),
        lambda: True,
        read=lambda _: next(inputs),
        write=output.append,
        clock=lambda: next(times),
    )
    assert calls == [
        [{"role": "user", "content": "Old"}],
        [{"role": "user", "content": "New"}],
    ]
    assert any("sau thời gian không nhắn" in line for line in output)


@pytest.mark.parametrize("preview", [False, True])
def test_reset_one_context_preserves_delivery_safety_quotas_and_other_account(
    tmp_path, monkeypatch, capsys, preview
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    data = tmp_path / "data"
    states = {name: State(data / name) for name in ("state.sqlite3", "preview.sqlite3")}
    target_name = "preview.sqlite3" if preview else "state.sqlite3"
    for state in states.values():
        state.remember(THREAD, "user", "PRIVATE HISTORY", 1000, 12)
        state.remember("thread:999", "user", "OTHER CHAT", 1000, 12)
        assert state.claim(THREAD, "incoming", 1000)
        state.pause(THREAD, 2000)
        outbox = state.begin_send(THREAD, "Sent reply", 1000)
        state.finish_send(outbox, "sent", "outgoing")
        assert state.reserve_ai("2026-10-23", 1)
    untouched = {
        "config.json": '{"allowed_threads": []}',
        "secrets.json": "PRIVATE COOKIE AND KEY",
        "persona.local.txt": "PRIVATE PERSONA",
        "data/messenger-device.db": "PRIVATE DEVICE",
    }
    for name, content in untouched.items():
        (tmp_path / name).write_text(content)
    other_account = tmp_path / "bot-2" / "data" / "state.sqlite3"
    other_account.parent.mkdir(parents=True)
    other_account.write_bytes(b"OTHER ACCOUNT")
    cli.reset_context(THREAD, preview=preview)
    for name, state in states.items():
        assert bool(state.history(THREAD, 12, 3500)) is (name != target_name)
        assert state.history("thread:999", 12, 3500)[0]["content"] == "OTHER CHAT"
        assert not state.claim(THREAD, "incoming", 1001)
        assert state.paused(THREAD, 1001)
        assert state.bot_echo(THREAD, "outgoing", "Sent reply", 1001)
        assert state.last_send(THREAD) == 1000
        assert state.sends_since(THREAD, 0) == 1
        assert not state.reserve_ai("2026-10-23", 1)
        state.close()
    for name, content in untouched.items():
        assert (tmp_path / name).read_text() == content
    assert other_account.read_bytes() == b"OTHER ACCOUNT"
    assert "PRIVATE" not in capsys.readouterr().out


def test_reset_rejects_invalid_thread_and_missing_database_without_creating_data(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    for thread in ("222", "../../secrets.json", "thread:0"):
        with pytest.raises(ValueError, match="discover"):
            cli.reset_context(thread)
    with pytest.raises(ValueError, match="Chưa có dữ liệu"):
        cli.reset_context(THREAD)
    assert not (tmp_path / "data").exists()


def test_reset_refuses_while_bot_holds_instance_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    state = State(tmp_path / "data" / "state.sqlite3")
    state.remember(THREAD, "user", "Keep context", 1000, 12)
    with cli.instance_lock(tmp_path / "data"):
        with pytest.raises(RuntimeError, match="Dừng phiên"):
            cli.reset_context(THREAD)
    assert state.history(THREAD, 12, 3500)[0]["content"] == "Keep context"
    state.close()


def test_reset_cli_dispatches_thread_and_preview_flag(monkeypatch):
    reset = Mock()
    monkeypatch.setattr(cli, "reset_context", reset)
    monkeypatch.setattr(
        "sys.argv", ["messenger_ai", "reset-context", THREAD, "--preview"]
    )
    cli.main()
    reset.assert_called_once_with(THREAD, preview=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,model",
    [
        ("groq", "openai/gpt-oss-120b"),
        ("cloudflare", "@cf/qwen/qwen3-30b-a3b-fp8"),
        ("nvidia", "google/gemma-4-31b-it"),
        ("google", "gemini-3.5-flash-lite"),
    ],
)
async def test_all_providers_receive_private_persona_and_context_rules_once(
    provider, model
):
    history = [
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": "An earlier claim"},
        {"role": "user", "content": "Clarification"},
    ]
    original = deepcopy(history)
    requests, reservations = [], []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if provider == "google":
            prompt = payload["systemInstruction"]["parts"][0]["text"]
            assert [m["parts"][0]["text"] for m in payload["contents"]] == [
                m["content"] for m in history
            ]
            body = {
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": "OK"}]}}
                ]
            }
        else:
            prompt = payload["messages"][0]["content"]
            assert payload["messages"][1:] == history
            body = {
                "choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]
            }
        assert prompt.startswith("PRIVATE OWNER PROFILE\n\n")
        assert prompt.count("PRIVATE OWNER PROFILE") == 1
        assert prompt.count("DÙNG NGỮ CẢNH") == 1
        assert "Lịch sử, nhất là câu trả lời trước của bot, có thể sai" in prompt
        assert "Không suy ra giới tính" in prompt
        return httpx.Response(200, json=body)

    def reserve():
        reservations.append(True)
        return True

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "test-key",
            Settings(ai_provider=provider, model=model, minimum_ai_interval_seconds=0),
            "PRIVATE OWNER PROFILE",
            account_id="a" * 32,
            client=client,
        )
        assert await ai.generate(history, reserve) == "OK"
    assert len(requests) == len(reservations) == 1
    assert history == original
