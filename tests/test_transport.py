import asyncio
from types import SimpleNamespace

import pytest

from messenger_ai.core import Message, parse_event
from messenger_ai.facebook import FacebookTransport


@pytest.mark.asyncio
async def test_real_adapter_constructor_and_send_routes(monkeypatch, tmp_path):
    import fbchat_v2

    instances = []

    class Listener:
        startup_timeout = 1
        connection_state = "connected"

        def __init__(self, data, **kwargs):
            self.kwargs = kwargs
            self.stopped = asyncio.Event()
            self.calls = []
            instances.append(self)

        def on_message(self, callback):
            self.callback = callback

        def set_connection_state_callback(self, callback):
            self.status = callback

        def wait_until_connected(self, timeout, *, require_e2ee):
            assert require_e2ee is True
            return True

        async def connect_mqtt(self):
            await self.stopped.wait()

        def stop(self):
            loop.call_soon_threadsafe(self.stopped.set)

        async def send_e2ee_message(self, jid, text, **kwargs):
            self.calls.append((jid, text, kwargs))
            return {"messageId": "sent-e2ee"}

        async def send_message(self, tid, text, **kwargs):
            self.calls.append((tid, text, kwargs))
            return {"messageId": "sent-regular"}

    async def home(cookie):
        assert cookie == "c_user=111; xs=TEST;"
        return {"FacebookID": "111"}

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(fbchat_v2, "dataGetHome", home)
    monkeypatch.setattr(fbchat_v2, "listeningE2EEEvent", Listener)
    transport = FacebookTransport(
        "c_user=111; xs=TEST;",
        tmp_path / "device.db",
        tmp_path / "bridge",
        log=lambda _: None,
    )
    await transport.connect()
    assert transport.own_id == "111"
    assert instances[0].kwargs["e2ee_memory_only"] is False
    assert instances[0].kwargs["device_path"] == str(tmp_path / "device.db")
    e2ee = Message("e2ee:222@msgr", "in-1", "222", "Hi", 100, "222@msgr", "222:1@msgr")
    await transport.send(e2ee, "Reply")
    regular = Message("thread:333", "in-2", "222", "Hi", 100, thread_id=333)
    await transport.send(regular, "Reply two")
    assert instances[0].calls == [
        (
            "222@msgr",
            "Reply",
            {"reply_to_id": "in-1", "reply_to_sender_jid": "222:1@msgr"},
        ),
        (333, "Reply two", {"reply_to_id": "in-2"}),
    ]
    await transport.close()


def test_bridge_queue_overflow_stops_instead_of_dropping_owner_message(tmp_path):
    transport = FacebookTransport("", tmp_path / "device", tmp_path / "bridge")
    for _ in range(1001):
        transport._enqueue({"type": "message"})
    assert transport.overflowed
    assert transport.queue.qsize() == 1000


@pytest.mark.asyncio
async def test_typing_uses_real_bridge_actions_and_existing_device(tmp_path):
    calls = []

    class Bridge:
        async def call(self, method, params):
            calls.append((method, params))
            return {}

    transport = FacebookTransport("", tmp_path / "device", tmp_path / "bridge")
    # Exercise the actual fbchat-v2 2.3.4 action serializer, without Facebook.
    transport.listener = SimpleNamespace(_bridge=Bridge())
    encrypted = Message("e2ee:222@msgr", "in-1", "222", "Hi", 100, "222@msgr")
    regular = parse_event(
        {
            "type": "message",
            "data": {
                "id": "in-2",
                "senderId": "222",
                "text": "Hi",
                "timestampMs": 100000,
                "threadId": 333,
                "threadType": 13,
            },
        }
    )
    for message in (encrypted, regular):
        await transport.set_typing(message, True)
        await transport.set_typing(message, False)
    assert calls == [
        ("sendE2EETyping", {"chatJid": "222@msgr", "isTyping": True}),
        ("sendE2EETyping", {"chatJid": "222@msgr", "isTyping": False}),
        (
            "sendTypingIndicator",
            {"threadId": 333, "isTyping": True, "isGroup": False, "threadType": 13},
        ),
        (
            "sendTypingIndicator",
            {"threadId": 333, "isTyping": False, "isGroup": False, "threadType": 13},
        ),
    ]
    assert not (tmp_path / "device").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("closing", [False, True])
async def test_typing_rejects_unready_or_closing_transport(tmp_path, closing):
    transport = FacebookTransport("", tmp_path / "device", tmp_path / "bridge")
    transport.closing = closing
    if closing:
        transport.listener = SimpleNamespace(_bridge=object())
    with pytest.raises(RuntimeError):
        await transport.set_typing(Message("thread:333", "in", "222", "Hi", 100), True)
