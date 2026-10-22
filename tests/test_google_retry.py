import asyncio

import httpx
import pytest

from messenger_ai import ai as module
from messenger_ai.ai import AIError, ChatAI, FallbackAI, ProviderUnavailable
from messenger_ai.config import GOOGLE_MODELS, Settings


def google_reply():
    return httpx.Response(
        200,
        json={
            "candidates": [
                {"finishReason": "STOP", "content": {"parts": [{"text": "OK"}]}}
            ]
        },
    )


def google(client):
    return ChatAI(
        "google-key",
        Settings(
            ai_provider="google", model=GOOGLE_MODELS[0], minimum_ai_interval_seconds=0
        ),
        "Persona",
        client=client,
        fail_fast=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 503])
async def test_google_quick_error_retries_once_with_same_context_and_budget(
    monkeypatch, status
):
    requests, waits, reserves = [], [], []

    async def sleep(seconds):
        waits.append(seconds)

    def handler(request):
        requests.append(request)
        assert request.extensions["timeout"]["read"] == 8
        assert request.extensions["timeout"]["connect"] == 4
        return httpx.Response(status) if len(requests) == 1 else google_reply()

    def reserve():
        reserves.append(1)
        return True

    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = google(client)
        assert await ai.generate([{"role": "user", "content": "Hi"}], reserve) == "OK"
    assert len(requests) == len(reserves) == 2
    assert requests[0].content == requests[1].content
    assert len(waits) == 1 and 1 <= waits[0] <= 1.5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind, cooldown",
    [("quota", 300), ("retry-after", 120), ("retry-info", 90), ("network", 30)],
)
async def test_google_does_not_retry_quota_long_hints_or_network_timeout(
    kind, cooldown
):
    requests = []

    def handler(request):
        requests.append(request)
        if kind == "network":
            raise httpx.ReadTimeout("private-key", request=request)
        if kind == "quota":
            return httpx.Response(429)
        if kind == "retry-after":
            return httpx.Response(500, headers={"Retry-After": "120"})
        return httpx.Response(
            503,
            json={
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "90s",
                        }
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderUnavailable) as error:
            await google(client).generate([], lambda: True)
    assert len(requests) == 1
    assert error.value.cooldown == cooldown
    assert "private-key" not in str(error.value)


@pytest.mark.asyncio
async def test_google_retries_at_most_once_then_moves_to_next_source(monkeypatch):
    calls, reserves = [], []

    async def sleep(_):
        pass

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(500)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "backup"}, "finish_reason": "stop"}]
            },
        )

    def reserve():
        reserves.append(1)
        return True

    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fallback = ChatAI(
            "groq",
            Settings(minimum_ai_interval_seconds=0),
            "Persona",
            client=client,
            fail_fast=True,
        )
        ai = FallbackAI(google(client), fallback, clock=lambda: 100, log=lambda _: None)
        assert await ai.generate([], reserve) == "backup"
        assert calls == ["generativelanguage.googleapis.com"] * 2 + ["api.groq.com"]
        assert len(reserves) == 3
        assert ai.blocked_until[0] == 120


@pytest.mark.asyncio
async def test_google_retry_respects_exhausted_local_budget(monkeypatch):
    calls = []
    budget = iter((True, False))

    async def sleep(_):
        pass

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AIError, match="giới hạn gọi AI"):
            await google(client).generate([], lambda: next(budget))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_google_slow_server_error_does_not_retry(monkeypatch):
    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ) as client:
        ai = google(client)

        def handler(request):
            calls.append(request)
            ai._last_attempt -= 3
            return httpx.Response(500)

        # Change only the mock transport; no wall-clock sleeps are needed.
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as slow_client:
            ai.client = slow_client
            with pytest.raises(ProviderUnavailable):
                await ai.generate([], lambda: True)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_google_model_total_deadline_cancels_inflight_request(monkeypatch):
    monkeypatch.setattr(module, "GOOGLE_MODEL_TIMEOUT", 0.02)
    entered, cancelled = [], []

    async def handler(request):
        entered.append(1)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(1)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderUnavailable, match="quá chậm") as error:
            await google(client).generate([], lambda: True)
    assert entered == cancelled == [1]
    assert error.value.cooldown == 30


@pytest.mark.asyncio
async def test_google_pool_budget_reaches_backup_and_skips_other_google_models(
    monkeypatch,
):
    monkeypatch.setattr(module, "GOOGLE_POOL_TIMEOUT", 0.02)
    calls, cancelled = [], []

    async def handler(request):
        calls.append(request.url.host)
        if request.url.host == "generativelanguage.googleapis.com":
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(1)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "backup"}, "finish_reason": "stop"}]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fallback = ChatAI(
            "groq",
            Settings(minimum_ai_interval_seconds=0),
            "Persona",
            client=client,
            fail_fast=True,
        )
        ai = FallbackAI(google(client), google(client), fallback, log=lambda _: None)
        assert await ai.generate([], lambda: True) == "backup"
    assert calls == ["generativelanguage.googleapis.com", "api.groq.com"]
    assert cancelled == [1]


@pytest.mark.asyncio
async def test_manual_cancellation_is_not_converted_to_retry(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request)
        raise asyncio.CancelledError

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = FallbackAI(google(client), google(client), log=lambda _: None)
        with pytest.raises(asyncio.CancelledError):
            await ai.generate([], lambda: True)
    assert len(calls) == 1
