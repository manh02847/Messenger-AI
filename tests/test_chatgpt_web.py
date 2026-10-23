import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from messenger_ai import cli
from messenger_ai.ai import AIError, FallbackAI, ProviderUnavailable, create_ai
from messenger_ai.chatgpt_web import ChatGPTWebAI, TEMPORARY_URL, web_prompt
from messenger_ai.config import Settings


def fake_browser():
    page = Mock()
    page.goto = AsyncMock()
    page.close = AsyncMock()
    editor = Mock(fill=AsyncMock())
    send = Mock(click=AsyncMock())
    profile = Mock(wait_for=AsyncMock())
    temporary = Mock(wait_for=AsyncMock())
    copy = Mock(wait_for=AsyncMock())
    stop = Mock(wait_for=AsyncMock())
    reply = Mock(
        count=AsyncMock(return_value=1),
        text_content=AsyncMock(return_value="Bạn định đi đâu?"),
    )
    for control in (editor, send, profile, temporary, copy, stop):
        control.filter.return_value = control
    controls = {
        "Gửi": send,
        "Tắt trò chuyện": temporary,
        "Sao chép": copy,
        "Ngừng": stop,
        "Mở menu": profile,
    }

    def role(kind, **kwargs):
        if kind == "textbox":
            return editor
        return next(v for k, v in controls.items() if k in kwargs["name"].pattern)

    page.get_by_role.side_effect = role
    page.locator.return_value = reply
    context = Mock(new_page=AsyncMock(return_value=page), close=AsyncMock())
    ai = ChatGPTWebAI(Settings(minimum_ai_interval_seconds=0), "Persona")
    ai._start = AsyncMock(return_value=context)
    return ai, page, controls, editor, reply


def test_prompt_bounds_history_and_separates_roles():
    settings = Settings(history_messages=3, history_char_limit=9)
    prompt = web_prompt(
        settings,
        "Persona",
        [
            {"role": "user", "content": "old thread data"},
            {"role": "assistant", "content": "12345678"},
            {"role": "user", "content": "abcde"},
        ],
    )
    history = json.loads(prompt.split("\n")[-1])
    assert history == [
        {"role": "assistant", "content": "5678"},
        {"role": "user", "content": "abcde"},
    ]
    assert "old thread data" not in prompt
    assert prompt.startswith("Persona\n")


@pytest.mark.asyncio
async def test_new_temporary_page_each_turn_waits_for_finished_reply_and_closes():
    ai, page, controls, editor, reply = fake_browser()
    reserve = Mock(return_value=True)
    history = [{"role": "user", "content": "tí đi choei k"}]
    for _ in range(2):
        assert await ai.generate(history, reserve) == "Bạn định đi đâu?"
    assert page.goto.await_count == 2
    page.goto.assert_awaited_with(TEMPORARY_URL, wait_until="domcontentloaded")
    assert page.close.await_count == 2
    assert reserve.call_count == 2
    controls["Ngừng"].wait_for.assert_awaited_with(state="hidden", timeout=25000)
    assert ai.last_used == ai.description
    assert "tí đi choei k" in editor.fill.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["Tắt trò chuyện", "Mở menu"])
async def test_never_sends_without_verified_temporary_mode_and_login(missing):
    ai, page, controls, _, _ = fake_browser()
    controls[missing].wait_for.side_effect = TimeoutError("private session details")
    reserve = Mock(return_value=True)
    with pytest.raises(ProviderUnavailable) as error:
        await ai.generate([{"role": "user", "content": "private message"}], reserve)
    assert "private" not in str(error.value)
    controls["Gửi"].click.assert_not_awaited()
    reserve.assert_not_called()
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_budget_denied_never_sends_or_falls_back():
    ai, page, controls, _, _ = fake_browser()
    fallback = Mock(
        label="Fallback", description="Fallback", provider="api", generate=AsyncMock()
    )
    chain = FallbackAI(ai, fallback)
    with pytest.raises(AIError, match="giới hạn"):
        await chain.generate([], lambda: False)
    controls["Gửi"].click.assert_not_awaited()
    fallback.generate.assert_not_awaited()
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_after_send_does_not_retry_or_return_partial_reply():
    ai, page, controls, _, reply = fake_browser()
    controls["Ngừng"].wait_for.side_effect = TimeoutError("stream incomplete")
    with pytest.raises(ProviderUnavailable):
        await ai.generate([], lambda: True)
    controls["Gửi"].click.assert_awaited_once()
    reply.text_content.assert_not_awaited()
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_closes_temporary_tab_without_swallowing_cancel():
    ai, page, controls, _, _ = fake_browser()
    controls["Sao chép"].wait_for.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await ai.generate([], lambda: True)
    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_web_unavailable_routes_same_context_to_existing_provider():
    ai, page, controls, _, _ = fake_browser()
    controls["Tắt trò chuyện"].wait_for.side_effect = TimeoutError
    secondary = Mock(
        label="API",
        description="API",
        provider="api",
        generate=AsyncMock(return_value="API answer"),
    )
    chain = FallbackAI(ai, secondary)
    history = [{"role": "user", "content": "hello"}]
    reserve = Mock(return_value=True)
    assert await chain.generate(history, reserve) == "API answer"
    secondary.generate.assert_awaited_once_with(history, reserve)
    assert chain.last_used == "API"
    assert chain.blocked_until[0] > chain.clock()


def test_factory_web_opt_in_and_preserves_google_cf_groq_order(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "messenger_ai.ai.ChatAI",
        lambda token, config, persona, **kw: SimpleNamespace(
            provider=config.ai_provider, label=config.ai_provider, close=AsyncMock()
        ),
    )
    settings = Settings(
        chatgpt_web=True, google_models=("gemma-4-31b-it",), ai_fallback=True
    )
    ai = create_ai(
        {
            "google_api_key": "google",
            "groq_api_key": "groq",
            "cloudflare_api_token": "cf",
            "cloudflare_account_id": "a" * 32,
        },
        settings,
        "Persona",
    )
    assert [c.provider for c in ai.clients] == [
        "chatgpt_web",
        "google",
        "groq",
        "cloudflare",
    ]
    asyncio.run(ai.close())


def test_configure_web_preserves_secrets_models_and_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    raw = {
        "reply_scope": "all_private",
        "google_models": ["gemma-4-31b-it"],
        "ai_fallback": True,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    secrets = tmp_path / "secrets.json"
    secrets.write_text("keep credentials untouched")
    cli.configure_chatgpt_web()
    assert json.loads(path.read_text()) == {**raw, "chatgpt_web": True}
    cli.configure_chatgpt_web(disable=True)
    assert json.loads(path.read_text()) == {**raw, "chatgpt_web": False}
    assert secrets.read_text() == "keep credentials untouched"
    with pytest.raises(ValueError):
        Settings.from_dict({"chatgpt_web": "true"})


@pytest.mark.asyncio
async def test_cli_web_check_is_strict_and_never_uses_api_fallback(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(Settings, "load", lambda: Settings())
    (tmp_path / "persona.txt").write_text("Persona")
    ai = Mock(
        last_used="ChatGPT web / chat tạm thời",
        close=AsyncMock(),
        generate=AsyncMock(return_value="hello"),
    )

    def generate(history, reserve):
        assert reserve() is True
        return "hello"

    ai.generate.side_effect = generate
    monkeypatch.setattr("messenger_ai.chatgpt_web.ChatGPTWebAI", lambda *a: ai)
    await cli.check_chatgpt_web()
    assert "Nguồn thực tế: ChatGPT web" in capsys.readouterr().out
    ai.close.assert_awaited_once()
