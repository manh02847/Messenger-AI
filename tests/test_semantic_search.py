import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest

from messenger_ai import ai as module
from messenger_ai.ai import (
    AIBudgetExceeded,
    AIError,
    ChatAI,
    FallbackAI,
    ProviderUnavailable,
    VisionFallbackAI,
)
from messenger_ai.config import Settings
from messenger_ai.context import system_prompt
from messenger_ai.images import test_image as red_image
from messenger_ai.search_routing import SEARCH_REQUEST, can_request_search, needs_search

FLASH = "gemini-3.5-flash-lite"
SEARCHERS = ("gemma-4-31b-it", "gemma-4-26b-a4b-it")
MISSED = "Quán Phở Thìn ở Lò Đúc đóng cửa lúc nào?"


def history(text):
    return [{"role": "user", "content": text}]


def model(request):
    return request.url.path.rsplit("/", 1)[-1].split(":")[0]


def response(text="Câu trả lời đã xác minh.", *, grounded=False):
    candidate = {"finishReason": "STOP", "content": {"parts": [{"text": text}]}}
    if grounded:
        candidate["groundingMetadata"] = {
            "webSearchQueries": ["PUBLIC_QUERY"],
            "groundingChunks": [
                {"web": {"uri": "https://example.com/source", "title": "Source"}}
            ],
        }
    return httpx.Response(200, json={"candidates": [candidate]})


def pool(client, *, images=False, enabled=True, clock=None):
    base = Settings(ai_provider="google", minimum_ai_interval_seconds=0)
    clients = [
        ChatAI(
            "PRIVATE_KEY",
            replace(
                base,
                model=name,
                model_features={
                    f"google:{name}": {
                        "search": "auto" if enabled and name in SEARCHERS else "off"
                    }
                },
            ),
            "PRIVATE_PERSONA",
            client=client,
            fail_fast=True,
        )
        for name in (FLASH, *SEARCHERS)
    ]
    return (VisionFallbackAI if images else FallbackAI)(
        *clients, **({"clock": clock} if clock else {})
    )


@pytest.mark.parametrize(
    "text",
    [
        "bình ga 1 bình nhiêu ta",
        "binh ga 1 binh nhiu ta",
        "bình gas bao nhiêu tiền",
        "gas giờ bn",
        "vé xe bao nhiêu",
        "sim này bn",
        "gói cước nhiêu tiền",
        "tìm thử xem nào",
        "tìm xem giúp mình",
        "tra thử đi b",
    ],
)
def test_screenshot_price_and_search_requests_have_fast_local_routing(text):
    assert needs_search(history(text))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        MISSED,
        "Quán này mở cửa đến mấy giờ?",
        "Bệnh viện Bạch Mai nằm chỗ nào?",
        "Hạn chót nộp học bổng MEXT là lúc nào?",
        "Tàu Hà Nội Hải Phòng chạy lúc mấy giờ?",
        "Làm hộ chiếu online cần những giấy tờ nào?",
        "Lỗi này có trong bản Python 3.13.4 không?",
        "Viettel còn bán gói ST90K không?",
        "Trường Bách Khoa nhận hồ sơ tới khi nào?",
        "Bên FPT có cửa hàng nào ở Cầu Giấy?",
        "Chỗ đó còn nhận khách không?",
        "OpenRouter có cho dùng Claude miễn phí không?",
        "Có đợt tuyển sinh bổ sung ở NEU không?",
        "Lịch nghỉ Tết của trường đó công bố chưa?",
        "Thông tin trong bài này có đúng không?",
        "Tác giả bài báo này là ai?",
        "Shop này còn bán mẫu đó không?",
        "Giờ đóng cửa của bảo tàng đó?",
        "Khu ấy có bị cấm xe máy không?",
    ],
)
async def test_main_model_can_request_search_for_meanings_outside_keyword_rules(
    question,
):
    context = (
        history("Mình đang hỏi thông tin công khai.")
        + [{"role": "assistant", "content": "Bạn hỏi tiếp đi."}]
        + history(question)
    )
    original = deepcopy(context)
    assert not needs_search(context)
    calls, budget = [], []

    def handler(request):
        name = model(request)
        body = json.loads(request.content)
        calls.append(name)
        if name == FLASH:
            prompt = body["systemInstruction"]["parts"][0]["text"]
            assert (
                SEARCH_REQUEST in prompt
                and "không có công cụ tra cứu web" not in prompt
            )
            assert "tools" not in body
            return response(SEARCH_REQUEST)
        assert name == SEARCHERS[0] and body["tools"] == [{"googleSearch": {}}]
        assert len(body["contents"]) == 1
        assert question in body["contents"][0]["parts"][0]["text"]
        assert (
            "Dùng Google Search để xác minh"
            in body["systemInstruction"]["parts"][0]["text"]
        )
        return response(grounded=True)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = pool(client)
        answer = await ai.generate(context, lambda: budget.append(1) or True)
        assert calls == [FLASH, SEARCHERS[0]] and len(budget) == 2
        assert answer == "Câu trả lời đã xác minh." and "http" not in answer
        assert ai.last_search_used is True and ai.last_used.endswith(SEARCHERS[0])
        assert context == original


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "thế à",
        "ừ vậy hả",
        "ok",
        "Mạnh đang làm gì",
        "hôm nay bạn làm gì",
        "Không cần search nhé",
        "Tí đi chơi k",
        "Thế nay ngày gì?",
    ],
)
async def test_reaction_private_opt_out_and_clock_do_not_inherit_or_request_search(
    question,
):
    context = (
        history("Bình ga 1 bình nhiêu ta")
        + [{"role": "assistant", "content": "Đã kiểm tra."}]
        + history(question)
    )
    assert not needs_search(context) and not can_request_search(context)
    calls = []

    def handler(request):
        calls.append(model(request))
        prompt = json.loads(request.content)["systemInstruction"]["parts"][0]["text"]
        assert SEARCH_REQUEST not in prompt
        return response("Trả lời thường.")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await pool(client).generate(context, lambda: True) == "Trả lời thường."
    assert calls == [FLASH]


@pytest.mark.parametrize(
    "question",
    [
        "2 + 2 bằng mấy?",
        "Dịch câu này sang tiếng Anh",
        "Viết lời chúc sinh nhật",
        "Vì sao lá cây màu xanh?",
        "Chat hôm nay vui nhỉ",
    ],
)
@pytest.mark.asyncio
async def test_ordinary_answers_still_cost_one_request_without_a_classifier_call(
    question,
):
    calls = []

    def handler(request):
        calls.append(model(request))
        return response("Trả lời thường.")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert (
            await pool(client).generate(history(question), lambda: True)
            == "Trả lời thường."
        )
    assert calls == [FLASH]


@pytest.mark.asyncio
@pytest.mark.parametrize("images", [False, True])
async def test_semantic_search_retries_only_searchers_and_new_reaction_uses_flash(
    images,
):
    calls, moment, succeed = [], [100.0], [False]
    context = history(MISSED)
    image = red_image()
    options = {"images": [image]} if images else {}

    def handler(request):
        name, body = model(request), json.loads(request.content)
        calls.append(name)
        if images:
            assert body["contents"][-1]["parts"][-1]["inlineData"]["data"] == image.data
        if name == FLASH:
            return response(
                SEARCH_REQUEST
                if body["contents"][-1]["parts"][0]["text"] == MISSED
                else "Ừ."
            )
        return response(grounded=True) if succeed[0] else httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = pool(client, images=images, clock=lambda: moment[0])
        with pytest.raises(ProviderUnavailable) as error:
            await ai.generate(context, lambda: True, **options)
        assert error.value.cooldown == 1
        assert calls == [FLASH, *SEARCHERS]
        assert ai.route(context) == ((1, 2), True)
        with pytest.raises(ProviderUnavailable):
            await ai.generate(context, lambda: True, **options)
        assert calls == [FLASH, *SEARCHERS]
        assert (
            await ai.generate(context + history("thế à"), lambda: True, **options)
            == "Ừ."
        )
        assert calls[-1] == FLASH
        moment[0] += 1.1
        succeed[0] = True
        assert (
            await ai.generate(context, lambda: True, **options)
            == "Câu trả lời đã xác minh."
        )
        assert calls == [FLASH, *SEARCHERS, FLASH, SEARCHERS[0]]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["no_grounding", "marker"])
async def test_search_handoff_never_accepts_unverified_draft_or_loops_to_main_model(
    bad,
):
    calls = []

    def handler(request):
        name = model(request)
        calls.append(name)
        if name == FLASH or bad == "marker":
            return response(SEARCH_REQUEST)
        return response("Thông tin chưa xác minh.")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = pool(client)
        with pytest.raises(ProviderUnavailable):
            await ai.generate(history(MISSED), lambda: True)
        assert calls == [FLASH, *SEARCHERS]
        assert not ai.last_used and not ai.last_search_used


@pytest.mark.asyncio
async def test_search_disabled_never_advertises_handoff_or_silently_enables_tools():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(model(request))
        assert "tools" not in body
        assert SEARCH_REQUEST not in body["systemInstruction"]["parts"][0]["text"]
        return response("Mình chưa có thông tin đã kiểm tra.")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = pool(client, enabled=False)
        assert (
            await ai.generate(history(MISSED), lambda: True)
            == "Mình chưa có thông tin đã kiểm tra."
        )
        assert calls == [FLASH] and not ai._search_requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,main_model",
    [
        ("groq", "openai/gpt-oss-120b"),
        ("nvidia", "google/gemma-4-31b-it"),
        ("cloudflare", "@cf/qwen/qwen3.8-27b"),
    ],
)
async def test_openai_compatible_sources_can_request_google_search(
    provider, main_model
):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(request.url.host)
        if request.url.host != "generativelanguage.googleapis.com":
            assert SEARCH_REQUEST in body["messages"][0]["content"]
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": SEARCH_REQUEST},
                        }
                    ]
                },
            )
        return response(grounded=True)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        main = ChatAI(
            "PRIVATE_KEY",
            Settings(
                ai_provider=provider, model=main_model, minimum_ai_interval_seconds=0
            ),
            "Persona",
            client=client,
            account_id="a" * 32,
            fail_fast=True,
        )
        searcher = pool(client).clients[1]
        ai = FallbackAI(main, searcher)
        assert (
            await ai.generate(history(MISSED), lambda: True)
            == "Câu trả lời đã xác minh."
        )
        assert len(calls) == 2 and ai.last_search_used


@pytest.mark.asyncio
async def test_handoff_preserves_daily_budget_and_does_not_retry_fatal_search_errors():
    calls, budget = [], [0]

    def handler(request):
        calls.append(model(request))
        return (
            response(SEARCH_REQUEST) if model(request) == FLASH else httpx.Response(403)
        )

    def reserve():
        budget[0] += 1
        return budget[0] <= 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = pool(client)
        with pytest.raises(AIBudgetExceeded):
            await ai.generate(history(MISSED), reserve)
        assert calls == [FLASH]
        with pytest.raises(AIError, match="kiểm tra key/model/quyền"):
            await ai.generate(history(MISSED), lambda: True)
        assert calls == [FLASH, *SEARCHERS]
        with pytest.raises(AIError):
            await ai.generate(history(MISSED), lambda: True)
        assert calls == [FLASH, *SEARCHERS]


def test_semantic_route_cache_is_bounded_hashes_only_and_obeys_search_switches():
    # Client construction does not create a network connection.
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))):
        ai = FallbackAI(
            type("Stub", (), {"label": "main"})(),
            type("Stub", (), {"label": "search"})(),
        )
        for index in range(180):
            ai.remember_search(history(f"PRIVATE_MESSAGE_{index}"))
        assert len(ai._search_requests) == 128
        assert all(
            len(key) == 64 and "PRIVATE" not in key for key in ai._search_requests
        )
        assert ai.route(history("PRIVATE_MESSAGE_179")) == ((0, 1), False)


def test_clock_uses_vietnam_date_weekday_and_handles_utc_midnight_boundary():
    prompt = system_prompt(
        "Persona", now=datetime(2026, 10, 24, 18, 5, tzinfo=timezone.utc)
    )
    assert "Chủ nhật, 25/10/2026 01:05" in prompt
    assert "Asia/Ho_Chi_Minh (UTC+7)" in prompt
    assert "chủ tài khoản đang ở đâu" in prompt


@pytest.mark.asyncio
async def test_single_turn_slang_price_requires_real_search_and_keeps_explicitly_requested_links():
    calls = []
    question = "bình ga 1 bình nhiêu ta, cho xin link với"

    def handler(request):
        calls.append(model(request))
        body = json.loads(request.content)
        current = body["contents"][-1]["parts"][0]["text"]
        assert question in current and "hỏi giá bao nhiêu tiền" in current
        assert "dùng công cụ Google Search" in current
        return response(
            "Bạn xem tại https://example.com/requested-link.", grounded=True
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = pool(client)
        answer = await ai.generate(history(question), lambda: True)
        assert answer == "Bạn xem tại https://example.com/requested-link."
        assert calls == [SEARCHERS[0]] and ai.last_search_used


@pytest.mark.asyncio
async def test_remembered_handoff_cannot_override_models_switched_to_search_off():
    calls = []

    def handler(request):
        calls.append(model(request))
        body = json.loads(request.content)
        assert "tools" not in body
        assert SEARCH_REQUEST not in body["systemInstruction"]["parts"][0]["text"]
        return response("Trả lời theo cấu hình không tra cứu.")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = pool(client)
        context = history(MISSED)
        ai.remember_search(context)
        assert ai.route(context) == ((1, 2), True)
        for searcher in ai.clients[1:]:
            searcher.settings = replace(searcher.settings, model_features={})
        assert ai.route(context) == ((0, 1, 2), False)
        assert (
            await ai.generate(context, lambda: True)
            == "Trả lời theo cấu hình không tra cứu."
        )
        assert calls == [FLASH]


@pytest.mark.asyncio
async def test_handoff_shares_original_google_time_budget(monkeypatch):
    moment, calls, deadlines = [100.0], [], []
    original_timeout = asyncio.timeout

    def timeout(seconds):
        deadlines.append(seconds)
        return original_timeout(30)

    monkeypatch.setattr(module.asyncio, "timeout", timeout)

    def handler(request):
        calls.append(model(request))
        if model(request) == FLASH:
            moment[0] += 57
            return response(SEARCH_REQUEST)
        return response(grounded=True)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ai = pool(client, clock=lambda: moment[0])
        assert (
            await ai.generate(history(MISSED), lambda: True)
            == "Câu trả lời đã xác minh."
        )
        assert calls == [FLASH, SEARCHERS[0]]
        assert 3 in deadlines
