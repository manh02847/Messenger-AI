"""Protocol faults should rotate/retry; blocked or truncated output must stop."""

import json
from dataclasses import replace

import httpx
import pytest

from messenger_ai.ai import (
    AIError,
    ChatAI,
    FallbackAI,
    ProviderUnavailable,
    VisionFallbackAI,
)
from messenger_ai.config import Settings
from messenger_ai.images import test_image as red_image

HISTORY = [{"role": "user", "content": "Chào bạn"}]
PROVIDERS = [
    ("google", "gemini-3.5-flash-lite"),
    ("nvidia", "google/gemma-4-31b-it"),
    ("groq", "openai/gpt-oss-120b"),
    ("cloudflare", "@cf/qwen/qwen3.8-27b"),
]


def response(provider, content="OK", finish=None):
    if provider == "google":
        return {
            "candidates": [
                {
                    "finishReason": finish or "STOP",
                    "content": {"parts": [{"text": content}]},
                }
            ]
        }
    return {
        "choices": [
            {"finish_reason": finish or "stop", "message": {"content": content}}
        ]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", PROVIDERS)
@pytest.mark.parametrize(
    "fault",
    ["json", "schema", "empty", "thought_only", "open_thought", "missing_finish"],
)
async def test_corrupt_success_response_is_retryable_and_never_leaks_body(
    provider, model, fault
):
    data = response(provider)
    if fault == "schema":
        data = {"error": "PRIVATE_BODY"}
    elif fault in ("empty", "thought_only", "open_thought"):
        data = response(
            provider,
            {
                "empty": "",
                "thought_only": "<think>PRIVATE_BODY</think>",
                "open_thought": "<think>PRIVATE_BODY",
            }[fault],
        )
    elif fault == "missing_finish":
        data["candidates" if provider == "google" else "choices"][0].pop(
            "finishReason" if provider == "google" else "finish_reason"
        )
    wire = (
        httpx.Response(200, text="PRIVATE_BODY")
        if fault == "json"
        else httpx.Response(200, json=data)
    )
    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: calls.append(request) or wire)
    ) as client:
        ai = ChatAI(
            "PRIVATE_KEY",
            Settings(ai_provider=provider, model=model, minimum_ai_interval_seconds=0),
            "Persona",
            client=client,
            account_id="a" * 32,
            fail_fast=True,
        )
        with pytest.raises(ProviderUnavailable) as caught:
            await ai.generate(HISTORY, lambda: True)
    assert caught.value.retryable and caught.value.cooldown == 1
    assert "PRIVATE" not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("vision", [False, True])
@pytest.mark.parametrize(
    "reason",
    [
        "MALFORMED_RESPONSE",
        "MALFORMED_FUNCTION_CALL",
        "OTHER",
        "FINISH_REASON_UNSPECIFIED",
    ],
)
async def test_google_protocol_fault_rotates_same_history_and_images_immediately(
    vision, reason
):
    calls, budget = [], []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=response("google", "BROKEN_DRAFT", reason)
            if len(calls) == 1
            else response("google"),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        settings = Settings(
            ai_provider="google",
            model="gemini-3.5-flash-lite",
            minimum_ai_interval_seconds=0,
        )
        clients = [
            ChatAI(
                "KEY",
                replace(settings, model=model),
                "Persona",
                client=client,
                fail_fast=True,
            )
            for model in ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
        ]
        pool = (VisionFallbackAI if vision else FallbackAI)(
            *clients, log=lambda _: None
        )
        answer = await pool.generate(
            HISTORY,
            lambda: budget.append(1) or True,
            **({"images": [red_image()]} if vision else {}),
        )
        assert answer == "OK" and pool.last_used.endswith("gemini-3.1-flash-lite")
    assert len(calls) == len(budget) == 2
    assert calls[0]["contents"] == calls[1]["contents"]
    assert "inlineData" in calls[0]["contents"][-1]["parts"][-1] if vision else True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "SAFETY",
        "RECITATION",
        "PROHIBITED_CONTENT",
        "SPII",
        "ESCALATION",
        "MAX_TOKENS",
        "CONTINUATION",
        "MISSING_THOUGHT_SIGNATURE",
    ],
)
async def test_google_block_or_config_budget_failure_is_not_retried_or_rotated(reason):
    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: (
                calls.append(request)
                or httpx.Response(200, json=response("google", "DO_NOT_SEND", reason))
            )
        )
    ) as client:
        ai = ChatAI(
            "KEY",
            Settings(ai_provider="google", model="gemini-3.5-flash-lite"),
            "Persona",
            client=client,
        )
        with pytest.raises(AIError) as caught:
            await FallbackAI(ai, ai, log=lambda _: None).generate(HISTORY, lambda: True)
    assert not isinstance(caught.value, ProviderUnavailable)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", PROVIDERS[1:])
@pytest.mark.parametrize(
    "reason", ["content_filter", "tool_calls", "function_call", "length"]
)
async def test_non_google_rejects_all_nonfinal_output(provider, model, reason):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json=response(provider, "DO_NOT_SEND", reason)
            )
        )
    ) as client:
        ai = ChatAI(
            "KEY",
            Settings(ai_provider=provider, model=model),
            "Persona",
            account_id="a" * 32,
            client=client,
        )
        with pytest.raises(AIError):
            await ai.generate(HISTORY, lambda: True)
