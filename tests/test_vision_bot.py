import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest
import httpx

from messenger_ai.config import Settings
from messenger_ai.core import Message, ReplyBot
from messenger_ai.images import IMAGE_FAILURE, ImageAttachment, ImageError, ImageInput
from messenger_ai.state import State

THREAD = "e2ee:222@msgr"
NOW = 1800000000


class TextAI:
    def __init__(self):
        self.calls = []

    async def generate(self, history, reserve):
        assert reserve()
        self.calls.append(deepcopy(history))
        return "Text reply"


class VisionAI(TextAI):
    last_used = "Test vision model"

    async def generate(self, history, reserve, *, images):
        assert reserve()
        self.calls.append((deepcopy(history), list(images)))
        return "Image reply"


class Transport:
    def __init__(self):
        self.downloads, self.sent, self.typing = [], [], []

    async def load_image(self, image, *, encrypted):
        self.downloads.append((image, encrypted))
        return ImageInput("processed-" + image.url.rsplit("/", 1)[-1])

    async def send(self, message, text):
        self.sent.append((message, text))
        return {"messageId": f"reply-{len(self.sent)}"}

    async def set_typing(self, message, active):
        self.typing.append(active)


def incoming(mid="photo-1", *, text="", photo=True, sender="222", thread=THREAD):
    return Message(
        thread,
        mid,
        sender,
        text,
        NOW,
        "222@msgr",
        "222:1@msgr",
        is_private=True,
        images=(
            ImageAttachment(
                url=f"https://scontent.xx.fbcdn.net/{mid}?PRIVATE_CDN_TOKEN"
            ),
        )
        if photo
        else (),
    )


def make_bot(tmp_path, *, enabled=True, vision=None, **options):
    settings = Settings(
        allowed_threads=(THREAD,),
        dry_run=False,
        debounce_seconds=0,
        reply_cooldown_seconds=0,
        minimum_ai_interval_seconds=0,
        ai_retry_enabled=False,
    )
    state, text_ai, transport = State(tmp_path / "state.sqlite3"), TextAI(), Transport()
    vision = vision or VisionAI()
    logs = []
    bot = ReplyBot(
        replace(settings, **options),
        state,
        text_ai,
        transport,
        "111",
        clock=lambda: NOW,
        log=logs.append,
        image_ai=vision if enabled else None,
    )
    return bot, state, text_ai, vision, transport, logs


async def finish(bot, state):
    await bot.close()
    state.close()


@pytest.mark.asyncio
async def test_photo_only_uses_vision_once_and_never_stores_image_bytes_or_keys(
    tmp_path,
):
    bot, state, text, vision, transport, logs = make_bot(tmp_path)
    message = incoming()
    bot.receive(message)
    bot.receive(message)
    await asyncio.gather(*bot.tasks.values())
    assert (
        not text.calls
        and len(vision.calls) == len(transport.sent) == len(transport.downloads) == 1
    )
    assert "gửi ảnh" in vision.calls[0][0][-1]["content"]
    assert transport.downloads[0][1] is True
    stored = str(state.db.execute("SELECT content FROM messages").fetchall())
    assert "PRIVATE_CDN_TOKEN" not in stored and "processed-" not in stored
    assert "PRIVATE_CDN_TOKEN" not in " ".join(logs)
    assert not bot.pending_images
    await finish(bot, state)


@pytest.mark.asyncio
@pytest.mark.parametrize("all_failed", [False, True])
async def test_real_vision_fallback_downloads_once_counts_both_attempts_and_sends_at_most_one_reply(
    tmp_path, all_failed
):
    from messenger_ai.ai import ChatAI, VisionFallbackAI

    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1 or all_failed:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "Image reply"}}
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        clients = [
            ChatAI(
                "PRIVATE_KEY",
                Settings(ai_provider=p, model=m, minimum_ai_interval_seconds=0),
                "PRIVATE PERSONA",
                client=client,
            )
            for p, m in (
                ("google", "gemini-3.5-flash-lite"),
                ("groq", "qwen/qwen3.8-27b"),
            )
        ]
        vision = VisionFallbackAI(*clients, log=lambda _: None)
        bot, state, text, _, transport, logs = make_bot(tmp_path, vision=vision)
        bot.receive(incoming(text="Ảnh gì đây?"))
        await asyncio.gather(*bot.tasks.values())
        assert len(requests) == 2 and len(transport.downloads) == 1
        assert len(transport.sent) == (0 if all_failed else 1)
        assert not text.calls and not bot.pending_images
        assert state.db.execute("SELECT count(*) FROM ai_calls").fetchone()[0] == 2
        assert "PRIVATE" not in " ".join(logs)
        if not all_failed:
            assert transport.sent[0][1] == "Image reply"
            assert any("Groq / qwen/qwen3.8-27b" in line for line in logs)
        await finish(bot, state)
        await vision.close()


@pytest.mark.asyncio
async def test_photo_then_question_in_burst_are_one_vision_turn_and_later_text_stays_text(
    tmp_path,
):
    bot, state, text, vision, transport, _ = make_bot(tmp_path)
    bot.receive(incoming())
    bot.receive(incoming("question", text="Chữ trong ảnh là gì?", photo=False))
    await asyncio.gather(*bot.tasks.values())
    assert len(vision.calls) == len(transport.sent) == 1 and not text.calls
    assert vision.calls[0][0][-1]["content"] == "Chữ trong ảnh là gì?"
    bot.receive(incoming("later", text="Cảm ơn", photo=False))
    await asyncio.gather(*bot.tasks.values())
    assert len(vision.calls) == len(transport.downloads) == 1
    assert len(text.calls) == 1
    assert any(item["content"] == "Image reply" for item in text.calls[0])
    await finish(bot, state)


@pytest.mark.asyncio
async def test_only_two_most_recent_images_are_loaded_per_burst(tmp_path):
    bot, state, _, vision, transport, _ = make_bot(tmp_path)
    for mid in ("one", "two", "three"):
        bot.receive(incoming(mid))
    await asyncio.gather(*bot.tasks.values())
    assert [
        item.url.rsplit("/", 1)[-1].split("?")[0] for item, _ in transport.downloads
    ] == ["two", "three"]
    assert len(vision.calls[0][1]) == 2
    await finish(bot, state)


@pytest.mark.asyncio
async def test_disabled_vision_ignores_photo_only_and_marks_caption_photo_unavailable(
    tmp_path,
):
    bot, state, text, vision, transport, _ = make_bot(tmp_path, enabled=False)
    bot.receive(incoming())
    assert not bot.tasks and not state.history(THREAD, 12, 3500)
    bot.receive(incoming("caption", text="Nhận xét ảnh nhé"))
    await asyncio.gather(*bot.tasks.values())
    assert not vision.calls and not transport.downloads
    assert "chưa bật" in text.calls[0][-1]["content"]
    await finish(bot, state)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["group", "unlisted", "paused", "old", "daily_send_limit"]
)
async def test_existing_filters_apply_before_any_image_download_or_ai_call(
    tmp_path, reason
):
    bot, state, text, vision, transport, _ = make_bot(
        tmp_path,
        reply_scope="all_private" if reason == "group" else "allowlist",
        max_replies_per_thread_per_day=1,
    )
    message = incoming()
    if reason == "group":
        message = replace(message, is_private=False)
    elif reason == "unlisted":
        message = replace(message, thread="thread:999")
    elif reason == "paused":
        state.pause(THREAD, NOW + 300)
    elif reason == "old":
        message = replace(message, timestamp=NOW - 600)
    else:
        state.begin_send(THREAD, "Earlier reply", NOW)
    bot.receive(message)
    if bot.tasks:
        await asyncio.gather(*bot.tasks.values())
    assert (
        not transport.downloads
        and not transport.sent
        and not vision.calls
        and not text.calls
    )
    await finish(bot, state)


@pytest.mark.asyncio
async def test_download_error_sends_honest_failure_and_does_not_guess_with_text_ai(
    tmp_path,
):
    bot, state, text, vision, transport, logs = make_bot(tmp_path)

    async def fail(*args, **kwargs):
        raise ImageError("E2EE_NOT_READY")

    transport.load_image = fail
    bot.receive(incoming())
    await asyncio.gather(*bot.tasks.values())
    assert transport.sent[0][1] == IMAGE_FAILURE
    assert not vision.calls and not text.calls
    assert state.db.execute("SELECT count(*) FROM ai_calls").fetchone()[0] == 0
    assert any("E2EE_NOT_READY" in log for log in logs)
    await finish(bot, state)


@pytest.mark.asyncio
async def test_manual_reply_during_download_prevents_image_ai_and_send(tmp_path):
    bot, state, _, vision, transport, _ = make_bot(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()

    async def load(*args, **kwargs):
        entered.set()
        await release.wait()
        return ImageInput("image")

    transport.load_image = load
    bot.receive(incoming())
    await entered.wait()
    bot.receive(incoming("manual", text="Mình tự trả lời", photo=False, sender="111"))
    release.set()
    await asyncio.gather(*bot.tasks.values())
    assert not vision.calls and not transport.sent and not bot.pending_images
    assert state.paused(THREAD, NOW) and transport.typing[-1] is False
    await finish(bot, state)


@pytest.mark.asyncio
async def test_new_question_during_vision_discards_old_draft_and_reuses_loaded_image(
    tmp_path,
):
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingVision(VisionAI):
        async def generate(self, history, reserve, *, images):
            answer = await super().generate(history, reserve, images=images)
            if len(self.calls) == 1:
                entered.set()
                await release.wait()
                return "OLD DRAFT"
            return answer

    bot, state, _, vision, transport, _ = make_bot(tmp_path, vision=WaitingVision())
    bot.receive(incoming())
    await entered.wait()
    bot.receive(incoming("new", text="Đọc giúp dòng cuối", photo=False))
    release.set()
    await asyncio.gather(*bot.tasks.values())
    assert (
        len(vision.calls) == 2 and len(transport.downloads) == len(transport.sent) == 1
    )
    assert vision.calls[-1][0][-1]["content"] == "Đọc giúp dòng cuối"
    assert transport.sent[0][1] != "OLD DRAFT"
    await finish(bot, state)


@pytest.mark.asyncio
async def test_images_from_different_chats_are_isolated_and_downloads_are_serialized(
    tmp_path,
):
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingVision(VisionAI):
        async def generate(self, history, reserve, *, images):
            answer = await super().generate(history, reserve, images=images)
            if len(self.calls) == 1:
                entered.set()
                await release.wait()
            return answer

    bot, state, _, vision, transport, _ = make_bot(
        tmp_path, vision=WaitingVision(), reply_scope="all_private"
    )
    bot.receive(incoming("first", text="First chat"))
    await entered.wait()
    bot.receive(incoming("second", text="Second chat", thread="e2ee:333@msgr"))
    await asyncio.sleep(0)
    assert len(transport.downloads) == 1
    release.set()
    await asyncio.gather(*bot.tasks.values())
    assert len(vision.calls) == 2
    assert "First chat" in vision.calls[0][0][-1]["content"]
    assert "Second chat" in vision.calls[1][0][-1]["content"]
    assert vision.calls[0][1] != vision.calls[1][1]
    await finish(bot, state)


@pytest.mark.asyncio
@pytest.mark.parametrize("history_messages", [1, 12])
async def test_new_photo_during_previous_send_uses_only_new_photo_and_latest_user_question(
    tmp_path,
    history_messages,
):
    bot, state, _, vision, transport, _ = make_bot(
        tmp_path, history_messages=history_messages
    )
    entered, release = asyncio.Event(), asyncio.Event()
    send = transport.send

    async def delayed_send(message, text):
        result = await send(message, text)
        if len(transport.sent) == 1:
            entered.set()
            await release.wait()
        return result

    transport.send = delayed_send
    bot.receive(incoming("first", text="First photo"))
    await entered.wait()
    bot.receive(incoming("second", text="Second photo"))
    release.set()
    await asyncio.gather(*bot.tasks.values())
    assert len(vision.calls) == len(transport.sent) == 2
    assert len(vision.calls[1][1]) == 1
    assert "second" in vision.calls[1][1][0].data
    assert vision.calls[1][0][-1]["role"] == "user"
    assert "Second photo" in vision.calls[1][0][-1]["content"]
    await finish(bot, state)
