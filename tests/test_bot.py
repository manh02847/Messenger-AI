import asyncio
from dataclasses import replace

import pytest

from messenger_ai.config import Settings
from messenger_ai.core import Message, ReplyBot, parse_event
from messenger_ai.state import State

THREAD = "e2ee:222@msgr"
NOW = 1800000000.0


class FakeAI:
    def __init__(self, answer="Mình nhận được rồi bạn nhé."):
        self.answer = answer
        self.calls = []

    async def generate(self, history, reserve):
        assert reserve()
        self.calls.append(history)
        return self.answer


class Sender:
    def __init__(self, result=None, error=False):
        self.calls = []
        self.result = result or {"messageId": "bot-1"}
        self.error = error

    async def send(self, message, text):
        self.calls.append((message, text))
        if self.error:
            raise TimeoutError("server error with secret data")
        return self.result


def message(mid="m1", text="Chào bạn", sender="222", thread=THREAD, timestamp=NOW):
    return Message(thread, mid, sender, text, timestamp, "222@msgr", "222:1@msgr")


def make_bot(tmp_path, **options):
    settings = Settings(
        allowed_threads=(THREAD,),
        dry_run=False,
        debounce_seconds=0,
        reply_cooldown_seconds=0,
        minimum_ai_interval_seconds=0,
    )
    ai = options.pop("ai", FakeAI())
    sender = options.pop("sender", Sender())
    logs = []
    state = State(tmp_path / "state.sqlite3")
    bot = ReplyBot(
        replace(settings, **options),
        state,
        ai,
        sender,
        "111",
        clock=lambda: NOW,
        log=logs.append,
    )
    return bot, state, ai, sender, logs


async def drain(bot):
    await asyncio.gather(*list(bot.tasks.values()))


def test_parse_real_bridge_schema():
    msg = parse_event(
        {
            "type": "e2eeMessage",
            "data": {
                "id": "a",
                "senderId": 222,
                "chatJid": "222@msgr",
                "senderJid": "222:7@msgr",
                "timestampMs": NOW * 1000,
                "text": "A",
            },
        }
    )
    assert msg.thread == THREAD
    assert msg.sender_jid == "222:7@msgr"
    assert msg.timestamp == NOW
    regular = parse_event(
        {
            "type": "message",
            "data": {
                "id": "b",
                "senderId": 222,
                "threadId": 999,
                "timestampMs": NOW * 1000,
                "text": "B",
            },
        }
    )
    assert regular.thread == "thread:999"
    assert regular.thread_id == 999


@pytest.mark.parametrize(
    "event",
    [
        None,
        {},
        {"type": "typing", "data": {}},
        {"type": "e2eeMessage", "data": {"text": "hi"}},
    ],
)
def test_invalid_events_ignored(event):
    assert parse_event(event) is None


@pytest.mark.asyncio
async def test_deny_unlisted_conversation_even_with_same_sender(tmp_path):
    bot, state, ai, sender, _ = make_bot(tmp_path)
    bot.receive(message(thread="thread:999"))
    assert ai.calls == [] and sender.calls == []
    assert not bot.tasks
    state.close()


@pytest.mark.asyncio
async def test_reply_and_deduplicate_after_restart(tmp_path):
    bot, state, ai, sender, _ = make_bot(tmp_path)
    bot.receive(message())
    bot.receive(message())
    await drain(bot)
    assert len(sender.calls) == len(ai.calls) == 1
    assert sender.calls[0][0].id == "m1"
    state.close()
    second, state2, ai2, sender2, _ = make_bot(tmp_path)
    second.receive(message())
    assert not second.tasks and not sender2.calls and not ai2.calls
    state2.close()


@pytest.mark.asyncio
async def test_recent_boot_ignores_old_backfill(tmp_path):
    bot, state, ai, sender, _ = make_bot(tmp_path)
    bot.receive(message(timestamp=NOW - 10))
    assert not bot.tasks and not ai.calls and not sender.calls
    state.close()


@pytest.mark.asyncio
async def test_incoming_burst_is_one_reply_with_both_messages(tmp_path):
    bot, state, ai, sender, _ = make_bot(tmp_path)
    bot.receive(message("m1", "Tin một"))
    bot.receive(message("m2", "Tin hai"))
    await drain(bot)
    assert len(sender.calls) == 1
    assert [x["content"] for x in ai.calls[0]] == ["Tin một", "Tin hai"]
    state.close()


@pytest.mark.asyncio
async def test_manual_reply_cancels_draft_and_persists_pause(tmp_path):
    bot, state, ai, sender, _ = make_bot(tmp_path)
    bot.receive(message())
    bot.receive(message("own", "Để mình tự trả lời nhé", sender="111"))
    await drain(bot)
    assert not sender.calls
    assert state.paused(THREAD, NOW)
    state.close()
    second, state2, _, sender2, _ = make_bot(tmp_path)
    second.receive(message("m3"))
    assert not second.tasks and not sender2.calls
    state2.close()


@pytest.mark.asyncio
async def test_manual_reply_while_ai_is_running_prevents_send(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingAI:
        async def generate(self, history, reserve):
            assert reserve()
            entered.set()
            await release.wait()
            return "Bản nháp cũ"

    bot, state, _, sender, _ = make_bot(tmp_path, ai=WaitingAI())
    bot.receive(message())
    await entered.wait()
    bot.receive(message("manual", "Mình tự nhắn rồi", sender="111"))
    release.set()
    await drain(bot)
    assert sender.calls == []
    state.close()


@pytest.mark.asyncio
async def test_new_message_during_generation_replaces_old_draft(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingAI:
        calls = 0

        async def generate(self, history, reserve):
            assert reserve()
            self.calls += 1
            if self.calls == 1:
                entered.set()
                await release.wait()
                return "Nháp cũ"
            return "Nháp mới"

    bot, state, ai, sender, _ = make_bot(tmp_path, ai=WaitingAI())
    bot.receive(message())
    await entered.wait()
    bot.receive(message("new", "Đính chính nhé"))
    release.set()
    await drain(bot)
    assert len(sender.calls) == 1 and sender.calls[0][1].endswith("Nháp mới")
    assert ai.calls == 2
    state.close()


@pytest.mark.asyncio
async def test_bot_echo_does_not_pause(tmp_path):
    bot, state, _, sender, _ = make_bot(tmp_path)
    bot.receive(message())
    await drain(bot)
    bot.receive(message("bot-1", sender.calls[0][1], sender="111"))
    assert not state.paused(THREAD, NOW)
    bot.receive(message("m2"))
    await drain(bot)
    assert len(sender.calls) == 2
    state.close()


@pytest.mark.asyncio
async def test_echo_racing_send_response_is_recognized(tmp_path):
    sender = Sender()
    bot, state, _, _, _ = make_bot(tmp_path, sender=sender)

    async def send(original, text):
        sender.calls.append((original, text))
        bot.receive(message("early-echo", text, sender="111"))
        return {"messageId": "early-echo"}

    sender.send = send
    bot.receive(message())
    await drain(bot)
    assert not state.paused(THREAD, NOW)
    state.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sender",
    [
        Sender(result={"messageId": "uncertain", "deliveryStatus": "unknown"}),
        Sender(error=True),
    ],
)
async def test_ambiguous_delivery_never_retried(tmp_path, sender):
    sender.calls.clear()
    bot, state, _, _, logs = make_bot(tmp_path, sender=sender)
    bot.receive(message())
    await drain(bot)
    bot.receive(message())
    bot.receive(message("next"))
    assert len(sender.calls) == 1
    assert state.paused(THREAD, NOW)
    assert "secret" not in " ".join(logs)
    assert state.history(THREAD, 12, 3000)[-1]["role"] == "user"
    state.close()


@pytest.mark.asyncio
async def test_preview_sends_nothing_and_does_not_invent_history(tmp_path):
    bot, state, ai, sender, logs = make_bot(tmp_path, dry_run=True)
    bot.receive(message())
    await drain(bot)
    assert len(ai.calls) == 1 and not sender.calls
    assert "CHƯA GỬI" in logs[0]
    assert [x["role"] for x in state.history(THREAD, 12, 3000)] == ["user"]
    state.close()


@pytest.mark.asyncio
async def test_handoff_pauses_without_sending(tmp_path):
    bot, state, _, sender, _ = make_bot(tmp_path, ai=FakeAI("[[HANDOFF]]"))
    bot.receive(message())
    await drain(bot)
    assert not sender.calls and state.paused(THREAD, NOW)
    state.close()


@pytest.mark.asyncio
async def test_daily_send_limit_counts_ambiguous_attempts(tmp_path):
    bot, state, _, sender, logs = make_bot(tmp_path, max_replies_per_thread_per_day=1)
    state.begin_send(THREAD, "Previous uncertain send", NOW - 60)
    bot.receive(message())
    await drain(bot)
    assert not sender.calls
    assert "giới hạn" in logs[0]
    state.close()


def test_history_stays_separate_and_bounded(tmp_path):
    state = State(tmp_path / "state.sqlite3")
    for i in range(20):
        state.remember(THREAD, "user", f"Thread one {i}", NOW, keep=4)
    state.remember("thread:999", "user", "PRIVATE OTHER CHAT", NOW, keep=4)
    history = state.history(THREAD, 12, 20)
    assert sum(len(x["content"]) for x in history) <= 20
    assert "PRIVATE" not in str(history)
    assert state.reserve_ai("2026-10-22", 1)
    assert not state.reserve_ai("2026-10-22", 1)
    assert state.reserve_ai("2026-10-23", 1)
    state.close()
