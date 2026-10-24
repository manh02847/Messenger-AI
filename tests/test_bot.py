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
        self.typing_calls = []
        self.result = result or {"messageId": "bot-1"}
        self.error = error

    async def send(self, message, text):
        self.calls.append((message, text))
        if self.error:
            raise TimeoutError("server error with secret data")
        return self.result

    async def set_typing(self, message, is_typing):
        self.typing_calls.append((message.thread, is_typing))


def message(mid="m1", text="Chào bạn", sender="222", thread=THREAD, timestamp=NOW):
    return Message(thread, mid, sender, text, timestamp, "222@msgr", "222:1@msgr")


def make_bot(tmp_path, **options):
    settings = Settings(
        allowed_threads=(THREAD,),
        dry_run=False,
        debounce_seconds=0,
        reply_cooldown_seconds=0,
        minimum_ai_interval_seconds=0,
        ai_retry_enabled=False,
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
    assert sender.typing_calls == []
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
    assert sender.typing_calls == []
    assert "CHƯA GỬI" in logs[0]
    assert [x["role"] for x in state.history(THREAD, 12, 3000)] == ["user"]
    state.close()


@pytest.mark.asyncio
async def test_handoff_pauses_without_sending(tmp_path):
    bot, state, _, sender, _ = make_bot(tmp_path, ai=FakeAI("[[HANDOFF]]"))
    bot.receive(message(text="Cho mình nói chuyện với Mạnh nhé"))
    await drain(bot)
    assert not sender.calls and state.paused(THREAD, NOW)
    state.close()


@pytest.mark.asyncio
async def test_model_cannot_pause_for_confusion_and_next_turn_runs(tmp_path):
    bot, state, ai, sender, _ = make_bot(tmp_path, ai=FakeAI("[[HANDOFF]]"))
    bot.receive(message(text="đang lag gì thế"))
    await drain(bot)
    assert not state.paused(THREAD, NOW)
    assert len(sender.calls) == 1
    assert "[[HANDOFF]]" not in sender.calls[0][1]
    ai.answer = "Nãy mình hiểu nhầm ý bạn."
    bot.receive(message(mid="next", text="ý là rep sai đấy"))
    await drain(bot)
    assert len(sender.calls) == 2 and len(ai.calls) == 2
    assert ai.calls[1][-2]["role"] == "assistant"
    state.close()


@pytest.mark.asyncio
async def test_explicit_stop_cancels_pending_draft_without_ai(tmp_path):
    bot, state, ai, sender, _ = make_bot(tmp_path)
    bot.receive(message())
    bot.receive(message(mid="stop", text="Đừng trả lời nữa"))
    await drain(bot)
    assert not sender.calls and not ai.calls
    assert state.paused(THREAD, NOW)
    state.close()


@pytest.mark.asyncio
async def test_daily_send_limit_counts_ambiguous_attempts(tmp_path):
    bot, state, _, sender, logs = make_bot(tmp_path, max_replies_per_thread_per_day=1)
    state.begin_send(THREAD, "Previous uncertain send", NOW - 60)
    bot.receive(message())
    await drain(bot)
    assert not sender.calls
    assert not sender.typing_calls
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


def scope_event(*, jid=None, thread_type=None, sender=222, mid="scope-1", tid=999):
    data = {
        "id": mid,
        "senderId": sender,
        "timestampMs": NOW * 1000,
        "text": "Chào bạn",
        "threadId": tid,
    }
    if jid is not None:
        data.update(chatJid=jid, senderJid=f"{sender}:1@msgr")
    if thread_type is not None:
        data["threadType"] = thread_type
    return {"type": "e2eeMessage" if jid is not None else "message", "data": data}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event,private",
    [
        (scope_event(jid="222@msgr"), True),
        (scope_event(jid="222:7@msgr"), True),
        (scope_event(jid="222.1:7@msgr"), True),
        (scope_event(jid="222@g.us"), False),
        (scope_event(jid="222-333@g.us"), False),
        (scope_event(jid="222@broadcast"), False),
        (scope_event(jid="222@unknown"), False),
        (scope_event(jid="222@msgr.evil"), False),
        (scope_event(jid="222-333@msgr"), False),
        *[(scope_event(thread_type=t), True) for t in (1, 7, 10, 13, 15)],
        *[
            (scope_event(thread_type=t), False)
            for t in (None, 0, 2, 8, 16, 18, 201, 999, True, "1")
        ],
    ],
)
async def test_all_private_filters_before_ai_and_history(tmp_path, event, private):
    msg = parse_event(event)
    assert msg is not None and msg.is_private is private
    # Even an explicitly listed group must be rejected in all_private mode.
    bot, state, ai, sender, _ = make_bot(
        tmp_path, reply_scope="all_private", allowed_threads=(msg.thread,)
    )
    bot.receive(msg)
    await drain(bot)
    assert bool(ai.calls) is private
    assert bool(sender.calls) is private
    assert bool(state.history(msg.thread, 12, 3500)) is private
    state.close()


@pytest.mark.asyncio
async def test_all_private_empty_allowlist_and_separate_context(tmp_path):
    bot, state, ai, sender, _ = make_bot(
        tmp_path, reply_scope="all_private", allowed_threads=()
    )
    for jid, mid in (("222@msgr", "one"), ("333@msgr", "two")):
        event = scope_event(jid=jid, mid=mid)
        event["data"]["text"] = mid
        bot.receive(parse_event(event))
        await drain(bot)
    assert len(sender.calls) == 2
    assert [h[0]["content"] for h in ai.calls] == ["one", "two"]
    assert all(len(h) == 1 for h in ai.calls)
    state.close()


@pytest.mark.asyncio
async def test_all_private_manual_reply_cancels_draft(tmp_path):
    bot, state, ai, sender, _ = make_bot(
        tmp_path, reply_scope="all_private", allowed_threads=()
    )
    bot.receive(parse_event(scope_event(jid="222@msgr")))
    bot.receive(parse_event(scope_event(jid="222@msgr", sender=111, mid="manual")))
    await drain(bot)
    assert not sender.calls and not ai.calls
    assert state.paused(THREAD, NOW)
    state.close()


def test_reply_scope_validation_and_backwards_compatibility():
    assert Settings.from_dict({}).reply_scope == "allowlist"
    assert Settings.from_dict({"reply_scope": "all_private"}).allowed_threads == ()
    for bad in ("all", "", True, None, [], {}):
        with pytest.raises(ValueError, match="reply_scope"):
            Settings.from_dict({"reply_scope": bad})


def test_scope_command_preserves_config_and_secrets(tmp_path, monkeypatch):
    import json
    from messenger_ai import cli

    raw = {"allowed_threads": [THREAD], "model": "custom", "dry_run": True}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    secret = tmp_path / "secrets.json"
    secret.write_text("untouched")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    cli.set_reply_scope("all_private")
    assert json.loads(path.read_text()) == {**raw, "reply_scope": "all_private"}
    assert secret.read_text() == "untouched"
    cli.set_reply_scope("allowlist")
    assert json.loads(path.read_text()) == {**raw, "reply_scope": "allowlist"}


class WaitingAI:
    def __init__(self, error=False):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.error = error

    async def generate(self, history, reserve):
        from messenger_ai.ai import AIError

        assert reserve()
        self.entered.set()
        await self.release.wait()
        if self.error:
            raise AIError("Model tạm lỗi.")
        return "Câu trả lời hoàn chỉnh."


class TypingSender(Sender):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.started = asyncio.Event()
        self.refreshed = asyncio.Event()
        self.stopped = asyncio.Event()

    async def set_typing(self, message, is_typing):
        await super().set_typing(message, is_typing)
        if is_typing:
            if self.started.is_set():
                self.refreshed.set()
            self.started.set()
        else:
            self.stopped.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["sent", "ai_error", "send_error", "unknown"])
async def test_typing_during_ai_and_clears_on_every_result(tmp_path, finish):
    ai = WaitingAI(error=finish == "ai_error")
    sender = TypingSender(
        error=finish == "send_error",
        result={"messageId": "sent", "deliveryStatus": "unknown"}
        if finish == "unknown"
        else None,
    )
    bot, state, _, _, _ = make_bot(tmp_path, ai=ai, sender=sender)
    bot.receive(message())
    await asyncio.wait_for(sender.started.wait(), 1)
    assert ai.entered.is_set() and sender.calls == []
    assert sender.typing_calls == [(THREAD, True)]
    ai.release.set()
    await asyncio.wait_for(drain(bot), 1)
    assert sender.typing_calls == [(THREAD, True), (THREAD, False)]
    assert len(sender.calls) == (finish != "ai_error")
    assert not bot.typing_tasks
    state.close()


@pytest.mark.asyncio
async def test_typing_refreshes_while_waiting_without_extra_ai_calls(tmp_path, monkeypatch):
    from messenger_ai import core

    monkeypatch.setattr(core, "TYPING_REFRESH_SECONDS", 0.01)
    ai, sender = WaitingAI(), TypingSender()
    bot, state, _, _, _ = make_bot(tmp_path, ai=ai, sender=sender)
    bot.receive(message())
    await asyncio.wait_for(sender.refreshed.wait(), 1)
    assert sender.calls == [] and len(sender.typing_calls) >= 2
    ai.release.set()
    await asyncio.wait_for(drain(bot), 1)
    assert sender.typing_calls[-1] == (THREAD, False)
    # Typing refreshes do not use the AI budget.
    day = "2027-01-15"  # NOW in Vietnam.
    assert state.reserve_ai(day, 2)
    assert not state.reserve_ai(day, 2)
    state.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sender_id,text", [("111", "Mình đang tự nhắn"), ("222", "Đừng trả lời nữa")]
)
async def test_handoff_clears_typing_before_ai_returns(tmp_path, sender_id, text):
    ai, sender = WaitingAI(), TypingSender()
    bot, state, _, _, _ = make_bot(tmp_path, ai=ai, sender=sender)
    bot.receive(message())
    await asyncio.wait_for(sender.started.wait(), 1)
    bot.receive(message(mid="stop", sender=sender_id, text=text))
    await asyncio.wait_for(sender.stopped.wait(), 1)
    assert not ai.release.is_set() and sender.calls == []
    assert state.paused(THREAD, NOW)
    ai.release.set()
    await asyncio.wait_for(drain(bot), 1)
    assert sender.calls == []
    assert sender.typing_calls == [(THREAD, True), (THREAD, False)]
    state.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "timeout"])
async def test_typing_failure_never_blocks_reply_or_leaks_error(tmp_path, monkeypatch, failure):
    from messenger_ai import core

    monkeypatch.setattr(core, "TYPING_UPDATE_TIMEOUT", 0.01)

    class BrokenTyping(TypingSender):
        async def set_typing(self, message, is_typing):
            await super().set_typing(message, is_typing)
            if failure == "timeout":
                await asyncio.Event().wait()
            raise RuntimeError("cookie=SECRET; private content")

    ai, sender = WaitingAI(), BrokenTyping()
    bot, state, _, _, logs = make_bot(tmp_path, ai=ai, sender=sender)
    bot.receive(message())
    await asyncio.wait_for(sender.stopped.wait(), 1)
    ai.release.set()
    await asyncio.wait_for(drain(bot), 1)
    assert len(sender.calls) == 1
    assert "SECRET" not in " ".join(logs) and "private content" not in " ".join(logs)
    assert not bot.typing_tasks
    state.close()


@pytest.mark.asyncio
async def test_preview_never_emits_typing_even_while_ai_waits(tmp_path):
    ai, sender = WaitingAI(), TypingSender()
    bot, state, _, _, _ = make_bot(tmp_path, ai=ai, sender=sender, dry_run=True)
    bot.receive(message())
    await asyncio.wait_for(ai.entered.wait(), 1)
    assert not bot.typing_tasks and sender.typing_calls == []
    ai.release.set()
    await asyncio.wait_for(drain(bot), 1)
    assert sender.typing_calls == [] and sender.calls == []
    state.close()


@pytest.mark.asyncio
async def test_worker_cancellation_clears_typing(tmp_path):
    ai, sender = WaitingAI(), TypingSender()
    bot, state, _, _, _ = make_bot(tmp_path, ai=ai, sender=sender)
    bot.receive(message())
    await asyncio.wait_for(sender.started.wait(), 1)
    bot.tasks[THREAD].cancel()
    with pytest.raises(asyncio.CancelledError):
        await bot.tasks[THREAD]
    assert sender.typing_calls[-1] == (THREAD, False)
    assert sender.calls == [] and not bot.typing_tasks
    state.close()


@pytest.mark.asyncio
async def test_close_clears_typing_without_cancelling_inflight_send(tmp_path):
    sending, release_send = asyncio.Event(), asyncio.Event()

    class SlowSend(TypingSender):
        async def send(self, message, text):
            sending.set()
            await release_send.wait()
            return await super().send(message, text)

    ai, sender = WaitingAI(), SlowSend()
    bot, state, _, _, _ = make_bot(tmp_path, ai=ai, sender=sender)
    bot.receive(message())
    await asyncio.wait_for(sender.started.wait(), 1)
    ai.release.set()
    await asyncio.wait_for(sending.wait(), 1)
    closing = asyncio.create_task(bot.close())
    await asyncio.wait_for(sender.stopped.wait(), 1)
    assert not closing.done() and not release_send.is_set()
    release_send.set()
    await asyncio.wait_for(closing, 1)
    assert len(sender.calls) == 1 and not bot.typing_tasks
    state.close()


@pytest.mark.asyncio
async def test_new_message_during_typing_cleanup_still_gets_reply(tmp_path):
    stopping, release_stop, second_sent = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class SlowTypingStop(TypingSender):
        async def set_typing(self, message, is_typing):
            if not is_typing:
                stopping.set()
                await release_stop.wait()
            await super().set_typing(message, is_typing)

        async def send(self, message, text):
            result = await super().send(message, text)
            if len(self.calls) == 2:
                second_sent.set()
            return result

    ai, sender = WaitingAI(), SlowTypingStop()
    bot, state, _, _, _ = make_bot(tmp_path, ai=ai, sender=sender)
    bot.receive(message())
    await asyncio.wait_for(sender.started.wait(), 1)
    ai.release.set()
    await asyncio.wait_for(stopping.wait(), 1)
    assert len(sender.calls) == 1
    bot.receive(message(mid="second", text="Còn câu này nữa"))
    release_stop.set()
    await asyncio.wait_for(second_sent.wait(), 1)
    await asyncio.wait_for(drain(bot), 1)
    assert [original.id for original, _ in sender.calls] == ["m1", "second"]
    assert not bot.typing_tasks
    state.close()
