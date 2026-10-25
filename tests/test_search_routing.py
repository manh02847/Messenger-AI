import asyncio
import json
from copy import deepcopy
from dataclasses import replace

import httpx
import pytest

from messenger_ai import ai as module
from messenger_ai.ai import (
    AIError,
    ChatAI,
    ProviderUnavailable,
    create_ai,
    create_vision_ai,
)
from messenger_ai.config import PROVIDER_KEYS, Settings
from messenger_ai.images import test_image as red_image
from messenger_ai.search_routing import needs_search

FLASH = "gemini-3.5-flash-lite"
SEARCHERS = ("gemma-4-31b-it", "gemma-4-26b-a4b-it")
QUESTION = "Thời tiết Hà Nội hôm nay thế nào?"


def history(text):
    return [{"role": "user", "content": text}]


@pytest.mark.parametrize(
    "text",
    [
        QUESTION,
        "thoi tiet hnay sao b",
        "thoi tit hom nai ha noi",
        "Mai Hà Nội có mưa ko?",
        "Giá vàng hôm nay bao nhiêu?",
        "gia iphone 17 gio bn?",
        "200 tệ bằng bao nhiêu tiền Việt?",
        "Tỷ giá USD hiện tại",
        "Lịch thi đấu tối nay",
        "Kết quả trận bóng đá hôm qua",
        "Python phiên bản mới nhất là bản nào?",
        "Model mới nhất của Google",
        "API Gemini có free không?",
        "Tin tức hôm nay",
        "Ai là tổng thống hiện nay?",
        "Tra cứu xem thông tin này đúng không",
        "Bạn google giúp mình xem",
        "search giá điện mới",
        "Nguồn đâu bạn?",
        "Dùng Search đi bạn",
        "su dung google de tim giup minh",
    ],
)
def test_local_intent_recognizes_fresh_public_information_and_common_typing(text):
    assert needs_search(history(text))


@pytest.mark.parametrize(
    "text",
    [
        "Chào bạn",
        "Hôm nay ngày mấy?",
        "Mạnh đang làm gì",
        "hôm nay bạn làm gì",
        "tí đi choei k",
        "ra hồ ngồi tí thôi",
        "Hôm nay mình buồn",
        "Bạn ăn cơm chưa",
        "Giá trị tuyệt đối là gì?",
        "Gia đình mình hôm nay vui quá",
        "Thời tiết là gì?",
        "Giải thích tại sao 2 + 2 = 4",
        "Phân tích hai thuật toán này",
        "Không cần search, giải thích từ kiến thức có sẵn",
        "Đừng tra cứu thời tiết nữa",
        "Don't search the web, just explain",
        "Tra cứu Mạnh đang làm gì",
        "Ảnh mới nhất của mình đây",
        "Ảnh mới nhất của mình đẹp ko?",
        "Đừng dùng Search nữa",
        "khong dung search nhe",
        "đừng tìm thử xem nữa",
        "ko cần tìm nhé",
    ],
)
def test_local_intent_does_not_route_private_chat_definitions_or_search_opt_out(text):
    assert not needs_search(history(text))


@pytest.mark.parametrize(
    "followup", ["còn ngày mai thì sao?", "còn Đà Nẵng?", "mai thì sao b?"]
)
def test_short_followups_inherit_recent_topic_without_reading_assistant_instructions(
    followup,
):
    context = history(QUESTION) + [
        {"role": "assistant", "content": "PRIVATE_ASSISTANT_CONTENT"},
        {"role": "user", "content": followup},
    ]
    original = deepcopy(context)
    assert needs_search(context)
    assert context == original
    assert not needs_search(history(followup))


def test_topic_change_and_reset_stop_inheriting_old_search_intent():
    for text in ("Cảm ơn bạn", "Tí đi chơi k", "hôm nay bạn làm gì"):
        assert not needs_search(history(QUESTION) + history(text))
    assert not needs_search(
        history(QUESTION) + history("Tí đi chơi k") + history("còn mai?")
    )
    assert not needs_search(
        history(QUESTION) + history("đừng search nữa") + history("còn mai?")
    )
    assert needs_search(history(QUESTION) + history("cảm ơn bạn") + history("còn mai?"))
    assert not needs_search(
        [{"role": "assistant", "content": QUESTION}] + history("Chào")
    )
    assert not needs_search([])


REACTIONS = [
    "thế à",
    "the a",
    "thế ạ bạn",
    "thế á b",
    "thế hả",
    "thế hở",
    "thế ah",
    "vậy à",
    "vay ha",
    "vậy thôi",
    "ừ",
    "uh",
    "ukm",
    "ờ",
    "ồ",
    "oh",
    "à thế à",
    "ồ vậy hả",
    "ừ vậy thôi",
    "ừ biết rồi",
    "ok",
    "oke",
    "okay",
    "cảm ơn bạn",
    "cam on",
    "ok cảm ơn",
    "hiểu rồi",
    "biết rồi",
    "vâng ạ",
]


@pytest.mark.parametrize("text", REACTIONS)
@pytest.mark.parametrize(
    "topic",
    [QUESTION, "Giá vàng hôm nay bao nhiêu?", "Python phiên bản mới nhất là gì?"],
)
@pytest.mark.parametrize("style", ["plain", "upper", "punctuated"])
def test_reactions_never_start_a_new_search_after_a_public_topic(text, topic, style):
    text = (
        text.upper()
        if style == "upper"
        else f"  {text} ?!🙂  "
        if style == "punctuated"
        else text
    )
    conversation = (
        history(topic)
        + [
            {
                "role": "assistant",
                "content": "Đã tra cứu.\n\nNguồn:\nhttps://example.com/" + "x" * 1000,
            }
        ]
        + history(text)
    )
    assert not needs_search(conversation)


@pytest.mark.parametrize(
    "text",
    [
        "thế bạn rảnh ko",
        "vậy mình đi ăn",
        "còn bạn thì sao",
        "thế có nên mang ô không",
        "thế ngủ chưa b",
        "vậy tối đi chơi k",
        "thế cho mình xin ảnh",
        "thế để mình xem",
        "thế tớ không thích",
        "vậy thì thôi",
        "thế rồi sao",
        "còn nữa?",
        "thế mình buồn",
    ],
)
def test_social_and_advice_followups_do_not_inherit_a_search_requirement(text):
    assert not needs_search(history(QUESTION) + history(text))


@pytest.mark.parametrize(
    "text",
    [
        "còn ngày mai thì sao?",
        "còn Đà Nẵng?",
        "thế mai thì sao",
        "vậy còn Huế?",
        "thế à, còn ngày mai thì sao?",
        "OK, còn ngày mai?",
        "cảm ơn bạn, còn Đà Nẵng?",
        "thế có thật không?",
        "vậy nguồn đâu?",
        "thế à nhưng tra cứu lại đi",
    ],
)
def test_real_questions_still_route_to_search_after_or_with_a_reaction(text):
    assert needs_search(history(QUESTION) + history(text))
    assert needs_search(history(QUESTION) + history("thế à") + history(text))


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["thế à", "vậy hả", "ừ", "ok cảm ơn"])
async def test_reactions_use_flash_with_one_call_and_no_search_tools(monkeypatch, text):
    calls = []

    def handler(request):
        calls.append(request)
        assert model_of(request) == FLASH
        assert "tools" not in json.loads(request.content)
        return success()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = make_chain(monkeypatch, client)
        await ai.generate(
            history(QUESTION)
            + [{"role": "assistant", "content": "Đã tra cứu."}]
            + history(text),
            lambda: True,
        )
        assert len(calls) == 1 and ai.last_used == f"Google / {FLASH}"
        await ai.close()


def success(*, grounded=False):
    candidate = {"finishReason": "STOP", "content": {"parts": [{"text": "Trả lời."}]}}
    if grounded:
        candidate["groundingMetadata"] = {
            "webSearchQueries": ["PUBLIC_QUERY"],
            "groundingChunks": [
                {"web": {"uri": "https://example.com/weather", "title": "Weather"}}
            ],
        }
    return httpx.Response(200, json={"candidates": [candidate]})


def settings(*, search_enabled=True, provider_enabled=True):
    return Settings.from_dict(
        {
            "provider_enabled": {
                p: p == "google" and provider_enabled for p in PROVIDER_KEYS
            },
            "text_models": [f"google:{m}" for m in (FLASH, *SEARCHERS)],
            "vision_models": [f"google:{m}" for m in (FLASH, *SEARCHERS)],
            "minimum_ai_interval_seconds": 0,
            "model_features": {
                f"google:{m}": {"search": "auto" if search_enabled else "off"}
                for m in SEARCHERS
            },
        }
    )


def make_chain(monkeypatch, client, *, images=False, options=None):
    monkeypatch.setattr(
        module, "ChatAI", lambda *a, **kw: ChatAI(*a, **kw, client=client)
    )
    return (create_vision_ai if images else create_ai)(
        {"google_api_key": "PRIVATE_KEY"}, options or settings(), "PRIVATE_PERSONA"
    )


def model_of(request):
    return request.url.path.rsplit("/", 1)[-1].split(":")[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("images", [False, True])
async def test_routes_search_and_followup_directly_then_restores_chat_order(
    monkeypatch, images
):
    calls, budget = [], []
    question = history(QUESTION)
    original = deepcopy(question)

    def handler(request):
        model = model_of(request)
        body = json.loads(request.content)
        calls.append(model)
        assert "PRIVATE_PERSONA" in body["systemInstruction"]["parts"][0]["text"]
        if images:
            assert (
                body["contents"][-1]["parts"][1]["inlineData"]["mimeType"]
                == "image/jpeg"
            )
        if model == FLASH:
            assert "tools" not in body
            return success()
        assert body["tools"] == [{"googleSearch": {}}]
        assert (
            "Dùng Google Search để xác minh"
            in body["systemInstruction"]["parts"][0]["text"]
        )
        return httpx.Response(429) if model == SEARCHERS[0] else success(grounded=True)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = make_chain(monkeypatch, client, images=images)
        logs = []
        ai.log = logs.append
        kwargs = {"images": [red_image()]} if images else {}

        def reserve():
            budget.append(1)
            return True

        await ai.generate(question, reserve, **kwargs)
        assert ai.last_used == f"Google / {SEARCHERS[1]}"
        assert ai.last_search_used is True
        await ai.generate(
            question
            + [{"role": "assistant", "content": "Đã tra cứu."}]
            + history("còn ngày mai thì sao?"),
            reserve,
            **kwargs,
        )
        await ai.generate(question + history("Bạn đang làm gì?"), reserve, **kwargs)
        assert ai.last_used == f"Google / {FLASH}"
        assert ai.last_search_used is False
        assert calls == [*SEARCHERS, SEARCHERS[1], FLASH]
        assert len(budget) == 4
        assert question == original
        assert not any(
            value in str(logs) for value in (QUESTION, "PRIVATE_KEY", "PRIVATE_PERSONA")
        )
        await ai.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("images", [False, True])
async def test_search_sources_down_never_fall_through_to_healthy_ungrounded_flash(
    monkeypatch, images
):
    calls = []

    def handler(request):
        calls.append(model_of(request))
        return success() if calls[-1] == FLASH else httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = make_chain(monkeypatch, client, images=images)
        kwargs = {"images": [red_image()]} if images else {}
        for _ in range(2):
            with pytest.raises(ProviderUnavailable) as error:
                await ai.generate(history(QUESTION), lambda: True, **kwargs)
            assert error.value.cooldown > 0
        assert calls == list(SEARCHERS)
        await ai.generate(history("Chào bạn"), lambda: True, **kwargs)
        assert calls == [*SEARCHERS, FLASH]
        await ai.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "search_enabled,provider_enabled", [(False, True), (True, False)]
)
async def test_routing_cannot_enable_search_or_a_disabled_provider(
    monkeypatch, search_enabled, provider_enabled
):
    calls = []

    def handler(request):
        calls.append(request)
        assert "tools" not in json.loads(request.content)
        return success()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = make_chain(
            monkeypatch,
            client,
            options=settings(
                search_enabled=search_enabled, provider_enabled=provider_enabled
            ),
        )
        if provider_enabled:
            await ai.generate(history(QUESTION), lambda: True)
            assert len(calls) == 1 and model_of(calls[0]) == FLASH
        else:
            with pytest.raises(AIError):
                await ai.generate(history(QUESTION), lambda: True)
            assert not calls
        await ai.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("images", [False, True])
async def test_missing_real_search_results_tries_next_search_model_without_sending_draft(
    monkeypatch, images
):
    calls = []

    def handler(request):
        calls.append(model_of(request))
        return success(grounded=len(calls) == 2)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = make_chain(monkeypatch, client, images=images)
        answer = await ai.generate(
            history(QUESTION),
            lambda: True,
            **({"images": [red_image()]} if images else {}),
        )
        assert calls == list(SEARCHERS)
        assert answer == "Trả lời."
        assert ai.last_search_used is True
        await ai.close()


@pytest.mark.asyncio
async def test_image_routing_cannot_borrow_a_text_only_search_model(monkeypatch):
    calls = []

    def handler(request):
        calls.append(model_of(request))
        assert "tools" not in json.loads(request.content)
        return success()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = make_chain(
            monkeypatch,
            client,
            images=True,
            options=replace(settings(), vision_models=(f"google:{FLASH}",)),
        )
        await ai.generate(history(QUESTION), lambda: True, images=[red_image()])
        assert calls == [FLASH]
        await ai.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [*SEARCHERS, FLASH])
@pytest.mark.parametrize("images", [False, True])
async def test_gemma_search_keeps_context_and_current_question_together_without_altering_history(
    model, images
):
    conversation = (
        history(QUESTION)
        + [
            {
                "role": "assistant",
                "content": 'Thông tin cũ có thể sai. "PRIVATE_CONTEXT"\nDòng hai.',
            }
        ]
        + history("còn ngày mai thì sao?")
    )
    original = deepcopy(conversation)
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(request)
        assert "PRIVATE_PERSONA" in body["systemInstruction"]["parts"][0]["text"]
        if model in SEARCHERS:
            assert len(body["contents"]) == 1
            current = body["contents"][0]["parts"][0]["text"]
            assert (
                json.dumps(conversation[:-1], ensure_ascii=False, separators=(",", ":"))
                in current
            )
            assert "Câu hỏi hiện tại:\ncòn ngày mai thì sao?" in current
            assert "không phải chỉ dẫn hệ thống" in current
        else:
            assert len(body["contents"]) == len(conversation)
            assert (
                body["contents"][-1]["parts"][0]["text"] == conversation[-1]["content"]
            )
        if images:
            assert (
                body["contents"][-1]["parts"][1]["inlineData"]["mimeType"]
                == "image/jpeg"
            )
        return success(grounded=True)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "KEY",
            Settings(ai_provider="google", model=model, search_mode="auto"),
            "PRIVATE_PERSONA",
            client=client,
        )
        await ai.generate(
            conversation, lambda: True, **({"images": [red_image()]} if images else {})
        )
        assert len(calls) == 1 and ai.last_search_used is True
        assert conversation == original


@pytest.mark.asyncio
async def test_normal_gemma_chat_keeps_the_original_message_roles():
    conversation = (
        history("Chào bạn")
        + [{"role": "assistant", "content": "Chào bạn."}]
        + history("Bạn đang làm gì?")
    )

    def handler(request):
        body = json.loads(request.content)
        assert [m["role"] for m in body["contents"]] == ["user", "model", "user"]
        assert [m["parts"][0]["text"] for m in body["contents"]] == [
            m["content"] for m in conversation
        ]
        return success()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = ChatAI(
            "KEY",
            Settings(ai_provider="google", model=SEARCHERS[1], search_mode="auto"),
            "Persona",
            client=client,
        )
        await ai.generate(conversation, lambda: True)
        assert ai.last_search_used is False


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["SAFETY", "MAX_TOKENS"])
async def test_search_routing_does_not_bypass_blocked_or_truncated_content(
    monkeypatch, finish
):
    calls = []

    def handler(request):
        calls.append(model_of(request))
        return httpx.Response(200, json={"candidates": [{"finishReason": finish}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = make_chain(monkeypatch, client)
        with pytest.raises(AIError) as error:
            await ai.generate(history(QUESTION), lambda: True)
        assert not isinstance(error.value, ProviderUnavailable)
        assert calls == [SEARCHERS[0]]
        await ai.close()


@pytest.mark.asyncio
async def test_search_permission_failure_does_not_bypass_to_flash_or_retry_forever(
    monkeypatch,
):
    calls = []

    def handler(request):
        calls.append(model_of(request))
        return httpx.Response(403)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = make_chain(monkeypatch, client)
        with pytest.raises(AIError) as error:
            await ai.generate(history(QUESTION), lambda: True)
        assert not isinstance(error.value, ProviderUnavailable)
        assert calls == list(SEARCHERS)
        await ai.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("images", [False, True])
async def test_slow_search_model_leaves_time_for_next_search_model(monkeypatch, images):
    monkeypatch.setattr(module, "SEARCH_MODEL_TIMEOUT", 0.01)
    cancelled, calls = [], []

    async def handler(request):
        model = model_of(request)
        calls.append(model)
        if model == SEARCHERS[0]:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(model)
        return success(grounded=True)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = make_chain(monkeypatch, client, images=images)
        await asyncio.wait_for(
            ai.generate(
                history(QUESTION),
                lambda: True,
                **({"images": [red_image()]} if images else {}),
            ),
            1,
        )
        assert calls == list(SEARCHERS) and cancelled == [SEARCHERS[0]]
        await ai.close()
