"""Owner activity through the pinned SDK, conversation identity and echo races."""

import asyncio
from collections import OrderedDict
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from messenger_ai.core import parse_event
from messenger_ai.facebook import FacebookTransport, _owner_aware_listener
from test_bot import NOW, THREAD, drain, make_bot, message


def encrypted(*, jid="222@msgr", sender=111, mid="manual"):
    return {
        "type": "e2eeMessage",
        "data": {
            "id": mid,
            "senderId": sender,
            "chatJid": jid,
            "senderJid": f"{sender}:7@msgr",
            "timestampMs": NOW * 1000,
            "text": "PRIVATE_MANUAL_WORDS",
        },
    }


def sdk_listener(callback, *, adapted):
    # Exercise the real pinned SDK's dispatcher and ID deduplication, with
    # no connection, native process, cookie or account involved.
    from fbchat_v2 import listeningE2EEEvent

    cls = (
        _owner_aware_listener(listeningE2EEEvent, "111", callback)
        if adapted
        else listeningE2EEEvent
    )
    listener = cls.__new__(cls)
    listener._recent_message_keys = OrderedDict()
    listener._on_message = callback
    listener._populate_regular = lambda _: None
    listener._populate_e2ee = lambda _: None
    return listener


@pytest.mark.asyncio
async def test_sdk_cross_transport_dedup_cannot_hide_the_usable_owner_message(tmp_path):
    fallback = {
        "type": "message",
        "data": {
            **encrypted()["data"],
            "threadId": 999,
            "threadType": 0,
        },
    }
    original_events = []
    original = sdk_listener(original_events.append, adapted=False)
    original._dispatch(fallback)
    original._dispatch(encrypted())
    assert original_events == [fallback]  # Confirm the underlying SDK behavior.

    bot, state, ai, sender, logs = make_bot(tmp_path)
    bot.receive(message())

    def receive(event):
        parsed = parse_event(event)
        if parsed is not None:
            bot.receive(parsed)

    listener = sdk_listener(receive, adapted=True)
    listener._dispatch(fallback)
    listener._dispatch(encrypted())
    listener._dispatch(encrypted())
    await drain(bot)
    assert state.paused(THREAD, NOW) and not sender.calls and not ai.calls
    assert sum("Bạn vừa nhắn thủ công" in line for line in logs) == 1
    assert "PRIVATE_MANUAL_WORDS" not in " ".join(logs)
    state.close()


def test_other_peoples_messages_still_use_the_real_sdk_deduplication():
    events = []
    listener = sdk_listener(events.append, adapted=True)
    event = encrypted(sender=222)
    listener._dispatch(event)
    listener._dispatch(event)
    assert events == [event]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "jid", ["222@msgr", "222:9@msgr", "222.3@msgr", "222.0:7@msgr", "222.3:7@msgr"]
)
async def test_manual_device_jid_cancels_a_draft_already_running_for_the_same_person(
    tmp_path, jid
):
    started, release = asyncio.Event(), asyncio.Event()

    class WaitingAI:
        async def generate(self, history, reserve):
            started.set()
            await release.wait()
            return "This draft must be discarded."

    bot, state, _, sender, logs = make_bot(tmp_path, ai=WaitingAI())
    bot.receive(message())
    await asyncio.wait_for(started.wait(), 1)
    bot.receive(parse_event(encrypted(jid=jid)))
    release.set()
    await asyncio.wait_for(drain(bot), 1)
    assert state.paused(THREAD, NOW) and not sender.calls
    assert any("300 giây" in line for line in logs)
    state.close()


@pytest.mark.asyncio
async def test_canonical_identity_keeps_the_original_wire_address_and_sender_reference(
    tmp_path,
):
    event = encrypted(jid="222.3:7@msgr", sender=222)
    parsed = parse_event(event)
    assert parsed.thread == THREAD and parsed.is_private
    transport = FacebookTransport("", tmp_path / "device", tmp_path / "bridge")
    send = AsyncMock(return_value={"messageId": "sent"})
    transport.listener = SimpleNamespace(send_e2ee_message=send)
    await transport.send(parsed, "Test reply")
    send.assert_awaited_once_with(
        "222.3:7@msgr",
        "Test reply",
        reply_to_id="manual",
        reply_to_sender_jid="222:7@msgr",
    )


@pytest.mark.asyncio
async def test_device_qualified_allowlist_still_selects_the_same_person(tmp_path):
    bot, state, ai, sender, _ = make_bot(
        tmp_path, allowed_threads=("e2ee:222.3:7@msgr",)
    )
    bot.receive(parse_event(encrypted(sender=222)))
    await drain(bot)
    assert len(sender.calls) == len(ai.calls) == 1
    state.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("jid", ["222:7@g.us", "222:7@msgr.invalid", "0:7@msgr"])
async def test_identity_normalization_does_not_authorize_groups_unknown_servers_or_zero_ids(
    tmp_path, jid
):
    bot, state, ai, sender, _ = make_bot(tmp_path, reply_scope="all_private")
    bot.receive(parse_event(encrypted(jid=jid, sender=222)))
    await drain(bot)
    assert not sender.calls and not ai.calls
    state.close()


@pytest.mark.asyncio
async def test_known_bot_message_id_from_another_transport_is_not_a_manual_reply(
    tmp_path,
):
    bot, state, _, sender, _ = make_bot(tmp_path, reply_scope="all_private")
    outbox = state.begin_send(THREAD, "PRIVATE_BOT_REPLY", NOW)
    state.finish_send(outbox, "sent", "bot-mid")
    bot.receive(
        parse_event(
            {
                "type": "message",
                "data": {
                    "id": "bot-mid",
                    "senderId": 111,
                    "threadId": 999,
                    "threadType": 13,
                    "timestampMs": NOW * 1000,
                    "text": "PRIVATE_BOT_REPLY",
                },
            }
        )
    )
    assert not state.paused("thread:999", NOW) and not sender.calls
    state.close()


@pytest.mark.asyncio
async def test_real_sdk_owner_echo_with_device_jid_before_send_ack_does_not_pause(
    tmp_path,
):
    bot, state, ai, sender, logs = make_bot(tmp_path)

    def receive(event):
        bot.receive(parse_event(event))

    listener = sdk_listener(receive, adapted=True)

    async def send(original, text):
        sender.calls.append((original, text))
        echo = encrypted(jid="222.3:7@msgr", mid="early-sdk-echo")
        echo["data"]["text"] = text
        listener._dispatch(echo)
        return {"messageId": "early-sdk-echo"}

    sender.send = send
    bot.receive(message())
    await drain(bot)
    assert len(ai.calls) == len(sender.calls) == 1
    assert not state.paused(THREAD, NOW)
    assert not any("Bạn vừa nhắn thủ công" in line for line in logs)
    state.close()


@pytest.mark.asyncio
async def test_same_words_in_a_different_chat_cannot_hide_a_manual_reply(tmp_path):
    bot, state, _, _, _ = make_bot(tmp_path, reply_scope="all_private")
    state.begin_send("e2ee:333@msgr", "Same words", NOW)
    bot.receive(message("manual-new-id", "Same words", sender="111"))
    assert state.paused(THREAD, NOW)
    state.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["private", "scope", "age"])
async def test_ignored_owner_activity_reports_a_safe_rate_limited_reason(
    tmp_path, reason
):
    bot, state, _, _, logs = make_bot(tmp_path)
    changes = {
        "private": {"is_private": False},
        "scope": {"thread": "e2ee:333@msgr"},
        "age": {"timestamp": NOW - 10000},
    }[reason]
    activity = replace(message("ignored", "PRIVATE_WORDS", sender="111"), **changes)
    bot.receive(activity)
    bot.receive(activity)
    assert len(logs) == 1 and logs[0].startswith("Nhường:")
    assert "PRIVATE_WORDS" not in logs[0] and "333" not in logs[0]
    assert not state.paused(THREAD, NOW)
    state.close()


@pytest.mark.parametrize("code", [2, 0, "2", True, {"secret": "PRIVATE_ERROR"}])
def test_bridge_errors_log_only_a_fixed_classification_not_the_private_payload(
    tmp_path, code
):
    logs = []
    transport = FacebookTransport(
        "", tmp_path / "device", tmp_path / "bridge", log=logs.append
    )
    event = {"type": "error", "data": {"code": code, "message": "PRIVATE_ERROR"}}
    transport._enqueue(event)
    transport._enqueue(event)
    assert len(logs) == 1 and transport.queue.empty()
    assert "PRIVATE_ERROR" not in logs[0]
    assert ("chưa giải mã" in logs[0]) is (type(code) is int and code == 2)


def test_invalid_owner_metadata_is_reported_without_logging_identifiers_or_content(
    tmp_path,
):
    logs = []
    transport = FacebookTransport(
        "", tmp_path / "device", tmp_path / "bridge", log=logs.append
    )
    transport.own_id = "111"
    event = encrypted()
    del event["data"]["chatJid"]
    transport._enqueue(event)
    transport._enqueue(event)
    assert (
        transport.queue.empty() and len(logs) == 1 and "metadata thiếu/sai" in logs[0]
    )
    assert "111" not in logs[0] and "PRIVATE_MANUAL_WORDS" not in logs[0]
