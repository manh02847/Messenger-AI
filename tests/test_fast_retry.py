import asyncio
import time
from dataclasses import replace

import httpx
import pytest

from messenger_ai.ai import ChatAI, FallbackAI, ProviderUnavailable, transient_cooldown
from messenger_ai.config import Settings
from messenger_ai.grounding import with_sources


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,model",
    [
        ("google", "gemini-3.5-flash-lite"),
        ("nvidia", "google/gemma-4-31b-it"),
        ("groq", "openai/gpt-oss-120b"),
        ("cloudflare", "@cf/qwen/qwen3.8-27b"),
    ],
)
@pytest.mark.parametrize("status", [408, 429, 500, 503])
@pytest.mark.parametrize("hint", [None, "2", "120"])
async def test_fail_fast_rotates_after_one_request_and_honors_server_hints(
    provider, model, status, hint
):
    calls, budget = [], []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, headers={"retry-after": hint} if hint else {}, text="PRIVATE_BODY"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "PRIVATE_KEY",
            Settings(ai_provider=provider, model=model, minimum_ai_interval_seconds=0),
            "Persona",
            client=client,
            account_id="a" * 32,
            fail_fast=True,
        )
        with pytest.raises(ProviderUnavailable) as error:
            await ai.generate([], lambda: budget.append(1) or True)
        assert len(calls) == len(budget) == 1
        assert error.value.cooldown == (
            float(hint) if hint else 60 if status == 429 else 1
        )
        assert error.value.retryable is True
        assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("delay", ["1s", "2.5s", "90s"])
def test_google_structured_hint_is_not_replaced_by_an_unnecessary_fixed_pause(delay):
    response = httpx.Response(
        429,
        json={
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": delay,
                    }
                ]
            }
        },
    )
    assert transient_cooldown(response, google=True) == float(delay[:-1])


@pytest.mark.asyncio
async def test_failed_source_minimum_interval_does_not_delay_a_ready_source():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        assert "gemini-3.1-flash-lite" in request.url.path
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": "OK"}]}}
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        config = Settings(
            ai_provider="google",
            model="gemini-3.5-flash-lite",
            minimum_ai_interval_seconds=600,
        )
        one = ChatAI("KEY", config, "Persona", client=client, fail_fast=True)
        two = ChatAI(
            "KEY",
            replace(
                config, model="gemini-3.1-flash-lite", minimum_ai_interval_seconds=0
            ),
            "Persona",
            client=client,
            fail_fast=True,
        )
        pool = FallbackAI(one, two, log=lambda _: None)
        one._last_attempt = time.monotonic()
        pool.failures[0] = ProviderUnavailable("Temporary failure", 1)
        assert pool.wait_time(0) > 590
        assert await asyncio.wait_for(pool.generate([], lambda: True), 1) == "OK"
        assert len(calls) == 1
        await pool.close()


@pytest.mark.asyncio
async def test_all_models_wait_for_earliest_eligibility_not_the_sum_of_cooldowns():
    calls = []

    class Unavailable:
        label = "Test"

        def __init__(self, delay):
            self.delay = delay

        async def generate(self, history, reserve):
            calls.append(self.delay)
            raise ProviderUnavailable("Temporary failure", self.delay)

        async def close(self):
            pass

    pool = FallbackAI(
        *(Unavailable(delay) for delay in (7, 2, 5)),
        clock=lambda: 100,
        log=lambda _: None,
    )
    for _ in range(3):
        with pytest.raises(ProviderUnavailable) as error:
            await pool.generate([], lambda: True)
        assert error.value.cooldown == 2
    assert calls == [7, 2, 5]
    await pool.close()


@pytest.mark.parametrize(
    "queries,expected",
    [
        (None, False),
        ([], False),
        ("wrong type", False),
        ([None, 1, ""], False),
        (["valid query"], True),
    ],
)
def test_hidden_sources_still_validate_search_without_leaking_queries_html_or_redirects(
    queries, expected
):
    data = {
        "candidates": [
            {
                "groundingMetadata": {
                    "webSearchQueries": queries,
                    "searchEntryPoint": {
                        "renderedContent": '<a href="https://example.com/PRIVATE_TOKEN">PRIVATE_QUERY</a><script>PRIVATE_SCRIPT</script>'
                    },
                }
            }
        ]
    }
    answer, used, count = with_sources(
        data, "Thông tin trả lời.", 4000, include_sources=False
    )
    assert answer == "Thông tin trả lời." and used is expected and count == 0


def test_hidden_real_sources_preserve_detection_and_the_answer_character_budget():
    data = {
        "candidates": [
            {
                "groundingMetadata": {
                    "groundingChunks": [
                        {
                            "web": {
                                "uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/PRIVATE_TOKEN",
                                "title": "PRIVATE_TITLE",
                            }
                        }
                    ]
                }
            }
        ]
    }
    assert with_sources(data, "A" * 1000, 100, include_sources=False) == (
        "A" * 100,
        True,
        1,
    )
