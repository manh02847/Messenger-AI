import asyncio
import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from messenger_ai import ai as module, cli, model_catalog
from messenger_ai.ai import AIError, ChatAI, create_ai, create_vision_ai
from messenger_ai.config import (
    GOOGLE_DEFAULT_MODELS,
    PROVIDER_KEYS,
    Settings,
    canonical_config,
    model_target,
    valid_google_model,
)
from messenger_ai.images import test_image as red_image


@pytest.fixture
def account(tmp_path, monkeypatch):
    raw = {
        "provider_enabled": {p: p == "google" for p in PROVIDER_KEYS},
        "text_models": [
            "google:gemini-3.5-flash-lite",
            "google:gemini-3.1-flash-lite",
            "nvidia:owner/keep-custom-text",
        ],
        "vision_models": ["google:gemini-3.5-flash-lite"],
        "history_messages": 19,
        "reply_scope": "all_private",
        "max_ai_calls_per_day": 1000,
        "minimum_ai_interval_seconds": 0,
    }
    secrets = {
        "google_api_key": "PRIVATE_GOOGLE_KEY",
        "facebook_cookie": "c_user=111; xs=PRIVATE;",
    }
    (tmp_path / "config.json").write_text(json.dumps(raw))
    (tmp_path / "secrets.json").write_text(json.dumps(secrets))
    (tmp_path / "persona.local.txt").write_text("PRIVATE PERSONA")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "state.sqlite3").write_bytes(b"PRIVATE HISTORY")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "load_secrets", lambda *_: dict(secrets))
    monkeypatch.setattr(
        cli.getpass, "getpass", Mock(side_effect=AssertionError("No key prompt"))
    )
    return tmp_path, raw, secrets


def test_manual_models_keep_key_cookie_persona_history_and_other_model_lists(account):
    root, raw, _ = account
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != "config.json"
    }
    selected = ["gemini-3.8-flash", "gemini-4-argon", "future-model-2027"]
    cli.configure_ai("google", models=selected, keep_key=True)
    saved = json.loads((root / "config.json").read_text())
    assert saved == {
        **raw,
        "text_models": [
            *(f"google:{model}" for model in selected),
            "nvidia:owner/keep-custom-text",
        ],
    }
    assert (root / "config.json").stat().st_mode & 0o777 == 0o600
    assert before == {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != "config.json"
    }


def test_new_presets_never_replace_an_existing_selection_implicitly(account):
    root, raw, _ = account
    assert GOOGLE_DEFAULT_MODELS == (
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    )
    cli.configure_ai("google", keep_key=True)
    assert json.loads((root / "config.json").read_text()) == raw


def test_keep_key_missing_credentials_does_not_prompt_or_write_partial_config(
    account, monkeypatch
):
    root, _, _ = account
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(cli, "load_secrets", lambda *_: {})
    with pytest.raises(ValueError, match="Google"):
        cli.configure_ai("google", models=["gemini-4-argon"], keep_key=True)
    assert before == {
        path: path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize(
    "model",
    [
        *GOOGLE_DEFAULT_MODELS,
        "gemini-3.1-pro-preview",
        "gemini-2.5-flash",
        "gemma-4-31b-it",
        "future-model-2027.01",
    ],
)
def test_google_custom_models_work_in_legacy_and_canonical_text_and_image_configs(
    model,
):
    raw = {
        "ai_provider": "google",
        "model": model,
        "google_models": [model],
        "vision_provider": "google",
        "vision_model": model,
    }
    legacy = Settings.from_dict(raw)
    modern = Settings.from_dict(canonical_config(raw))
    assert legacy.text_targets == modern.text_targets == (("google", model),)
    assert legacy.vision_targets == modern.vision_targets == (("google", model),)


@pytest.mark.parametrize(
    "model",
    [
        "",
        "Gemini 4 Argon",
        "models/gemini-4-argon",
        "https://example.com/model",
        "../model",
        "gemini-4-argon:generateContent",
        "gemini-4-argon?key=PRIVATE",
        "gemini-4-argon#fragment",
        "gemini-4-argon\nPRIVATE",
        "x" * 201,
        None,
        {},
    ],
)
def test_google_model_ids_cannot_inject_api_path_query_or_headers(model):
    assert not valid_google_model(model)
    with pytest.raises(ValueError):
        model_target(f"google:{model}" if isinstance(model, str) else model)
    with pytest.raises(ValueError):
        Settings.from_dict({"ai_provider": "google", "model": model})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model", (*GOOGLE_DEFAULT_MODELS, "gemini-2.5-flash", "future-model-2027")
)
@pytest.mark.parametrize("with_images", [False, True])
async def test_custom_models_use_native_google_payload_context_and_selected_model_only(
    model, with_images
):
    requests, reservations = [], []
    history = [
        {"role": "user", "content": "Nãy đang nói đến ảnh à?"},
        {"role": "assistant", "content": "Bạn gửi mình xem nhé."},
        {"role": "user", "content": "Ảnh này có màu gì?"},
    ]
    images = [red_image()] if with_images else None

    def handler(request):
        requests.append(request)
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path == f"/v1beta/models/{model}:generateContent"
        assert not request.url.query
        assert request.headers["x-goog-api-key"] == "PRIVATE_KEY"
        payload = json.loads(request.content)
        prompt = payload["systemInstruction"]["parts"][0]["text"]
        assert prompt.startswith("PRIVATE PERSONA\n\nDÙNG NGỮ CẢNH")
        assert [item["role"] for item in payload["contents"]] == [
            "user",
            "model",
            "user",
        ]
        assert [item["parts"][0]["text"] for item in payload["contents"]] == [
            item["content"] for item in history
        ]
        generation = payload["generationConfig"]
        if model in GOOGLE_DEFAULT_MODELS:
            assert generation["thinkingConfig"] == {
                "thinkingLevel": "low" if model == "gemini-3.8-flash" else "minimal",
                "includeThoughts": False,
            }
        elif model == "gemini-2.5-flash":
            assert generation["thinkingConfig"] == {
                "thinkingBudget": 0,
                "includeThoughts": False,
            }
        else:
            assert "thinkingConfig" not in generation
        if with_images:
            assert payload["contents"][-1]["parts"][1] == {
                "inlineData": {"mimeType": images[0].mime_type, "data": images[0].data}
            }
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "Màu đỏ."}]},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "PRIVATE_KEY",
            Settings(ai_provider="google", model=model, minimum_ai_interval_seconds=0),
            "PRIVATE PERSONA",
            client=client,
        )
        assert (
            await ai.generate(
                history, lambda: reservations.append(1) or True, images=images
            )
            == "Màu đỏ."
        )
        assert ai.last_used == f"Google / {model}"
    assert len(requests) == len(reservations) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("with_images", [False, True])
async def test_manual_new_model_order_controls_fallback_when_google_only(
    account, monkeypatch, with_images
):
    root, _, secrets = account
    selected = ["gemini-4-argon", "gemini-3.8-flash", "gemini-3.6-flash"]
    cli.configure_ai("google", models=selected, keep_key=True)
    cli.configure_vision(None, None, chain=[f"google:{model}" for model in selected])
    requests, budget = [], []

    def handler(request):
        requests.append(request)
        assert request.url.host == "generativelanguage.googleapis.com"
        if len(requests) < 3:
            return httpx.Response(429, headers={"Retry-After": "600"})
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": "OK"}]}}
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(
            module, "ChatAI", lambda *a, **kw: ChatAI(*a, **kw, client=client)
        )
        settings = Settings.load(root)
        ai = (create_vision_ai if with_images else create_ai)(
            secrets, settings, "Persona"
        )
        options = {"images": [red_image()]} if with_images else {}
        assert (
            await ai.generate(
                [{"role": "user", "content": "Chào"}],
                lambda: budget.append(1) or True,
                **options,
            )
            == "OK"
        )
        assert ai.last_used == "Google / gemini-3.6-flash"
        await ai.close()
    assert len(budget) == 3
    assert [
        request.url.path.rsplit("/", 1)[-1].split(":")[0] for request in requests
    ] == selected


def model_entry(model, methods=("generateContent",)):
    return {"name": f"models/{model}", "supportedGenerationMethods": list(methods)}


@pytest.mark.asyncio
async def test_catalog_paginates_filters_methods_and_never_selects_models():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert str(request.url.copy_with(query=None)) == model_catalog.MODELS_URL
        assert request.headers["x-goog-api-key"] == "PRIVATE_KEY"
        assert "PRIVATE_KEY" not in str(request.url)
        assert request.extensions["timeout"] == {
            "connect": 4,
            "read": 10,
            "write": 10,
            "pool": 10,
        }
        if len(requests) == 1:
            assert dict(request.url.params) == {"pageSize": "1000"}
            return httpx.Response(
                200,
                json={
                    "models": [
                        model_entry("gemini-4-argon"),
                        model_entry("embedding-only", ["embedContent"]),
                        model_entry("bad/model"),
                        {"name": "not-a-resource"},
                        None,
                    ],
                    "nextPageToken": "next-page",
                },
            )
        assert dict(request.url.params) == {
            "pageSize": "1000",
            "pageToken": "next-page",
        }
        return httpx.Response(
            200,
            json={
                "models": [
                    model_entry("gemini-4-argon"),
                    model_entry("gemini-3.8-flash"),
                    model_entry("future-model-2027"),
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await model_catalog.list_google_models("PRIVATE_KEY", client=client) == (
            "gemini-4-argon",
            "gemini-3.8-flash",
            "future-model-2027",
        )
        assert not client.is_closed
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "403",
        "429",
        "503",
        "redirect",
        "network",
        "bad-json",
        "wrong-type",
        "repeated-page",
    ],
)
async def test_catalog_errors_are_finite_redacted_and_never_follow_a_redirect(failure):
    requests = []

    def handler(request):
        requests.append(request)
        if failure in ("403", "429", "503"):
            return httpx.Response(int(failure), text="PRIVATE_SERVER_BODY")
        if failure == "redirect":
            return httpx.Response(
                302, headers={"location": "https://example.com/PRIVATE_KEY"}
            )
        if failure == "network":
            raise httpx.ConnectError("PRIVATE_KEY", request=request)
        if failure == "bad-json":
            return httpx.Response(200, text="PRIVATE_SERVER_BODY")
        if failure == "wrong-type":
            return httpx.Response(200, json={"models": "PRIVATE_SERVER_BODY"})
        return httpx.Response(200, json={"models": [], "nextPageToken": "same"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AIError) as error:
            await model_catalog.list_google_models("PRIVATE_KEY", client=client)
    assert "PRIVATE" not in str(error.value)
    assert len(requests) == (2 if failure == "repeated-page" else 1)
    assert all(
        request.url.host == "generativelanguage.googleapis.com" for request in requests
    )


@pytest.mark.asyncio
async def test_catalog_deadline_cancels_request_and_closes_owned_client(monkeypatch):
    entered, cancelled = [], []

    async def handler(request):
        entered.append(1)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(1)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(model_catalog.httpx, "AsyncClient", lambda: client)
    monkeypatch.setattr(model_catalog, "CATALOG_TIMEOUT", 0.01)
    with pytest.raises(AIError, match="timeout"):
        await model_catalog.list_google_models("PRIVATE_KEY")
    assert entered == cancelled == [1]
    assert client.is_closed


@pytest.mark.asyncio
async def test_list_models_is_read_only_without_persona_state_or_messenger(
    account, monkeypatch, capsys
):
    root, _, _ = account
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    fetch = AsyncMock(return_value=("gemini-4-argon", "future-model-2027"))
    monkeypatch.setattr(model_catalog, "list_google_models", fetch)
    await cli.list_models("google")
    fetch.assert_awaited_once_with("PRIVATE_GOOGLE_KEY")
    assert before == {
        path: path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    output = capsys.readouterr().out
    assert "future-model-2027" in output and "PRIVATE" not in output


@pytest.mark.parametrize("legacy_alias", [False, True])
def test_cli_accepts_manual_model_ids_with_no_parser_catalog_lock(
    monkeypatch, legacy_alias
):
    command = "configure-google" if legacy_alias else "configure-ai"
    selected = ["gemini-4-argon", "future-model-2027"]
    called = Mock()
    monkeypatch.setattr(
        cli, "configure_google" if legacy_alias else "configure_ai", called
    )
    args = ["messenger_ai", command]
    if not legacy_alias:
        args.extend(["google", "--keep-key"])
    monkeypatch.setattr("sys.argv", [*args, "--models", *selected])
    cli.main()
    if legacy_alias:
        called.assert_called_once_with(selected, disable=False, only=False)
    else:
        called.assert_called_once_with(
            "google", None, None, models=selected, keep_key=True
        )


def test_list_models_cli_dispatch(monkeypatch):
    called = AsyncMock()
    monkeypatch.setattr(cli, "list_models", called)
    monkeypatch.setattr("sys.argv", ["messenger_ai", "list-models", "google"])
    cli.main()
    called.assert_awaited_once_with("google")


@pytest.mark.parametrize(
    "entered,expected",
    [
        ("gemini-4-argon", ["gemini-4-argon"]),
        ("gemini-4-argon, gemini-3.8-flash", ["gemini-4-argon", "gemini-3.8-flash"]),
        (
            "gemini-3.8-flash gemini-4-argon gemini-3.6-flash",
            ["gemini-3.8-flash", "gemini-4-argon", "gemini-3.6-flash"],
        ),
        ("", ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]),
    ],
)
def test_short_configure_command_accepts_model_input_and_reuses_key_without_prompt(
    account, monkeypatch, entered, expected, capsys
):
    root, raw, _ = account
    before = {
        path: path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != "config.json"
    }
    prompts = []
    monkeypatch.setattr(
        "builtins.input", lambda prompt: prompts.append(prompt) or entered
    )
    monkeypatch.setattr("sys.argv", ["messenger_ai", "configure-ai", "google"])
    cli.main()
    saved = json.loads((root / "config.json").read_text())
    assert saved == {
        **raw,
        "text_models": [*(f"google:{m}" for m in expected), raw["text_models"][-1]],
    }
    assert len(prompts) == 1 and "Nhập mã model" in prompts[0]
    assert "PRIVATE" not in capsys.readouterr().out
    assert before == {path: path.read_bytes() for path in before}


def test_interactive_enter_preserves_an_interleaved_model_order(account, monkeypatch):
    root, raw, _ = account
    raw["text_models"].insert(1, raw["text_models"].pop())
    (root / "config.json").write_text(json.dumps(raw))
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr("sys.argv", ["messenger_ai", "configure-ai", "google"])
    cli.main()
    assert json.loads((root / "config.json").read_text()) == raw


@pytest.mark.parametrize("edit_existing_key", [False, True])
def test_interactive_key_prompt_only_when_missing_or_explicitly_requested(
    account, monkeypatch, edit_existing_key
):
    root, _, secrets = account
    if not edit_existing_key:
        secrets["google_api_key"] = ""
    key_prompt = Mock(return_value="PRIVATE_NEW_KEY")
    monkeypatch.setattr(cli.getpass, "getpass", key_prompt)
    monkeypatch.setattr("builtins.input", lambda _: "gemini-4-argon")
    monkeypatch.setattr(
        "sys.argv",
        [
            "messenger_ai",
            "configure-ai",
            "google",
            *(["--edit-key"] if edit_existing_key else []),
        ],
    )
    cli.main()
    key_prompt.assert_called_once()
    saved = json.loads((root / "secrets.json").read_text())
    assert saved == {**secrets, "google_api_key": "PRIVATE_NEW_KEY"}


@pytest.mark.parametrize(
    "entered",
    ["https://example.com/model", ",,,", "gemini-4-argon,gemini-4-argon", None],
)
def test_invalid_or_missing_interactive_input_never_writes_partial_configuration(
    account, monkeypatch, entered
):
    root, _, _ = account
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    def prompt(_):
        if entered is None:
            raise EOFError
        return entered

    monkeypatch.setattr("builtins.input", prompt)
    monkeypatch.setattr("sys.argv", ["messenger_ai", "configure-ai", "google"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert before == {
        path: path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("entered", ["gemini-4-argon,gemini-3.8-flash", ""])
def test_short_vision_command_accepts_bare_model_ids_and_keeps_text_and_keys(
    account, monkeypatch, entered
):
    root, raw, _ = account
    before = {
        path: path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != "config.json"
    }
    monkeypatch.setattr("builtins.input", lambda _: entered)
    monkeypatch.setattr("sys.argv", ["messenger_ai", "configure-vision", "google"])
    cli.main()
    expected = (
        ["google:gemini-4-argon", "google:gemini-3.8-flash"]
        if entered
        else raw["vision_models"]
    )
    assert json.loads((root / "config.json").read_text()) == {
        **raw,
        "vision_models": expected,
    }
    assert before == {path: path.read_bytes() for path in before}


def test_short_vision_command_offers_text_models_when_no_image_models_exist(
    account, monkeypatch
):
    root, raw, _ = account
    raw["vision_models"] = []
    (root / "config.json").write_text(json.dumps(raw))
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr("sys.argv", ["messenger_ai", "configure-vision", "google"])
    cli.main()
    assert Settings.load(root).vision_models == tuple(
        target for target in raw["text_models"] if target.startswith("google:")
    )


@pytest.mark.parametrize("has_account_id", [False, True])
def test_interactive_cloudflare_reuses_key_and_collects_account_id_only_if_missing(
    account, monkeypatch, has_account_id
):
    root, _, secrets = account
    secrets["cloudflare_api_token"] = "PRIVATE_CF_KEY"
    secrets["cloudflare_account_id"] = "a" * 32 if has_account_id else ""
    answers = iter(["@cf/owner/selected", *([] if has_account_id else ["a" * 32])])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    key_prompt = Mock(return_value="")
    if not has_account_id:
        monkeypatch.setattr(cli.getpass, "getpass", key_prompt)
    monkeypatch.setattr("sys.argv", ["messenger_ai", "configure-ai", "cloudflare"])
    cli.main()
    assert ("cloudflare", "@cf/owner/selected") in Settings.load(root).text_targets
    if has_account_id:
        key_prompt.assert_not_called()
    else:
        key_prompt.assert_called_once()
        assert json.loads((root / "secrets.json").read_text()) == {
            **secrets,
            "cloudflare_account_id": "a" * 32,
        }
