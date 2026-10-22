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
        raise AIError("API yêu cầu chờ lâu hơn 60 giây. Bỏ lượt này, chờ tin nhắn mới.")
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


def validate_connection(
    api_key: str, settings: Settings, account_id: str = ""
) -> tuple[str, str]:
    provider = settings.ai_provider
    if provider not in ("groq", "cloudflare"):
        raise ValueError("Nhà cung cấp AI chưa được hỗ trợ.")
    label = "Cloudflare" if provider == "cloudflare" else "Groq"
    if not api_key.strip():
        raise ValueError(f"Thiếu API key/token {label}; chạy configure-ai.")
    if provider == "cloudflare":
        if not re.fullmatch(r"[0-9a-fA-F]{32}", account_id):
            raise ValueError("Cloudflare Account ID phải gồm 32 ký tự hex.")
        if not settings.model.startswith("@cf/"):
            raise ValueError("Model Cloudflare phải bắt đầu bằng @cf/.")
        return (
            label,
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions",
        )
    return label, API_URL


class ChatAI:
    def __init__(
        self,
        api_key: str,
        settings: Settings,
        persona: str,
        *,
        client: httpx.AsyncClient | None = None,
        account_id: str = "",
    ):
        self.provider = settings.ai_provider
        self.label, self.api_url = validate_connection(api_key, settings, account_id)
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
        persona = self.persona
        if (
            self.provider == "cloudflare"
            and self.settings.model == "@cf/qwen/qwen3-30b-a3b-fp8"
        ):
            persona += "\n/no_think"
        payload = {
            "model": self.settings.model,
            "messages": [{"role": "system", "content": persona}, *history],
            "temperature": 0.6,
            "stream": False,
        }
        token_field = (
            "max_tokens" if self.provider == "cloudflare" else "max_completion_tokens"
        )
        payload[token_field] = self.settings.max_completion_tokens
        if self.provider == "groq" and self.settings.model.startswith(
            "openai/gpt-oss-"
        ):
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
                        self.api_url,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=payload,
                    )
                except httpx.RequestError:
                    if attempt == 2:
                        raise AIError(
                            f"Chưa kết nối được {self.label}; không gửi tin nhắn trả lời."
                        ) from None
                    await asyncio.sleep(2**attempt)
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 2:
                        raise AIError(
                            f"{self.label} đang giới hạn hoặc lỗi dịch vụ (HTTP {response.status_code})."
                        )
                    await asyncio.sleep(
                        retry_delay(response.headers.get("retry-after"), attempt + 1)
                    )
                    continue
                if response.status_code in (401, 403):
                    raise AIError(
                        f"{self.label} từ chối API key/token, tài khoản hoặc quyền truy cập model."
                    )
                if response.status_code >= 400:
                    raise AIError(
                        f"{self.label} từ chối cấu hình yêu cầu (HTTP {response.status_code}); kiểm tra tên model."
                    )
                try:
                    data = response.json()
                    choice = data["choices"][0]
                    if choice.get("finish_reason") == "length":
                        raise AIError(
                            "Câu trả lời chạm max_completion_tokens (gồm suy luận); "
                            "đây không phải thông báo hết quota API. "
                            "Chạy tune-chat nếu đang dùng mức 768 cũ."
                        )
                    return final_text(choice["message"]["content"])
                except (ValueError, KeyError, IndexError, TypeError):
                    raise AIError(
                        f"Phản hồi {self.label} không đúng định dạng mong đợi."
                    ) from None
        raise AIError(f"Không nhận được phản hồi từ {self.label}.")

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()


# Compatibility for existing integrations importing the original class name.
GroqAI = ChatAI


def create_ai(secrets: dict[str, str], settings: Settings, persona: str) -> ChatAI:
    key = (
        "cloudflare_api_token"
        if settings.ai_provider == "cloudflare"
        else "groq_api_key"
    )
    return ChatAI(
        secrets.get(key, ""),
        settings,
        persona,
        account_id=secrets.get("cloudflare_account_id", ""),
    )
