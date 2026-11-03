"""Pinned Go event schema and actual SDK dispatch, without a Facebook session."""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from messenger_ai import cli
from messenger_ai.config import Settings
from messenger_ai.core import Message, parse_event
from messenger_ai.e2ee_activity import undecryptable_notice
from messenger_ai.facebook import FacebookTransport
from messenger_ai.state import State
from test_bot import NOW, THREAD, drain, make_bot, message
from test_manual_handoff import encrypted


def failure(
    *,
    unavailable=True,
    sender="111:7@msgr",
    from_me=True,
    chat="222.3:7@msgr",
    group=False,
    timestamp=NOW,
):
    return {
        "type": "raw",
        "timestamp": int(timestamp * 1000),
        "data": {
            "from": "whatsmeow",
            "type": "UndecryptableMessage",
            "data": {
                "IsUnavailable": unavailable,
                "UnavailableType": "",
                "DecryptFailMode": "hide",
                "Info": {
                    "Sender": sender,
                    "Chat": chat,
                    "IsFromMe": from_me,
                    "IsGroup": group,
                    "ID": "manual-unavailable",
                    "Timestamp": datetime.fromtimestamp(
                        timestamp, timezone.utc
                    ).isoformat(),
                    "PushName": "PRIVATE_NAME",
                    "DeviceSentMeta": {"Phash": "PRIVATE_DATA"},
                },
                "PRIVATE_BODY": "PRIVATE_CONTENT_MUST_NOT_BE_QUEUED",
            },
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", [True, False])
async def test_owner_metadata_pauses_the_right_chat_without_decrypting_text(
    tmp_path, unavailable
):
    started, release = asyncio.Event(), asyncio.Event()

    class WaitingAI:
        async def generate(self, history, reserve):
            started.set()
            await release.wait()
            return "Must never send this draft."

    bot, state, _, sender, logs = make_bot(tmp_path, ai=WaitingAI())
    bot.receive(message())
    await asyncio.wait_for(started.wait(), 1)
    notice = undecryptable_notice(failure(unavailable=unavailable), "111")
    assert notice.source == "self" and notice.chat == "private"
    assert notice.kind == ("missing_ciphertext" if unavailable else "decrypt_failed")
    assert notice.activity.thread == THREAD and notice.activity.metadata_only
    assert notice.activity.text == "" and not notice.activity.images
    bot.receive(notice.activity)
    bot.receive(notice.activity)  # Native retry of the same failed message.
    release.set()
    await asyncio.wait_for(drain(bot), 1)
    assert state.paused(THREAD, NOW) and not state.paused("e2ee:333@msgr", NOW)
    assert not sender.calls
    assert sum("Đã nhường theo metadata" in line for line in logs) == 1
    assert "PRIVATE" not in " ".join(logs) and "PRIVATE" not in repr(notice)
    state.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"sender": "333:7@msgr", "from_me": False},
        {"sender": "333:7@msgr", "from_me": True},
        {"sender": "111:7@msgr", "from_me": False},
        {"from_me": "true"},
        {"from_me": 1},
        {"group": True},
        {"group": None},
        {"group": 0},
        {"chat": "333@g.us"},
        {"chat": "222@msgr.invalid"},
        {"chat": "111:3@msgr"},
        {"sender": "111@msgr.invalid"},
    ],
)
def test_unverified_sources_groups_and_self_chat_cannot_pause_an_arbitrary_person(
    changes,
):
    notice = undecryptable_notice(failure(**changes), "111")
    assert notice.activity is None
    assert "PRIVATE" not in repr(notice)


@pytest.mark.parametrize(
    "field,value",
    [
        ("ID", ""),
        ("ID", "a" * 501),
        ("ID", "bad\nvalue"),
        ("ID", 123),
        ("Timestamp", "not-a-date"),
        ("Timestamp", "2026-11-03T08:18:01"),
        ("Timestamp", 123),
        ("Timestamp", "0001-01-01T00:00:00Z"),
    ],
)
def test_invalid_identity_or_time_never_becomes_owner_activity(field, value):
    event = failure()
    event["data"]["data"]["Info"][field] = value
    notice = undecryptable_notice(event, "111")
    assert notice.activity is None


@pytest.mark.parametrize("change", ["source", "event_type", "raw_type", "missing_info"])
def test_only_the_pinned_whatsmeow_failure_schema_is_read(change):
    event = failure()
    if change == "source":
        event["data"]["from"] = "lightspeed"
    elif change == "event_type":
        event["type"] = "message"
    elif change == "raw_type":
        event["data"]["type"] = "FBMessage"
    else:
        event["data"]["data"]["Info"] = None
    notice = undecryptable_notice(event, "111")
    assert notice is None or notice.activity is None


@pytest.mark.asyncio
@pytest.mark.parametrize("timestamp", [NOW - 10000, NOW + 31])
async def test_old_or_future_unavailable_activity_cannot_pause_a_live_conversation(
    tmp_path, timestamp
):
    bot, state, _, _, logs = make_bot(tmp_path)
    notice = undecryptable_notice(failure(timestamp=timestamp), "111")
    bot.receive(notice.activity)
    assert not state.paused(THREAD, NOW)
    assert any("thời gian tin" in line for line in logs)
    state.close()


@pytest.mark.asyncio
async def test_successful_later_decrypt_is_not_claimed_away_by_the_metadata_notice(
    tmp_path,
):
    bot, state, _, _, _ = make_bot(tmp_path)
    bot.receive(message())
    notice = undecryptable_notice(failure(), "111")
    bot.receive(notice.activity)
    await drain(bot)
    assert state.history(THREAD, 10, 1000) == [{"role": "user", "content": "Chào bạn"}]
    later = parse_event(encrypted(mid="manual-unavailable"))
    bot.receive(later)
    bot.receive(later)
    assert state.history(THREAD, 10, 1000) == [
        {"role": "user", "content": "Chào bạn"},
        {"role": "assistant", "content": "PRIVATE_MANUAL_WORDS"},
    ]
    state.close()


@pytest.mark.asyncio
async def test_unavailable_echo_with_confirmed_summary_id_does_not_pause_the_chat(
    tmp_path,
):
    bot, state, ai, sender, logs = make_bot(tmp_path)
    outbox = state.begin_send(THREAD, "Summary text", NOW, kind="summary")
    state.finish_send(outbox, "sent", "manual-unavailable")
    bot.receive(message())
    bot.receive(undecryptable_notice(failure(), "111").activity)
    await drain(bot)
    assert not state.paused(THREAD, NOW) and len(ai.calls) == len(sender.calls) == 1
    assert not any("Đã nhường theo metadata" in line for line in logs)
    state.close()


@pytest.mark.asyncio
async def test_plain_metadata_for_another_sender_cannot_enter_the_ai_queue(tmp_path):
    bot, state, ai, sender, _ = make_bot(tmp_path)
    activity = replace(undecryptable_notice(failure(), "111").activity, sender_id="333")
    bot.receive(activity)
    await drain(bot)
    assert not ai.calls and not sender.calls and not state.paused(THREAD, NOW)
    state.close()


@pytest.mark.asyncio
async def test_actual_sdk_raw_dispatch_to_transport_keeps_only_verified_metadata(
    monkeypatch, tmp_path
):
    import fbchat_v2

    actual_dispatch = fbchat_v2.listeningE2EEEvent._dispatch
    instances, logs = [], []

    class Listener:
        startup_timeout = 1
        connection_state = "connected"
        _dispatch = actual_dispatch

        def __init__(self, data, **kwargs):
            self.done = asyncio.Event()
            self.kwargs = kwargs
            instances.append(self)

        def on_message(self, callback):
            self._on_message = callback

        def set_connection_state_callback(self, callback):
            pass

        def wait_until_connected(self, *args, **kwargs):
            return True

        async def connect_mqtt(self):
            await self.done.wait()

        def stop(self):
            loop.call_soon_threadsafe(self.done.set)

    monkeypatch.setattr(
        fbchat_v2, "dataGetHome", AsyncMock(return_value={"FacebookID": "111"})
    )
    monkeypatch.setattr(fbchat_v2, "listeningE2EEEvent", Listener)
    loop = asyncio.get_running_loop()
    transport = FacebookTransport(
        "c_user=111; xs=TEST;",
        tmp_path / "device",
        tmp_path / "bridge",
        log=logs.append,
    )
    await transport.connect()
    try:
        listener = instances[0]
        assert listener.kwargs["debug_errors"] is False
        listener._dispatch(failure())
        await asyncio.sleep(0)
        queued = transport.queue.get_nowait()
        assert (
            isinstance(queued, Message)
            and queued.metadata_only
            and queued.thread == THREAD
        )
        assert "PRIVATE" not in repr(queued) and queued.text == ""
        listener._dispatch(failure(sender="333@msgr", from_me=False))
        listener._dispatch(failure(sender="333@msgr", from_me=False))
        await asyncio.sleep(0)
        assert transport.queue.empty()
        assert sum("nguồn=người khác" in line for line in logs) == 1
        assert "PRIVATE" not in " ".join(logs) and "111" not in " ".join(logs)
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_cli_consumes_internal_metadata_activity_without_treating_it_as_chat_text(
    tmp_path, monkeypatch
):
    now = datetime.now(timezone.utc).timestamp()
    incoming = encrypted(sender=222, mid="new-incoming")
    incoming["data"]["timestampMs"] = now * 1000
    metadata = undecryptable_notice(failure(timestamp=now), "111").activity

    async def events():
        yield incoming
        yield metadata
        await asyncio.sleep(0)

    ai = SimpleNamespace(
        description="Test AI",
        generate=AsyncMock(return_value="Must not reply"),
        close=AsyncMock(),
    )
    transport = SimpleNamespace(
        own_id="111",
        connect=AsyncMock(),
        close=AsyncMock(),
        events=events,
        send=AsyncMock(),
        set_typing=AsyncMock(),
    )
    settings = Settings(reply_scope="all_private", dry_run=False, debounce_seconds=0)
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "load_persona", lambda _: "Test persona")
    monkeypatch.setattr(
        cli, "load_secrets", lambda: {"facebook_cookie": "PRIVATE_COOKIE"}
    )
    monkeypatch.setattr(
        "scripts.fetch_assets.ensure_bridge", lambda: tmp_path / "bridge"
    )
    monkeypatch.setattr(
        "messenger_ai.facebook.FacebookTransport", lambda *args: transport
    )
    monkeypatch.setattr("messenger_ai.ai.create_ai", lambda *args: ai)
    monkeypatch.setattr("messenger_ai.ai.create_vision_ai", lambda *args: None)
    await asyncio.wait_for(cli.run(discovery=False, live=True, preview=False), 2)
    state = State(tmp_path / "data/state.sqlite3")
    try:
        assert (
            state.paused(THREAD, now)
            and not ai.generate.called
            and not transport.send.called
        )
    finally:
        state.close()
