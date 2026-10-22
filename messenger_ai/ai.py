from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

import httpx

from .config import Settings

API_URL = "https://api.groq.com/openai/v1/chat/completions"


class AIError(RuntimeError):
    pass


def retry_delay(value: str | None, attempt: int) -> float:
    if value:
        try:
            delay = float(value)
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                delay = (date - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                delay = 2**attempt
        if 0 <= delay <= 60:
            return max(1, delay)
        raise AIError(
            "Groq yêu cầu chờ lâu hơn 60 giây. Bỏ lượt này, chờ tin nhắn mới."
        )
    return float(2**attempt)


def final_text(value: object) -> str:
    if not isinstance(value, str):
        raise AIError("Model chưa trả về nội dung văn bản.")
    value = re.sub(
        r"<think>.*?</think>", "", value, flags=re.DOTALL | re.IGNORECASE
    ).strip()
    if "<think" in value.lower():
        raise AIError("Model trả về phần suy luận chưa đóng; không gửi nội dung này.")
    if not value:
        raise AIError("Model trả về câu trả lời trống.")
    return value


class GroqAI:
    def __init__(
        self,
        api_key: str,
        settings: Settings,
        persona: str,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key.strip():
            raise ValueError(
                "Chưa có API key Groq. Chạy configure hoặc đặt GROQ_API_KEY."
            )
        self.api_key = api_key
        self.settings = settings
        self.persona = persona
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(25, connect=10), follow_redirects=False
        )
        self._owns_client = client is None
        self._lock = asyncio.Lock()
        self._last_attempt = 0.0

    async def generate(
        self, history: list[dict[str, str]], reserve: Callable[[], bool]
    ) -> str:
        payload = {
            "model": self.settings.model,
            "messages": [{"role": "system", "content": self.persona}, *history],
            "temperature": 0.6,
            "max_completion_tokens": self.settings.max_completion_tokens,
            "stream": False,
        }
        if self.settings.model.startswith("openai/gpt-oss-"):
            payload.update(reasoning_effort="low", include_reasoning=False)
        async with self._lock:
            for attempt in range(3):
                wait = self.settings.minimum_ai_interval_seconds - (
                    time.monotonic() - self._last_attempt
                )
                if wait > 0:
                    await asyncio.sleep(wait)
                if not reserve():
                    raise AIError("Đã đạt giới hạn gọi AI trong ngày do bạn đặt.")
                self._last_attempt = time.monotonic()
                try:
                    response = await self.client.post(
                        API_URL,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=payload,
                    )
                except httpx.RequestError:
                    if attempt == 2:
                        raise AIError(
                            "Chưa kết nối được Groq; không gửi tin nhắn trả lời."
                        ) from None
                    await asyncio.sleep(2**attempt)
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 2:
                        raise AIError(
                            f"Groq đang giới hạn hoặc lỗi dịch vụ (HTTP {response.status_code})."
                        )
                    await asyncio.sleep(
                        retry_delay(response.headers.get("retry-after"), attempt + 1)
                    )
                    continue
                if response.status_code in (401, 403):
                    raise AIError("Groq từ chối API key hoặc quyền truy cập model.")
                if response.status_code >= 400:
                    raise AIError(
                        f"Groq từ chối cấu hình yêu cầu (HTTP {response.status_code}); kiểm tra tên model."
                    )
                try:
                    data = response.json()
                    choice = data["choices"][0]
                    if choice.get("finish_reason") == "length":
                        raise AIError(
                            "Model hết token trước khi hoàn thành; tăng max_completion_tokens."
                        )
                    return final_text(choice["message"]["content"])
                except (ValueError, KeyError, IndexError, TypeError):
                    raise AIError(
                        "Phản hồi Groq không đúng định dạng mong đợi."
                    ) from None
        raise AIError("Không nhận được phản hồi từ Groq.")

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
