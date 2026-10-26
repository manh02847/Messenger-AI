import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime

import httpx
import pytest
import pytest_asyncio

from messenger_ai import ai as module
from messenger_ai.ai import (
    AIError,
    AIBudgetExceeded,
    ChatAI,
    ProviderUnavailable,
    create_ai,
)
from messenger_ai.config import Settings
from messenger_ai.core import Message, ReplyBot, VIETNAM
from messenger_ai.images import ImageAttachment, test_image as red_image
from messenger_ai.state import State

THREAD = "e2ee:222@msgr"
OTHER = "e2ee:333@msgr"
NOW = 1800000000.0


@dataclass
class Clock:
    now: float = NOW


class AI:
    last_used = "Test AI"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def generate(self, history, reserve, *, images=None):
        if not reserve():
            raise AIBudgetExceeded()
        self.calls.append((deepcopy(history), images))
        await asyncio.sleep(0)
        result = self.outcomes.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class Transport:
    def __init__(self):
        self.sent, self.typing, self.downloads = [], [], []

    async def send(self, message, text):
        self.sent.append((message, text))
        return {"messageId": f"reply-{len(self.sent)}"}

    async def set_typing(self, message, active):
        self.typing.append((message.thread, active))

    async def load_image(self, attachment, *, encrypted):
        self.downloads.append(attachment)
        return red_image()


class WatchedEvent(asyncio.Event):
    def __init__(self):
        super().__init__()
        self.waiting = asyncio.Event()

    async def wait(self):
        self.waiting.set()
        return await super().wait()


def incoming(
    clock, mid="one", text="Bạn đang làm gì?", thread=THREAD, sender="222", images=()
):
    jid = thread.partition(":")[2]
    return Message(
        thread,
        mid,
        sender,
        text,
        clock.now,
        jid,
        f"{sender}:1@msgr",
        is_private=True,
        images=images,
    )


@pytest_asyncio.fixture
async def make(tmp_path):
    instances = []

    def build(ai=None, *, image_ai=None, **options):
        clock, transport, logs = Clock(), Transport(), []
        state = State(tmp_path / str(len(instances)) / "state.sqlite3")
        settings = replace(
            Settings(
                allowed_threads=(THREAD, OTHER),
                dry_run=False,
                debounce_seconds=0,
                reply_cooldown_seconds=0,
                minimum_ai_interval_seconds=0,
            ),
            **options,
        )
        ai = ai or AI(["Trả lời."])
        bot = ReplyBot(
            settings,
            state,
            ai,
            transport,
            "111",
            clock=lambda: clock.now,
            image_ai=image_ai,
            log=logs.append,
        )
        instances.append((bot, state))
        return bot, state, ai, transport, clock, logs

    yield build
    for bot, state in instances:
        await bot.close()
        state.close()


async def finish(bot):
    await asyncio.wait_for(asyncio.gather(*list(bot.tasks.values())), 2)


def fast_forward(bot, clock):
    waits = []

    async def wait(thread, revision, delay):
        waits.append(delay)
        await bot._finish_typing(thread)
        clock.now += delay

    bot._wait_retry = wait
    return waits


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["malformed", "empty", "json"])
async def test_single_google_model_retains_turn_after_corrupt_response(make, fault):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1 and fault == "json":
            return httpx.Response(200, text="PRIVATE_BODY")
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "MALFORMED_RESPONSE"
                        if len(calls) == 1 and fault == "malformed"
                        else "STOP",
                        "content": {
                            "parts": [
                                {"text": "" if len(calls) == 1 else "Đã trả lời."}
                            ]
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "KEY",
            Settings(
                ai_provider="google",
                model="gemini-3.5-flash-lite",
                minimum_ai_interval_seconds=0,
            ),
            "Persona",
            client=client,
        )
        bot, state, _, transport, clock, logs = make(ai)
        waits = fast_forward(bot, clock)
        bot.receive(incoming(clock))
        await finish(bot)
    assert waits == [1] and len(calls) == 2
    assert len(transport.sent) == 1 and transport.sent[0][1] == "Đã trả lời."
    assert state.db.execute("SELECT count(*) FROM ai_calls").fetchone()[0] == 2
    assert len(state.history(THREAD, 12, 3500)) == 2
    assert "PRIVATE" not in " ".join(logs)


@pytest.mark.asyncio
@pytest.mark.parametrize("failures", [6, 64])
async def test_keeps_same_turn_beyond_age_limit_and_more_than_three_attempts_without_history_growth(
    make,
    failures,
):
    ai = AI([*[ProviderUnavailable("Busy", 1) for _ in range(failures)], "Đã trả lời."])
    bot, state, _, transport, clock, _ = make(ai, max_message_age_seconds=2)
    waits = fast_forward(bot, clock)
    bot.receive(incoming(clock))
    await finish(bot)
    assert len(ai.calls) == failures + 1 and len(transport.sent) == 1
    assert clock.now - NOW > bot.settings.max_message_age_seconds
    assert waits == [1] * failures
    assert all(history == ai.calls[0][0] for history, _ in ai.calls)
    assert state.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
    assert (
        state.db.execute("SELECT count(*) FROM ai_calls").fetchone()[0] == failures + 1
    )
    assert not bot.pending


@pytest.mark.asyncio
async def test_new_input_replaces_pending_question_without_shortening_or_extending_cooldown(
    make,
):
    ai = AI([ProviderUnavailable("Busy", 60), "Trả lời câu mới."])
    bot, state, _, transport, clock, _ = make(ai)
    waits = []

    async def wait(thread, revision, delay):
        waits.append(delay)
        await bot._finish_typing(thread)
        if len(waits) == 1:
            clock.now += 1
            bot.receive(incoming(clock, "new", "Câu hỏi mới nhất?"))
        else:
            clock.now += delay

    bot._wait_retry = wait
    bot.receive(incoming(clock))
    await finish(bot)
    assert waits == [60, 59]
    assert len(ai.calls) == 2 and len(transport.sent) == 1
    assert ai.calls[-1][0][-1]["content"] == "Câu hỏi mới nhất?"
    assert transport.sent[0][0].id == "new"
    assert state.db.execute("SELECT count(*) FROM ai_calls").fetchone()[0] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["manual", "human", "close"])
async def test_long_retry_wait_is_interrupted_by_manual_reply_stop_or_shutdown(
    make, stop
):
    bot, state, ai, transport, clock, _ = make(
        AI([ProviderUnavailable("Quota", 86400)])
    )
    event = WatchedEvent()
    bot.retry_wakeups[THREAD] = event
    bot.receive(incoming(clock))
    await asyncio.wait_for(event.waiting.wait(), 1)
    assert (THREAD, False) in transport.typing
    if stop == "close":
        await asyncio.wait_for(bot.close(), 1)
    else:
        bot.receive(
            incoming(
                clock,
                "stop",
                "Mình tự trả lời" if stop == "manual" else "Đừng trả lời nữa",
                sender="111" if stop == "manual" else "222",
            )
        )
        await finish(bot)
        assert state.paused(THREAD, clock.now)
    assert len(ai.calls) == 1 and not transport.sent and not bot.pending


@pytest.mark.asyncio
async def test_multiple_chats_share_cooldown_and_a_single_inflight_attempt(make):
    ai = AI([ProviderUnavailable("Busy", 60), "Một.", "Hai."])
    bot, state, _, transport, clock, _ = make(ai)
    events = {thread: WatchedEvent() for thread in (THREAD, OTHER)}
    bot.retry_wakeups.update(events)
    for thread in (THREAD, OTHER):
        bot.receive(
            incoming(clock, thread=thread, sender="222" if thread == THREAD else "333")
        )
    await asyncio.wait_for(
        asyncio.gather(*(event.waiting.wait() for event in events.values())), 1
    )
    assert len(ai.calls) == 1
    assert bot.retry_after[id(ai)] == NOW + 60
    clock.now += 60
    for event in events.values():
        event.set()
    await finish(bot)
    assert len(ai.calls) == 3 and len(transport.sent) == 2
    assert {message.thread for message, _ in transport.sent} == {THREAD, OTHER}
    assert state.db.execute("SELECT count(*) FROM ai_calls").fetchone()[0] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("semantic", [False, True])
@pytest.mark.parametrize("same_thread", [False, True])
@pytest.mark.parametrize("text", ["Bạn đang làm gì?", "thế à", "ừ vậy hả"])
async def test_waiting_for_search_does_not_hold_a_regular_chat_on_healthy_flash(
    make, monkeypatch, same_thread, text, semantic
):
    calls = []
    first_question = (
        "Quán Phở Thìn ở Lò Đúc đóng cửa lúc nào?"
        if semantic
        else "Thời tiết Hà Nội hôm nay thế nào?"
    )

    def handler(request):
        model = request.url.path.rsplit("/", 1)[-1].split(":")[0]
        calls.append(model)
        if model == "gemma-4-26b-a4b-it":
            return httpx.Response(429)
        body = json.loads(request.content)
        reply = (
            "[[NEED_SEARCH]]"
            if semantic and body["contents"][-1]["parts"][0]["text"] == first_question
            else "Chào bạn."
        )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": reply}]},
                    }
                ]
            },
        )

    settings = Settings.from_dict(
        {
            "provider_enabled": {
                p: p == "google" for p in ("google", "nvidia", "groq", "cloudflare")
            },
            "text_models": [
                "google:gemini-3.5-flash-lite",
                "google:gemma-4-26b-a4b-it",
            ],
            "model_features": {"google:gemma-4-26b-a4b-it": {"search": "auto"}},
            "minimum_ai_interval_seconds": 0,
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(
            module, "ChatAI", lambda *a, **kw: ChatAI(*a, **kw, client=client)
        )
        ai = create_ai({"google_api_key": "KEY"}, settings, "Persona")
        bot, state, _, transport, clock, logs = make(ai)
        waiting = WatchedEvent()
        bot.retry_wakeups[THREAD] = waiting
        bot.receive(incoming(clock, text=first_question))
        await asyncio.wait_for(waiting.waiting.wait(), 1)
        assert THREAD in bot.pending and not transport.sent
        target = THREAD if same_thread else OTHER
        bot.receive(
            incoming(
                clock,
                "other",
                text,
                thread=target,
                sender="222" if same_thread else "333",
            )
        )
        await asyncio.wait_for(bot.tasks[target], 1)
        assert calls == (["gemini-3.5-flash-lite"] if semantic else []) + [
            "gemma-4-26b-a4b-it",
            "gemini-3.5-flash-lite",
        ]
        assert len(transport.sent) == 1 and transport.sent[0][0].thread == target
        assert transport.sent[0][0].id == "other"
        assert (THREAD in bot.pending) is not same_thread
        assert state.db.execute("SELECT count(*) FROM ai_calls").fetchone()[0] == (
            3 if semantic else 2
        )
        assert "[[NEED_SEARCH]]" not in str(state.history(target, 12, 3500))
        await bot.close()


@pytest.mark.asyncio
async def test_photo_retry_reuses_same_processed_image_and_never_calls_text_ai(make):
    vision = AI([ProviderUnavailable("Busy", 300), "Ảnh màu đỏ."])
    bot, state, text_ai, transport, clock, logs = make(image_ai=vision)
    waits = fast_forward(bot, clock)
    photo = ImageAttachment(url="https://scontent.fbcdn.net/picture?PRIVATE_TOKEN")
    bot.receive(incoming(clock, text="Ảnh gì đây?", images=(photo,)))
    await finish(bot)
    assert waits == [300] and len(transport.downloads) == 1
    assert len(vision.calls) == 2 and not text_ai.calls
    assert vision.calls[0][1][0] is vision.calls[1][1][0]
    assert len(transport.sent) == 1 and not bot.pending_images
    stored = str(state.db.execute("SELECT content FROM messages").fetchall())
    assert (
        "PRIVATE" not in stored + str(logs) and vision.calls[0][1][0].data not in stored
    )


@pytest.mark.asyncio
async def test_real_single_provider_with_multiple_models_recovers_without_using_disabled_sources(
    make, monkeypatch
):
    settings = Settings.from_dict(
        {
            "provider_enabled": {
                "google": True,
                "nvidia": False,
                "groq": False,
                "cloudflare": False,
            },
            "text_models": [
                "nvidia:google/gemma-4-31b-it",
                "google:gemini-3.5-flash-lite",
                "google:gemini-3.1-flash-lite",
                "groq:openai/gpt-oss-120b",
            ],
            "minimum_ai_interval_seconds": 0,
        }
    )
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "generativelanguage.googleapis.com"
        if len(requests) == 1:
            return httpx.Response(
                429, headers={"retry-after": "600"}, text="PRIVATE BODY"
            )
        if len(requests) == 2:
            return httpx.Response(
                503, headers={"retry-after": "3"}, text="PRIVATE BODY"
            )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "Đã trả lời."}]},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(
            module,
            "ChatAI",
            lambda *args, **kwargs: ChatAI(*args, client=client, **kwargs),
        )
        ai = create_ai({"google_api_key": "PRIVATE_KEY"}, settings, "PRIVATE PERSONA")
        bot, state, _, transport, clock, logs = make(ai)
        ai.clock = lambda: clock.now
        waits = fast_forward(bot, clock)
        bot.receive(incoming(clock))
        await finish(bot)
        await ai.close()
    assert waits == [3] and len(requests) == 3 and len(transport.sent) == 1
    assert "gemini-3.1-flash-lite" in requests[-1].url.path
    assert state.db.execute("SELECT count(*) FROM ai_calls").fetchone()[0] == 3
    assert "PRIVATE" not in str(logs)


@pytest.mark.asyncio
async def test_server_errors_keep_rotating_models_with_a_short_constant_round_pause(
    make, monkeypatch
):
    calls = []

    def handler(request):
        calls.append(request.url.path.rsplit("/", 1)[-1].split(":")[0])
        if len(calls) <= 8:
            return httpx.Response(503, text="PRIVATE_BODY")
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "Đã trả lời."}]},
                    }
                ]
            },
        )

    settings = Settings.from_dict(
        {
            "provider_enabled": {
                p: p == "google" for p in ("google", "nvidia", "groq", "cloudflare")
            },
            "text_models": [
                "google:gemini-3.5-flash-lite",
                "google:gemini-3.1-flash-lite",
            ],
            "minimum_ai_interval_seconds": 0,
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(
            module, "ChatAI", lambda *a, **kw: ChatAI(*a, **kw, client=client)
        )
        ai = create_ai({"google_api_key": "PRIVATE_KEY"}, settings, "Persona")
        bot, state, _, transport, clock, logs = make(ai, max_message_age_seconds=2)
        ai.clock = lambda: clock.now
        waits = fast_forward(bot, clock)
        bot.receive(incoming(clock))
        await finish(bot)
        assert calls == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"] * 4 + [
            "gemini-3.5-flash-lite"
        ]
        assert waits == [1] * 4
        assert len(transport.sent) == 1 and not bot.pending
        assert state.db.execute("SELECT count(*) FROM ai_calls").fetchone()[0] == 9
        assert state.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
        assert "PRIVATE" not in str(logs)
        await ai.close()


@pytest.mark.asyncio
async def test_local_daily_budget_waits_until_vietnam_midnight_without_extra_http(make):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "Đã trả lời."}}
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "KEY", Settings(minimum_ai_interval_seconds=0), "Persona", client=client
        )
        bot, state, _, transport, clock, _ = make(ai, max_ai_calls_per_day=1)
        old_day = datetime.fromtimestamp(clock.now, VIETNAM).date().isoformat()
        assert state.reserve_ai(old_day, 1)
        waits = []

        async def wait(thread, revision, delay):
            waits.append(delay)
            await bot._finish_typing(thread)
            if len(waits) == 1:
                clock.now += delay - 0.5
                bot.receive(incoming(clock, "new", "Câu mới ngay sau nửa đêm?"))
            else:
                clock.now += delay

        bot._wait_retry = wait
        bot.receive(incoming(clock))
        await finish(bot)
    assert len(requests) == len(transport.sent) == 1
    assert len(waits) == 2 and waits[-1] == pytest.approx(0.5)
    assert transport.sent[0][0].id == "new"
    assert datetime.fromtimestamp(clock.now, VIETNAM).date().isoformat() != old_day
    assert state.db.execute("SELECT count(*) FROM ai_calls").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_local_reply_cap_keeps_accepted_turn_for_the_next_day(make):
    bot, state, ai, transport, clock, _ = make(max_replies_per_thread_per_day=1)
    old_send = state.begin_send(THREAD, "Earlier", clock.now - 1)
    state.finish_send(old_send, "sent", "earlier")
    waits = fast_forward(bot, clock)
    bot.receive(incoming(clock))
    await finish(bot)
    assert len(waits) == len(ai.calls) == len(transport.sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [AIError("Invalid config"), ProviderUnavailable("Bad key", 600, retryable=False)],
)
async def test_invalid_configuration_does_not_enter_an_infinite_retry_loop(
    make, failure
):
    bot, _, ai, transport, clock, _ = make(AI([failure]))
    waits = fast_forward(bot, clock)
    bot.receive(incoming(clock))
    await finish(bot)
    assert len(ai.calls) == 1 and not waits and not transport.sent


@pytest.mark.asyncio
async def test_uncertain_messenger_send_is_never_retried_even_when_ai_retry_is_enabled(
    make,
):
    bot, state, ai, transport, clock, _ = make()
    attempts = []

    async def send(message, text):
        attempts.append((message, text))
        raise TimeoutError("Unknown delivery")

    transport.send = send
    waits = fast_forward(bot, clock)
    bot.receive(incoming(clock))
    await finish(bot)
    assert len(ai.calls) == len(attempts) == 1 and not waits
    assert state.db.execute("SELECT status FROM outbox").fetchone()[0] == "unknown"
    assert state.paused(THREAD, clock.now)


@pytest.mark.asyncio
async def test_retry_can_be_disabled_without_changing_provider_configuration(make):
    bot, _, ai, transport, clock, _ = make(
        AI([ProviderUnavailable("Busy", 60)]), ai_retry_enabled=False
    )
    waits = fast_forward(bot, clock)
    bot.receive(incoming(clock))
    await finish(bot)
    assert len(ai.calls) == 1 and not waits and not transport.sent


@pytest.mark.asyncio
async def test_an_old_draft_error_never_discards_a_new_message_received_during_the_request(
    make,
):
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingAI(AI):
        async def generate(self, history, reserve, **options):
            if not self.calls:
                entered.set()
                await release.wait()
            return await super().generate(history, reserve, **options)

    ai = WaitingAI([AIError("Old request failed"), "Trả lời tin mới."])
    bot, _, _, transport, clock, _ = make(ai)
    bot.receive(incoming(clock))
    await entered.wait()
    bot.receive(incoming(clock, "new", "Câu mới?"))
    release.set()
    await finish(bot)
    assert len(ai.calls) == 2 and len(transport.sent) == 1
    assert transport.sent[0][0].id == "new"


@pytest.mark.asyncio
async def test_all_models_with_invalid_access_do_not_become_a_retryable_pool(
    make, monkeypatch
):
    settings = Settings(
        google_models=("gemini-3.5-flash-lite", "gemini-3.1-flash-lite"),
        ai_provider="google",
        model="gemini-3.5-flash-lite",
        minimum_ai_interval_seconds=0,
    )
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(404)
        )
    ) as client:
        monkeypatch.setattr(
            module,
            "ChatAI",
            lambda *args, **kwargs: ChatAI(*args, client=client, **kwargs),
        )
        ai = create_ai({"google_api_key": "PRIVATE_KEY"}, settings, "Persona")
        bot, _, _, transport, clock, _ = make(ai)
        waits = fast_forward(bot, clock)
        bot.receive(incoming(clock))
        await finish(bot)
        await ai.close()
    assert len(requests) == 2 and not waits and not transport.sent


@pytest.mark.parametrize("bad", ["false", None, 0, []])
def test_retry_flag_requires_a_boolean(bad):
    with pytest.raises(ValueError, match="ai_retry_enabled"):
        Settings.from_dict({"ai_retry_enabled": bad})
