import asyncio
import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from messenger_ai import ai as module, cli
from messenger_ai.ai import AIError, ChatAI, ProviderUnavailable
from messenger_ai.config import NVIDIA_DEFAULT_MODEL, Settings


def settings(**kw):
    return Settings(
        ai_provider="nvidia",
        model=NVIDIA_DEFAULT_MODEL,
        minimum_ai_interval_seconds=0,
        **kw,
    )


def response(text="Bạn định đi đâu, mấy giờ?"):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": text, "reasoning_content": "PRIVATE THOUGHT"},
            }
        ]
    }


@pytest.mark.asyncio
async def test_nvidia_payload_uses_fixed_endpoint_context_max_tokens_and_no_thinking():
    history = [
        {"role": "user", "content": "tí đi choei k"},
        {"role": "assistant", "content": "Bạn định đi đâu?"},
        {"role": "user", "content": "ra hồ"},
    ]

    def handler(request):
        assert (
            str(request.url) == "https://integrate.api.nvidia.com/v1/chat/completions"
        )
        assert request.headers["authorization"] == "Bearer test-nvidia-secret"
        payload = json.loads(request.content)
        assert payload["model"] == NVIDIA_DEFAULT_MODEL
        assert payload["messages"] == [
            {"role": "system", "content": "Persona"},
            *history,
        ]
        assert payload["max_tokens"] == 4096
        assert "max_completion_tokens" not in payload
        assert "reasoning_effort" not in payload
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        assert payload["stream"] is False
        return httpx.Response(200, json=response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI("test-nvidia-secret", settings(), "Persona", client=client)
        assert await ai.generate(history, lambda: True) == "Bạn định đi đâu, mấy giờ?"
        assert ai.last_used == "NVIDIA / google/gemma-4-31b-it"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 401, 403, 404, 410, 429, 500, 503])
async def test_nvidia_unavailable_does_not_retry_or_leak_response(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            json={"error": "private-response test-nvidia-secret"},
            headers={"retry-after": "120"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI("test-nvidia-secret", settings(), "Persona", client=client)
        with pytest.raises(ProviderUnavailable) as error:
            await ai.generate([], lambda: True)
        assert len(calls) == 1
        assert "private-response" not in str(error.value)
        assert "test-nvidia-secret" not in str(error.value)
        if status == 429:
            assert error.value.cooldown >= 120


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["length", "tool_calls", "content_filter", None])
async def test_nvidia_never_sends_partial_or_nonfinal_content(reason):
    data = response("unfinished")
    data["choices"][0]["finish_reason"] = reason
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))
    ) as client:
        ai = ChatAI("test-key", settings(), "Persona", client=client)
        with pytest.raises(AIError):
            await ai.generate([], lambda: True)


@pytest.mark.asyncio
async def test_nvidia_first_routes_to_google_with_same_context_and_shared_budget(
    monkeypatch,
):
    calls, reservations = [], []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "integrate.api.nvidia.com":
            return httpx.Response(429, headers={"retry-after": "90"})
        assert request.headers["x-goog-api-key"] == "google-key"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "Google answer"}]},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(
            module, "ChatAI", lambda *a, **kw: ChatAI(*a, **kw, client=client)
        )
        cfg = Settings(
            nvidia_model=NVIDIA_DEFAULT_MODEL,
            google_models=("gemma-4-31b-it",),
            ai_fallback=True,
            minimum_ai_interval_seconds=0,
        )
        ai = module.create_ai(
            {
                "nvidia_api_key": "nv-key",
                "google_api_key": "google-key",
                "groq_api_key": "groq",
                "cloudflare_api_token": "cf",
                "cloudflare_account_id": "a" * 32,
            },
            cfg,
            "Persona",
        )
        assert [c.provider for c in ai.clients] == [
            "nvidia",
            "google",
            "groq",
            "cloudflare",
        ]

        def reserve():
            reservations.append(True)
            return True

        assert (
            await ai.generate([{"role": "user", "content": "ra hồ"}], reserve)
            == "Google answer"
        )
        assert calls == [
            "integrate.api.nvidia.com",
            "generativelanguage.googleapis.com",
        ]
        assert len(reservations) == 2
        assert ai.last_used.startswith("Google /")


@pytest.mark.asyncio
async def test_nvidia_timeout_cancels_call_before_next_source(monkeypatch):
    monkeypatch.setattr(module, "NVIDIA_MODEL_TIMEOUT", 0.01)
    cancelled = asyncio.Event()

    async def handler(request):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        primary = ChatAI("test-key", settings(), "Persona", client=client)
        other = Mock(
            label="Groq",
            description="Groq",
            provider="groq",
            generate=AsyncMock(return_value="OK"),
        )
        ai = module.FallbackAI(primary, other)
        assert await ai.generate([], lambda: True) == "OK"
        assert cancelled.is_set()


@pytest.mark.asyncio
async def test_nvidia_cannot_bypass_daily_budget():
    handler = Mock(return_value=httpx.Response(200, json=response()))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI("test-key", settings(), "Persona", client=client)
        with pytest.raises(AIError, match="giới hạn gọi AI"):
            await ai.generate([], lambda: False)
    handler.assert_not_called()


def test_configure_nvidia_preserves_all_existing_sources_and_credentials(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    raw = {
        "reply_scope": "all_private",
        "google_models": ["gemma-4-31b-it"],
        "ai_fallback": True,
        "model": "qwen/qwen3.8-27b",
        "manual_pause_seconds": 300,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    secrets = tmp_path / "secrets.json"
    secrets.write_text(
        json.dumps(
            {
                "groq_api_key": "groq",
                "google_api_key": "google",
                "cloudflare_api_token": "cf",
                "cloudflare_account_id": "a" * 32,
                "facebook_cookie": "keep-cookie",
            }
        )
    )
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "nvidia-key")
    cli.configure_nvidia(NVIDIA_DEFAULT_MODEL)
    assert json.loads(path.read_text()) == {**raw, "nvidia_model": NVIDIA_DEFAULT_MODEL}
    saved = secrets.read_bytes()
    assert json.loads(saved)["facebook_cookie"] == "keep-cookie"
    assert json.loads(saved)["nvidia_api_key"] == "nvidia-key"
    assert secrets.stat().st_mode & 0o777 == 0o600
    cli.configure_nvidia(disable=True)
    assert json.loads(path.read_text()) == {**raw, "nvidia_model": ""}
    assert secrets.read_bytes() == saved


@pytest.mark.asyncio
async def test_strict_nvidia_check_never_creates_fallback_chain(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(
        Settings, "load", lambda: Settings(nvidia_model=NVIDIA_DEFAULT_MODEL)
    )
    monkeypatch.setattr(cli, "load_secrets", lambda: {"nvidia_api_key": "test-key"})
    (tmp_path / "persona.txt").write_text("Persona")
    (tmp_path / "persona.local.txt").write_text("Private persona")
    ai = Mock(
        last_used="NVIDIA / google/gemma-4-31b-it",
        generate=AsyncMock(return_value="OK"),
        close=AsyncMock(),
    )
    constructor = Mock(return_value=ai)
    monkeypatch.setattr(module, "ChatAI", constructor)
    factory = Mock()
    monkeypatch.setattr(module, "create_ai", factory)
    await cli.check_ai(provider="nvidia")
    factory.assert_not_called()
    assert constructor.call_args.args[2] == "Private persona"
    assert "Chỉ thử NVIDIA" in capsys.readouterr().out
    ai.close.assert_awaited_once()


@pytest.mark.parametrize(
    "model",
    [
        "unknown",
        ["google/gemma-4-31b-it"],
        None,
        "https://example.com/model",
        "google/gemma\n",
    ],
)
def test_bad_nvidia_models_cannot_enter_config(model):
    with pytest.raises(ValueError, match="nvidia_model"):
        Settings.from_dict({"nvidia_model": model})


@pytest.mark.asyncio
async def test_manually_selected_non_gemma_model_is_preserved_without_gemma_specific_options():
    model = "my-provider/my-chat-model-v2"

    def handler(request):
        payload = json.loads(request.content)
        assert payload["model"] == model
        assert "chat_template_kwargs" not in payload
        assert payload["max_tokens"] == 4096
        return httpx.Response(200, json=response("OK"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        config = Settings(
            ai_provider="nvidia", model=model, minimum_ai_interval_seconds=0
        )
        ai = ChatAI("test-key", config, "Persona", client=client)
        assert await ai.generate([], lambda: True) == "OK"
        assert ai.last_used == "NVIDIA / " + model


def test_manual_model_prompt_accepts_new_model_without_code_changes(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    (tmp_path / "config.json").write_text(json.dumps({"reply_scope": "all_private"}))
    (tmp_path / "secrets.json").write_text(json.dumps({"groq_api_key": "groq"}))
    monkeypatch.setattr("builtins.input", lambda _: "my-provider/new-chat-model")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "test-nvidia-key")
    cli.configure_nvidia()
    assert (
        json.loads((tmp_path / "config.json").read_text())["nvidia_model"]
        == "my-provider/new-chat-model"
    )


def test_missing_nvidia_key_never_saves_new_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    path = tmp_path / "config.json"
    before = json.dumps({"reply_scope": "all_private"})
    path.write_text(before)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "")
    with pytest.raises(ValueError, match="NVIDIA"):
        cli.configure_nvidia(NVIDIA_DEFAULT_MODEL)
    assert path.read_text() == before
    assert not (tmp_path / "secrets.json").exists()
