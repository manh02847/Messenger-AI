import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from messenger_ai.ai import AIError, ChatAI, FallbackAI, google_cooldown, google_text
from messenger_ai.config import GOOGLE_DEFAULT_MODELS, Settings


def response(text="Chào bạn"):
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {"thought": True, "text": "PRIVATE THOUGHT"},
                        {"text": text},
                    ]
                },
            }
        ]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("model", (*GOOGLE_DEFAULT_MODELS, "gemma-4-31b-it"))
async def test_google_native_request_preserves_context_and_hides_thoughts(model):
    history = [
        {"role": "user", "content": "Hôm qua đi đâu?"},
        {"role": "assistant", "content": "Bạn đang hỏi Mạnh à?"},
        {"role": "user", "content": "ừ"},
    ]

    def handler(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path.endswith(f"/{model}:generateContent")
        assert not request.url.query
        assert request.headers["x-goog-api-key"] == "google-secret"
        assert "authorization" not in request.headers
        payload = json.loads(request.content)
        prompt = payload["systemInstruction"]["parts"]
        assert len(prompt) == 1
        assert prompt[0]["text"].startswith("Persona\n\nDÙNG NGỮ CẢNH\n")
        assert [v["role"] for v in payload["contents"]] == ["user", "model", "user"]
        assert [v["parts"][0]["text"] for v in payload["contents"]] == [
            v["content"] for v in history
        ]
        assert payload["generationConfig"]["maxOutputTokens"] == 4096
        assert payload["generationConfig"]["thinkingConfig"] == {
            "thinkingLevel": "minimal"
            if model.startswith("gemma-") or model == "gemini-3.6-flash"
            else "low",
            "includeThoughts": False,
        }
        assert "reasoning_effort" not in payload
        return httpx.Response(200, json=response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "google-secret",
            Settings(ai_provider="google", model=model),
            "Persona",
            client=client,
        )
        assert await ai.generate(history, lambda: True) == "Chào bạn"
        assert ai.last_used == f"Google / {model}"


@pytest.mark.parametrize(
    "data",
    [
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {"candidates": [{"finishReason": "MAX_TOKENS"}]},
        {"candidates": [{"finishReason": "SAFETY"}]},
        {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"thought": True, "text": "private"}]},
                }
            ]
        },
    ],
)
def test_google_does_not_send_blocked_truncated_or_thought_only_content(data):
    with pytest.raises(AIError):
        google_text(data)


@pytest.mark.asyncio
async def test_google_pool_falls_back_in_priority_order_and_shares_budget(monkeypatch):
    from messenger_ai import ai as module

    calls, reservations = [], []
    history = [{"role": "user", "content": "test"}]

    def handler(request):
        calls.append(request)
        if request.url.host == "generativelanguage.googleapis.com":
            assert request.headers["x-goog-api-key"] == "google"
            return httpx.Response(429, headers={"retry-after": "600"})
        assert request.headers["authorization"] == "Bearer groq"
        assert json.loads(request.content)["messages"][1:] == history
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(
            module,
            "ChatAI",
            lambda *args, **kwargs: ChatAI(*args, **kwargs, client=client),
        )
        ai = module.create_ai(
            {"google_api_key": "google", "groq_api_key": "groq"},
            Settings(
                google_models=GOOGLE_DEFAULT_MODELS, minimum_ai_interval_seconds=0
            ),
            "Persona",
        )
        assert isinstance(ai, FallbackAI)
        ai.log = lambda _: None
        ai.clock = lambda: 100

        def reserve():
            reservations.append(1)
            return True

        assert await ai.generate(history, reserve) == "OK"
        assert [v.url.path.split("/")[-1].split(":")[0] for v in calls[:-1]] == list(
            GOOGLE_DEFAULT_MODELS
        )
        assert ai.blocked_until[:-1] == [700] * len(GOOGLE_DEFAULT_MODELS)
        assert ai.last_used.startswith("Groq / ")
        assert len(reservations) == len(GOOGLE_DEFAULT_MODELS) + 1
        calls.clear()
        assert await ai.generate(history, reserve) == "OK"
        assert len(calls) == 1
        assert calls[0].url.host == "api.groq.com"
        await ai.close()


@pytest.mark.asyncio
async def test_google_next_model_success_stops_rotation():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(404, text="private error")
        return httpx.Response(200, json=response("OK"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        clients = [
            ChatAI(
                "key",
                Settings(
                    ai_provider="google", model=model, minimum_ai_interval_seconds=0
                ),
                "Persona",
                client=client,
                fail_fast=True,
            )
            for model in GOOGLE_DEFAULT_MODELS
        ]
        ai = FallbackAI(*clients, clock=lambda: 100, log=lambda _: None)
        assert (
            await ai.generate([{"role": "user", "content": "Hi"}], lambda: True) == "OK"
        )
        assert len(calls) == 2
        assert ai.blocked_until[0] == 3700
        assert ai.last_used.endswith(GOOGLE_DEFAULT_MODELS[1])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_google_invalid_auth_config_stops_without_exposing_secrets(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="private-key and cookie")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        one = ChatAI(
            "private-key",
            Settings(ai_provider="google", model=GOOGLE_DEFAULT_MODELS[0]),
            "Persona",
            client=client,
            fail_fast=True,
        )
        two = ChatAI("groq", Settings(), "Persona", client=client, fail_fast=True)
        with pytest.raises(AIError) as error:
            await FallbackAI(one, two).generate([], lambda: True)
        assert len(calls) == 1
        assert "private-key" not in str(error.value)


def test_google_daily_quota_and_structured_retry(monkeypatch):
    import messenger_ai.ai as module

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 22, 23, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

    monkeypatch.setattr(module, "datetime", Clock)
    daily = httpx.Response(
        429,
        json={
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
                            }
                        ],
                    }
                ]
            }
        },
    )
    assert google_cooldown(daily, 2) == 3605
    minute = httpx.Response(
        429,
        json={
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "901.5s",
                    }
                ]
            }
        },
    )
    assert google_cooldown(minute, 2) == 901.5
    assert google_cooldown(httpx.Response(429, text="bad json"), 300) == 300


@pytest.mark.parametrize(
    "models", ["gemma-4-31b-it", ["bad model"], [GOOGLE_DEFAULT_MODELS[0]] * 2, [{}]]
)
def test_google_models_validation(models):
    with pytest.raises(ValueError, match="google_models"):
        Settings.from_dict({"google_models": models})


def test_configure_google_preserves_other_settings_and_can_disable(
    tmp_path, monkeypatch
):
    from messenger_ai import cli
    from messenger_ai.config import load_secrets

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    for name in (
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "FACEBOOK_COOKIE",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    raw = {
        "ai_provider": "groq",
        "ai_fallback": True,
        "model": "qwen/qwen3.8-27b",
        "fallback_model": "@cf/qwen/qwen3.8-27b",
        "reply_scope": "all_private",
        "manual_pause_seconds": 300,
    }
    secrets = {
        "groq_api_key": "groq",
        "cloudflare_api_token": "cf",
        "cloudflare_account_id": "a" * 32,
        "facebook_cookie": "cookie",
    }
    config = tmp_path / "config.json"
    secret = tmp_path / "secrets.json"
    config.write_text(json.dumps(raw))
    secret.write_text(json.dumps(secrets))
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "google-key")
    cli.configure_google()
    settings = Settings.load(tmp_path)
    assert settings.text_targets == (
        *(("google", model) for model in GOOGLE_DEFAULT_MODELS),
        ("groq", "qwen/qwen3.8-27b"),
        ("cloudflare", "@cf/qwen/qwen3.8-27b"),
    )
    assert (
        settings.reply_scope == raw["reply_scope"]
        and settings.manual_pause_seconds == raw["manual_pause_seconds"]
    )
    before_targets = settings.all_text_targets
    assert load_secrets(tmp_path) == {
        **secrets,
        "google_api_key": "google-key",
        "nvidia_api_key": "",
    }
    assert secret.stat().st_mode & 0o777 == 0o600
    saved_secret = secret.read_bytes()
    cli.configure_google(disable=True)
    assert Settings.load(tmp_path).all_text_targets == before_targets
    assert not Settings.load(tmp_path).provider_flags["google"]
    assert secret.read_bytes() == saved_secret
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "")
    cli.configure_google([GOOGLE_DEFAULT_MODELS[0]])
    assert Settings.load(tmp_path).text_targets[0] == (
        "google",
        GOOGLE_DEFAULT_MODELS[0],
    )


def test_empty_google_key_does_not_change_files(tmp_path, monkeypatch):
    from messenger_ai import cli

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config = tmp_path / "config.json"
    config.write_text("{}")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "")
    with pytest.raises(ValueError, match="Google"):
        cli.configure_google()
    assert config.read_text() == "{}"
    assert not (tmp_path / "secrets.json").exists()


@pytest.mark.asyncio
async def test_google_pool_respects_local_budget(monkeypatch):
    from messenger_ai import ai as module

    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: calls.append(request))
    ) as client:
        monkeypatch.setattr(
            module,
            "ChatAI",
            lambda *args, **kwargs: ChatAI(*args, **kwargs, client=client),
        )
        ai = module.create_ai(
            {"google_api_key": "google", "groq_api_key": "groq"},
            Settings(google_models=GOOGLE_DEFAULT_MODELS),
            "Persona",
        )
        with pytest.raises(AIError, match="giới hạn gọi AI"):
            await ai.generate([], lambda: False)
        assert not calls
        await ai.close()
