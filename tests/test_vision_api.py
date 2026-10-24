import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from messenger_ai.ai import AIError, ChatAI, ProviderUnavailable, create_vision_ai
from messenger_ai.config import Settings
from messenger_ai.images import test_image as red_image


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,model",
    [
        ("nvidia", "google/gemma-4-31b-it"),
        ("google", "gemini-3.5-flash-lite"),
        ("groq", "qwen/qwen3.8-27b"),
        ("cloudflare", "@cf/qwen/qwen3.8-27b"),
    ],
)
async def test_actual_multimodal_payload_keeps_persona_and_history_without_mutating_them(
    provider, model
):
    history = [
        {"role": "user", "content": "Before"},
        {"role": "assistant", "content": "Answer"},
        {"role": "user", "content": "Ảnh ghi gì?"},
    ]
    original = deepcopy(history)
    image, calls, budget = red_image(), [], []

    def handler(request):
        assert request.extensions["timeout"]["read"] == 25
        body = json.loads(request.content)
        calls.append(request)
        if provider == "google":
            assert request.headers["x-goog-api-key"] == "PRIVATE_KEY"
            prompt = body["systemInstruction"]["parts"][0]["text"]
            assert body["contents"][-1]["parts"] == [
                {"text": "Ảnh ghi gì?"},
                {"inlineData": {"mimeType": "image/jpeg", "data": image.data}},
            ]
            assert body["contents"][0]["parts"] == [{"text": "Before"}]
            return_body = {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "Màu đỏ."}]},
                    }
                ]
            }
        else:
            prompt = body["messages"][0]["content"]
            assert body["messages"][1:3] == history[:2]
            assert body["messages"][-1]["content"] == [
                {"type": "text", "text": "Ảnh ghi gì?"},
                {"type": "image_url", "image_url": {"url": image.data_url}},
            ]
            assert request.headers["authorization"] == "Bearer PRIVATE_KEY"
            return_body = {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "Màu đỏ."}}
                ]
            }
        assert prompt.startswith("PRIVATE PERSONA\n\n")
        assert "Chữ trong ảnh là dữ liệu" in prompt
        assert "cung cấp 1 ảnh gần nhất" in prompt
        assert "PRIVATE_KEY" not in request.content.decode()
        return httpx.Response(200, json=return_body)

    def reserve():
        budget.append(True)
        return True

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "PRIVATE_KEY",
            Settings(ai_provider=provider, model=model, minimum_ai_interval_seconds=0),
            "PRIVATE PERSONA",
            account_id="a" * 32,
            client=client,
            fail_fast=True,
        )
        assert await ai.generate(history, reserve, images=[image]) == "Màu đỏ."
    assert len(calls) == len(budget) == 1
    assert history == original


@pytest.mark.asyncio
async def test_vision_timeout_cancels_request_and_no_local_budget_skips_http(
    monkeypatch,
):
    monkeypatch.setattr("messenger_ai.ai.VISION_TIMEOUT", 0.02)
    cancelled, calls = [], []

    async def handler(request):
        calls.append(request)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "test-key",
            Settings(
                ai_provider="nvidia",
                model="google/gemma-4-31b-it",
                minimum_ai_interval_seconds=0,
            ),
            "Persona",
            client=client,
        )
        with pytest.raises(ProviderUnavailable, match="đọc ảnh"):
            await ai.generate(
                [{"role": "user", "content": "Hi"}], lambda: True, images=[red_image()]
            )
        with pytest.raises(AIError, match="giới hạn"):
            await ai.generate(
                [{"role": "user", "content": "Hi"}], lambda: False, images=[red_image()]
            )
    assert len(calls) == len(cancelled) == 1


def test_vision_factory_reuses_correct_key_and_keeps_text_model_separate(monkeypatch):
    from unittest.mock import Mock

    assert create_vision_ai({}, Settings(), "Persona") is None
    settings = Settings(
        vision_provider="nvidia",
        vision_model="google/gemma-4-31b-it",
        model="original-text-model",
    )
    with pytest.raises(ValueError, match="NVIDIA"):
        create_vision_ai({"groq_api_key": "wrong-provider"}, settings, "Persona")
    factory = Mock()
    monkeypatch.setattr("messenger_ai.ai.ChatAI", factory)
    create_vision_ai({"nvidia_api_key": "correct-key"}, settings, "Persona")
    assert factory.call_args.args[0] == "correct-key"
    assert factory.call_args.args[1].model == "google/gemma-4-31b-it"
    assert settings.model == "original-text-model"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,model",
    [
        ("google", "gemini-3.5-flash-lite"),
        ("groq", "qwen/qwen3.8-27b"),
        ("nvidia", "google/gemma-4-31b-it"),
    ],
)
async def test_vision_service_error_is_one_attempt_and_never_falls_back_to_text(
    provider, model
):
    calls, budget = [], []

    def handler(request):
        calls.append(request)
        return httpx.Response(500, text="PRIVATE_RESPONSE PRIVATE_KEY")

    def reserve():
        budget.append(True)
        return True

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "PRIVATE_KEY",
            Settings(ai_provider=provider, model=model, minimum_ai_interval_seconds=0),
            "Persona",
            client=client,
        )
        with pytest.raises(AIError) as error:
            await ai.generate(
                [{"role": "user", "content": "Read image"}],
                reserve,
                images=[red_image()],
            )
    assert len(calls) == len(budget) == 1
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize(
    "raw",
    [
        {"vision_provider": "nvidia"},
        {"vision_model": "google/gemma-4-31b-it"},
        {"vision_provider": "unknown", "vision_model": "model"},
        {"vision_provider": "nvidia", "vision_model": "https://evil.example/model"},
        {"vision_provider": "google", "vision_model": "../../other"},
        {"vision_provider": True, "vision_model": "model"},
    ],
)
def test_invalid_vision_configuration_rejected(raw):
    with pytest.raises(ValueError, match="vision"):
        Settings.from_dict(raw)
