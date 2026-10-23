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
    prompt = captured[0]["messages"][0]
    assert prompt["role"] == "system"
    assert prompt["content"].startswith("Persona\n\nDÙNG NGỮ CẢNH\n")


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
        with pytest.raises(AIError, match="không phải thông báo hết quota"):
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


@pytest.mark.asyncio
async def test_cloudflare_contract_and_reasoning_hidden():
    from messenger_ai.ai import ChatAI

    settings = Settings(
        ai_provider="cloudflare",
        model="@cf/qwen/qwen3-30b-a3b-fp8",
        minimum_ai_interval_seconds=0,
    )

    def handler(request):
        assert (
            str(request.url)
            == "https://api.cloudflare.com/client/v4/accounts/"
            + "a" * 32
            + "/ai/v1/chat/completions"
        )
        assert request.headers["authorization"] == "Bearer cf-test-only"
        payload = json.loads(request.content)
        assert payload["model"] == settings.model
        assert payload["max_tokens"] == 4096
        assert "max_completion_tokens" not in payload
        assert "include_reasoning" not in payload
        assert "reasoning_effort" not in payload
        assert payload["messages"][0]["content"].endswith("/no_think")
        assert "cf-test-only" not in request.content.decode()
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": "<think>hidden</think>Chào bạn",
                            "reasoning_content": "hidden",
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "cf-test-only", settings, "Persona", account_id="a" * 32, client=client
        )
        assert (
            await ai.generate([{"role": "user", "content": "Hi"}], lambda: True)
            == "Chào bạn"
        )


@pytest.mark.asyncio
async def test_cloudflare_errors_do_not_fallback_or_leak_secrets():
    from messenger_ai.ai import ChatAI

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403, text="cf-secret-sensitive")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "cf-secret-sensitive",
            Settings(ai_provider="cloudflare", model="@cf/qwen/qwen3-30b-a3b-fp8"),
            "Persona",
            account_id="b" * 32,
            client=client,
        )
        with pytest.raises(AIError, match="Cloudflare") as error:
            await ai.generate([], lambda: True)
        assert "cf-secret-sensitive" not in str(error.value)
    assert len(calls) == 1 and calls[0].url.host == "api.cloudflare.com"


def test_configure_cloudflare_preserves_facebook_scope_and_history(
    tmp_path, monkeypatch
):
    from messenger_ai import cli
    from messenger_ai.config import load_secrets

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    for name in (
        "GROQ_API_KEY",
        "FACEBOOK_COOKIE",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    config = {
        "reply_scope": "all_private",
        "history_messages": 20,
        "output_char_limit": 4000,
    }
    secrets = {"facebook_cookie": "cookie-private", "groq_api_key": "groq-private"}
    (tmp_path / "config.json").write_text(json.dumps(config))
    (tmp_path / "secrets.json").write_text(json.dumps(secrets))
    monkeypatch.setattr("builtins.input", lambda _: "a" * 32)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "cf-private")
    cli.configure_ai("cloudflare", 1000)
    updated = json.loads((tmp_path / "config.json").read_text())
    assert updated == {
        **config,
        "ai_provider": "cloudflare",
        "model": "@cf/qwen/qwen3-30b-a3b-fp8",
        "max_ai_calls_per_day": 1000,
    }
    saved = load_secrets(tmp_path)
    assert saved == {
        **secrets,
        "google_api_key": "",
        "nvidia_api_key": "",
        "cloudflare_account_id": "a" * 32,
        "cloudflare_api_token": "cf-private",
    }
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "")
    cli.configure_ai("groq")
    assert load_secrets(tmp_path) == saved
    assert Settings.load(tmp_path).ai_provider == "groq"
    assert Settings.load(tmp_path).reply_scope == "all_private"


def test_invalid_cloudflare_setup_does_not_modify_files(tmp_path, monkeypatch):
    from messenger_ai import cli

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    for name in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / "config.json"
    secret = tmp_path / "secrets.json"
    config.write_text("{}")
    secret.write_text('{"facebook_cookie":"keep"}')
    monkeypatch.setattr("builtins.input", lambda _: "invalid/account")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "cf-private")
    with pytest.raises(ValueError, match="Account ID"):
        cli.configure_ai("cloudflare")
    assert config.read_text() == "{}"
    assert secret.read_text() == '{"facebook_cookie":"keep"}'


@pytest.mark.asyncio
async def test_factory_uses_only_selected_provider_credentials(monkeypatch):
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    from messenger_ai.ai import create_ai

    secrets = {
        "groq_api_key": "groq-private",
        "cloudflare_api_token": "cf-private",
        "cloudflare_account_id": "a" * 32,
    }
    for provider, model, key in (
        ("groq", "openai/gpt-oss-120b", "groq-private"),
        ("cloudflare", "@cf/qwen/qwen3-30b-a3b-fp8", "cf-private"),
    ):
        ai = create_ai(secrets, Settings(ai_provider=provider, model=model), "Persona")
        try:
            assert ai.api_key == key
            assert ai.provider == provider
        finally:
            await ai.close()


@pytest.mark.asyncio
async def test_failover_shares_context_budget_and_respects_cooldown():
    from messenger_ai.ai import ChatAI, FallbackAI

    now, calls, budget_calls = [1000], [], []

    def reserve():
        budget_calls.append(1)
        return True

    def handler(request):
        calls.append((request.url.host, json.loads(request.content)))
        if request.url.host == "api.cloudflare.com":
            return httpx.Response(429, headers={"retry-after": "3600"})
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]},
        )

    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "previous"},
        {"role": "user", "content": "next"},
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cf = ChatAI(
            "cf",
            Settings(
                ai_provider="cloudflare",
                model="@cf/qwen/qwen3-30b-a3b-fp8",
                minimum_ai_interval_seconds=0,
            ),
            "Persona",
            account_id="a" * 32,
            fail_fast=True,
            client=client,
        )
        groq = ChatAI(
            "groq",
            Settings(minimum_ai_interval_seconds=0),
            "Persona",
            fail_fast=True,
            client=client,
        )
        ai = FallbackAI(cf, groq, clock=lambda: now[0], log=lambda _: None)
        assert await ai.generate(history, reserve) == "OK"
        assert await ai.generate(history, reserve) == "OK"
        assert [host for host, _ in calls] == [
            "api.cloudflare.com",
            "api.groq.com",
            "api.groq.com",
        ]
        assert ai.blocked_until[0] == 4600
        assert all(payload["messages"][1:] == history for _, payload in calls)
        assert len(budget_calls) == 3
        now[0] = 4601
        assert await ai.generate(history, reserve) == "OK"
        assert [host for host, _ in calls][-2:] == [
            "api.cloudflare.com",
            "api.groq.com",
        ]
        await ai.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 400])
async def test_failover_does_not_hide_invalid_credentials_or_config(status):
    from messenger_ai.ai import ChatAI, FallbackAI

    calls = []

    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(status, text="secret-key")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        primary = ChatAI(
            "key",
            Settings(minimum_ai_interval_seconds=0),
            "Persona",
            fail_fast=True,
            client=client,
        )
        secondary = ChatAI(
            "cf",
            Settings(ai_provider="cloudflare", model="@cf/qwen/qwen3-30b-a3b-fp8"),
            "Persona",
            account_id="a" * 32,
            fail_fast=True,
            client=client,
        )
        ai = FallbackAI(primary, secondary)
        with pytest.raises(AIError) as error:
            await ai.generate([], lambda: True)
        assert "secret-key" not in str(error.value)
        assert calls == ["api.groq.com"]


@pytest.mark.asyncio
async def test_both_providers_down_skip_requests_until_cooldown():
    from messenger_ai.ai import FallbackAI, ProviderUnavailable

    class Down:
        label = "down"

        def __init__(self):
            self.calls = 0
            self.closed = False

        async def generate(self, history, reserve):
            self.calls += 1
            raise ProviderUnavailable("down", 60)

        async def close(self):
            self.closed = True

    primary, secondary = Down(), Down()
    ai = FallbackAI(primary, secondary, clock=lambda: 100, log=lambda _: None)
    for _ in range(2):
        with pytest.raises(AIError, match="Các nguồn"):
            await ai.generate([], lambda: True)
    assert primary.calls == secondary.calls == 1
    await ai.close()
    assert primary.closed and secondary.closed


@pytest.mark.asyncio
async def test_failover_cannot_bypass_local_daily_limit():
    from messenger_ai.ai import ChatAI, FallbackAI

    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: calls.append(request))
    ) as client:
        one = ChatAI(
            "key",
            Settings(minimum_ai_interval_seconds=0),
            "Persona",
            fail_fast=True,
            client=client,
        )
        ai = FallbackAI(one, one)
        with pytest.raises(AIError, match="giới hạn gọi AI"):
            await ai.generate([], lambda: False)
    assert calls == []


def test_fallback_requires_both_credentials_before_saving(tmp_path, monkeypatch):
    from messenger_ai import cli

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    for name in ("GROQ_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "config.json"
    path.write_text("{}")
    monkeypatch.setattr("builtins.input", lambda _: "a" * 32)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "cf-token")
    with pytest.raises(ValueError, match="Groq"):
        cli.configure_ai("cloudflare", fallback=True)
    assert path.read_text() == "{}"
    assert not (tmp_path / "secrets.json").exists()
    (tmp_path / "secrets.json").write_text('{"groq_api_key":"groq-token"}')
    cli.configure_ai("cloudflare", fallback=True)
    assert Settings.load(tmp_path).ai_fallback is True
    cli.configure_ai("cloudflare", fallback=False)
    assert Settings.load(tmp_path).ai_fallback is False


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [408, 503, "network"])
async def test_transient_provider_errors_allow_failover(failure):
    from messenger_ai.ai import ChatAI, ProviderUnavailable

    calls = []

    def handler(request):
        calls.append(request)
        if failure == "network":
            raise httpx.ConnectError("private response", request=request)
        return httpx.Response(failure, text="private response")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "key",
            Settings(minimum_ai_interval_seconds=0),
            "Persona",
            client=client,
            fail_fast=True,
        )
        with pytest.raises(ProviderUnavailable) as error:
            await ai.generate([], lambda: True)
        assert "private response" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,model",
    [("groq", "qwen/qwen3.8-27b"), ("cloudflare", "@cf/qwen/qwen3.8-27b")],
)
async def test_qwen38_request_contract(provider, model):
    from messenger_ai.ai import ChatAI

    def handler(request):
        payload = json.loads(request.content)
        assert payload["model"] == model
        assert payload["reasoning_effort"] == "low"
        assert payload["max_completion_tokens"] == 4096
        assert "max_tokens" not in payload
        assert "include_reasoning" not in payload
        assert "/no_think" not in payload["messages"][0]["content"]
        if provider == "groq":
            assert payload["reasoning_format"] == "hidden"
        else:
            assert "reasoning_format" not in payload
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": "Bạn định đi đâu?",
                            "reasoning_content": "hidden",
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "key",
            Settings(ai_provider=provider, model=model),
            "Persona",
            account_id="a" * 32,
            client=client,
        )
        assert (
            await ai.generate(
                [{"role": "user", "content": "tí đi choei k"}], lambda: True
            )
            == "Bạn định đi đâu?"
        )


@pytest.mark.parametrize(
    "provider,fallback,limit",
    [("groq", False, 60), ("cloudflare", True, 60), ("groq", True, 2000)],
)
def test_upgrade_chat_updates_models_limits_and_preserves_other_data(
    tmp_path, monkeypatch, provider, fallback, limit
):
    from messenger_ai import cli
    from messenger_ai.ai import CHAT_MODELS

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    raw = {
        "ai_provider": provider,
        "ai_fallback": fallback,
        "model": "old-model",
        "fallback_model": "old-backup",
        "reply_scope": "all_private",
        "history_messages": 20,
        "manual_pause_seconds": 300,
        "max_replies_per_thread_per_day": limit,
        "max_ai_calls_per_day": limit,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    secret = tmp_path / "secrets.json"
    secret.write_text("unchanged-secret")
    cli.upgrade_chat()
    updated = json.loads(path.read_text())
    expected = {
        **raw,
        "model": CHAT_MODELS[provider],
        "max_replies_per_thread_per_day": max(1000, limit),
        "max_ai_calls_per_day": max(1000, limit),
    }
    if fallback:
        expected["fallback_model"] = CHAT_MODELS[
            "groq" if provider == "cloudflare" else "cloudflare"
        ]
    assert updated == expected
    assert secret.read_text() == "unchanged-secret"
    cli.upgrade_chat()
    assert json.loads(path.read_text()) == expected
