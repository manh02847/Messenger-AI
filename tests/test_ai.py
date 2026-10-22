import json

import httpx
import pytest

from messenger_ai.ai import AIError, GroqAI, final_text, retry_delay
from messenger_ai.config import Settings


@pytest.mark.asyncio
async def test_request_contract_and_only_final_answer():
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        assert request.url == "https://api.groq.com/openai/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": "Chào bạn",
                            "reasoning": "NEVER SEND THIS",
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = GroqAI(
            "test-private-key",
            Settings(minimum_ai_interval_seconds=0),
            "Persona",
            client=client,
        )
        text = await ai.generate([{"role": "user", "content": "Hi"}], lambda: True)
    assert text == "Chào bạn"
    assert captured[0]["include_reasoning"] is False
    assert captured[0]["reasoning_effort"] == "low"
    assert "reasoning_format" not in captured[0]
    assert captured[0]["messages"][0] == {"role": "system", "content": "Persona"}


@pytest.mark.asyncio
async def test_auth_error_does_not_leak_server_response_or_key():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(401, text="private-key-123")
        )
    ) as client:
        ai = GroqAI(
            "private-key-123",
            Settings(minimum_ai_interval_seconds=0),
            "Persona",
            client=client,
        )
        with pytest.raises(AIError) as error:
            await ai.generate([], lambda: True)
    assert "private-key-123" not in str(error.value)


@pytest.mark.asyncio
async def test_rate_limit_retry_consumes_local_budget(monkeypatch):
    waits, requests = [], []

    async def sleep(seconds):
        waits.append(seconds)

    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"retry-after": "1"})

    monkeypatch.setattr("messenger_ai.ai.asyncio.sleep", sleep)
    budget = iter((True, False))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = GroqAI(
            "test-key",
            Settings(minimum_ai_interval_seconds=0),
            "Persona",
            client=client,
        )
        with pytest.raises(AIError, match="giới hạn gọi AI"):
            await ai.generate([], lambda: next(budget))
    assert len(requests) == 1 and waits == [1]


@pytest.mark.asyncio
async def test_truncated_response_not_sent():
    payload = {
        "choices": [{"finish_reason": "length", "message": {"content": "Incomplete"}}]
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        ai = GroqAI(
            "test-key",
            Settings(minimum_ai_interval_seconds=0),
            "Persona",
            client=client,
        )
        with pytest.raises(AIError, match="hết token"):
            await ai.generate([], lambda: True)


def test_strip_explicit_thinking_and_reject_unclosed_tag():
    assert final_text("<think>private reasoning</think> Tin nhắn") == "Tin nhắn"
    with pytest.raises(AIError):
        final_text("<think>unfinished reasoning")
    with pytest.raises(AIError):
        final_text(None)


def test_excessive_retry_after_stops_instead_of_busy_loop():
    with pytest.raises(AIError, match="60 giây"):
        retry_delay("86400", 1)


@pytest.mark.parametrize(
    "raw",
    [
        {"allowed_threads": ["222"]},
        {"allowed_threads": ["*"]},
        {"dry_run": "false"},
        {"manual_pause_seconds": -1},
        {"history_messages": True},
    ],
)
def test_bad_config_rejected(raw):
    with pytest.raises(ValueError):
        Settings.from_dict(raw)
