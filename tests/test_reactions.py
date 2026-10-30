from dataclasses import replace
import json
from types import SimpleNamespace

import httpx
import pytest

from messenger_ai.ai import ChatAI, SearchRequested, ProviderUnavailable
from messenger_ai.search_routing import SEARCH_REQUEST
from messenger_ai.config import Settings
from messenger_ai.facebook import FacebookTransport
from messenger_ai.reactions import EMOJI, parse_reply
from test_bot import FakeAI, Sender, drain, make_bot, message


@pytest.mark.parametrize("reaction", EMOJI)
@pytest.mark.parametrize("only", [False, True])
def test_model_protocol(reaction, only):
    text = f"[[react:{reaction}{':only' if only else ''}]]\nMình hiểu rồi."
    result = parse_reply(text)
    assert result.text == "Mình hiểu rồi." and result.reaction == reaction
    assert result.reaction_only is only
    assert parse_reply(text, enabled=False).reaction is None


@pytest.mark.parametrize(
    "text",
    [
        "[[react:angry]]\nBody",
        "[[react:none:only]]\nBody",
        "[[react:like]]",
        "[[react:like]]\n",
        "[[react:like]]\n[[react:love]]\nBody",
    ],
)
def test_invalid_protocol_never_reaches_messages(text):
    with pytest.raises(ValueError):
        parse_reply(text)


class ReactSender(Sender):
    def __init__(self, *, fail=False):
        super().__init__()
        self.reactions = []
        self.fail = fail
        self.on_react = None

    async def react(self, msg, reaction):
        self.reactions.append((msg.id, reaction))
        if self.on_react:
            self.on_react()
        if self.fail:
            raise TimeoutError("PRIVATE")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "only,fail,expected_messages",
    [(True, False, 0), (True, True, 1), (False, False, 1), (False, True, 1)],
)
async def test_react_only_falls_back_to_text_and_both_actions_are_deduplicated(
    tmp_path, only, fail, expected_messages
):
    sender = ReactSender(fail=fail)
    bot, state, ai, _, logs = make_bot(
        tmp_path,
        sender=sender,
        ai=FakeAI(f"[[react:like{':only' if only else ''}]]\nMình hiểu rồi."),
        reaction_mode="auto",
    )
    incoming = message(text="Ok cảm ơn nhé")
    bot.receive(incoming)
    await drain(bot)
    bot.receive(incoming)
    await drain(bot)
    assert sender.reactions == [(incoming.id, "like")]
    assert len(sender.calls) == expected_messages and len(ai.calls) == 1
    assert all("[[react:" not in text for _, text in sender.calls)
    assert "PRIVATE" not in " ".join(logs)
    rows = state.db.execute("SELECT kind,status FROM outbox ORDER BY id").fetchall()
    assert rows[0] == ("reaction", "unknown" if fail else "sent")
    assert not state.bot_echo(
        incoming.thread, incoming.id, f"{incoming.id}:like", bot.clock()
    )
    state.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "option", [{"reaction_mode": "off"}, {"reaction_mode": "auto", "dry_run": True}]
)
async def test_off_and_preview_do_not_react(tmp_path, option):
    sender = ReactSender()
    bot, state, *_ = make_bot(
        tmp_path, sender=sender, ai=FakeAI("[[react:like:only]]\nĐã hiểu."), **option
    )
    bot.receive(message())
    await drain(bot)
    assert not sender.reactions
    assert len(sender.calls) == (0 if option.get("dry_run") else 1)
    state.close()


@pytest.mark.asyncio
async def test_owner_takes_over_during_reaction_so_no_old_text_is_sent(tmp_path):
    sender = ReactSender()
    bot, state, *_ = make_bot(
        tmp_path,
        sender=sender,
        ai=FakeAI("[[react:like]]\nOld answer"),
        reaction_mode="auto",
    )
    sender.on_react = lambda: bot.receive(
        message(mid="manual", text="Mình đang trả lời", sender="111")
    )
    bot.receive(message())
    await drain(bot)
    assert sender.reactions and not sender.calls
    state.close()


@pytest.mark.asyncio
async def test_group_is_never_reacted_to(tmp_path):
    sender = ReactSender()
    bot, state, ai, *_ = make_bot(
        tmp_path,
        sender=sender,
        ai=FakeAI("[[react:like]]\nBody"),
        reaction_mode="auto",
        reply_scope="all_private",
    )
    bot.receive(replace(message(), is_private=False))
    await drain(bot)
    assert not sender.reactions and not ai.calls
    state.close()


@pytest.mark.asyncio
async def test_reaction_rpc_uses_the_existing_bridge_with_exact_encrypted_and_regular_targets(
    tmp_path,
):
    calls = []

    class Bridge:
        async def call(self, method, params):
            calls.append((method, params))
            return {}

    transport = FacebookTransport("", tmp_path / "device", tmp_path / "bridge")
    transport.own_id = "111"
    transport.listener = SimpleNamespace(_bridge=Bridge())
    transport.native_reaction_timestamp = True
    encrypted = message()
    regular = replace(encrypted, chat_jid="", thread="thread:222", thread_id=222)
    await transport.react(encrypted, "like")
    await transport.react(regular, "love")
    assert calls == [
        (
            "sendE2EEReaction",
            {
                "chatJid": "222@msgr",
                "senderJid": "222:1@msgr",
                "messageId": "m1",
                "emoji": EMOJI["like"],
            },
        ),
        ("sendReaction", {"threadId": 222, "messageId": "m1", "emoji": EMOJI["love"]}),
    ]
    for msg, kind in [
        (replace(encrypted, is_private=False), "like"),
        (replace(encrypted, sender_id="111"), "like"),
        (replace(encrypted, sender_jid=""), "like"),
        (encrypted, "angry"),
    ]:
        with pytest.raises(ValueError):
            await transport.react(msg, kind)
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("thread_type", [7, 13, 15])
async def test_encrypted_web_projection_is_not_reacted_to_over_regular_transport(tmp_path, thread_type):
    calls = []

    class Bridge:
        async def call(self, method, params):
            calls.append(method)
            return {}

    transport = FacebookTransport("", tmp_path / "device", tmp_path / "bridge", log=lambda _: None)
    transport.own_id = "111"
    transport.listener = SimpleNamespace(_bridge=Bridge())
    incoming = replace(message(), chat_jid="", thread_id=222, thread_type=thread_type)
    with pytest.raises(ValueError):
        await transport.react(incoming, "like")
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("capabilities,expected", [(["e2eeReactionTimestamp"], True), ([], False), ("e2eeReactionTimestamp", False)])
async def test_native_reaction_requires_verified_bridge_capability(tmp_path, capabilities, expected):
    calls = []

    class Bridge:
        async def call(self, method, params):
            calls.append(method)
            return {"capabilities": capabilities} if method == "hello" else {}

    transport = FacebookTransport("", tmp_path / "device", tmp_path / "bridge", log=lambda _: None)
    transport.own_id = "111"
    transport.listener = SimpleNamespace(_bridge=Bridge())
    await transport._reaction_capabilities()
    assert transport.native_reaction_timestamp is expected
    if expected:
        await transport.react(message(), "like")
        assert calls == ["hello", "sendE2EEReaction"]
    else:
        with pytest.raises(RuntimeError):
            await transport.react(message(), "like")
        assert calls == ["hello"]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["google", "groq", "cloudflare", "nvidia"])
async def test_each_provider_receives_the_action_contract_and_returns_it_in_one_request(
    provider,
):
    captured = []

    def handler(request):
        body = json.loads(request.content)
        captured.append(body)
        answer = "[[react:like:only]]\nỪ, mình hiểu rồi."
        if provider == "google":
            assert "ĐIỀU KHIỂN CẢM XÚC" in body["systemInstruction"]["parts"][0]["text"]
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {"parts": [{"text": answer}]},
                        }
                    ]
                },
            )
        assert "ĐIỀU KHIỂN CẢM XÚC" in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": answer}}]
            },
        )

    settings = Settings(
        ai_provider=provider,
        reaction_mode="auto",
        model="gemini-3.5-flash-lite"
        if provider == "google"
        else "test/model"
        if provider == "nvidia"
        else "@cf/test/model"
        if provider == "cloudflare"
        else "test-model",
        minimum_ai_interval_seconds=0,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "nvapi-" + "a" * 32 if provider == "nvidia" else "KEY",
            settings,
            "Public synthetic persona",
            account_id="c" * 32,
            client=client,
            fail_fast=True,
        )
        result = await ai.generate(
            [{"role": "user", "content": "Cảm ơn nhé"}], lambda: True
        )
    assert parse_reply(result).reaction_only and len(captured) == 1


@pytest.mark.asyncio
async def test_search_handoff_and_grounded_answer_keep_working_with_reactions():
    responses = [SEARCH_REQUEST, "[[react:none]]\nThông tin vừa tra được."]

    def handler(request):
        answer = responses.pop(0)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": answer}]},
                        "groundingMetadata": {"webSearchQueries": ["synthetic query"]},
                    }
                ]
            },
        )

    settings = Settings(
        ai_provider="google",
        model="gemini-3.5-flash-lite",
        reaction_mode="auto",
        minimum_ai_interval_seconds=0,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI("KEY", settings, "Public persona", client=client, fail_fast=True)
        with pytest.raises(SearchRequested):
            await ai.generate(
                [{"role": "user", "content": "Giá hôm nay là bao nhiêu?"}],
                lambda: True,
                allow_search_request=True,
            )
        result = await ai.generate(
            [{"role": "user", "content": "Giá hôm nay là bao nhiêu?"}],
            lambda: True,
            require_search=True,
        )
    assert parse_reply(result).text == "Thông tin vừa tra được." and ai.last_search_used


@pytest.mark.asyncio
async def test_invalid_control_output_is_retryable_instead_of_being_sent():
    def handler(_):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "[[react:unknown]]\nBody"},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "KEY",
            Settings(reaction_mode="auto", minimum_ai_interval_seconds=0),
            "Persona",
            client=client,
            fail_fast=True,
        )
        with pytest.raises(ProviderUnavailable):
            await ai.generate([{"role": "user", "content": "Hello"}], lambda: True)
