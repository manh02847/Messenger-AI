from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from dataclasses import replace
from email.utils import parsedate_to_datetime
from typing import Callable

import httpx

from .config import Settings

API_URL = "https://api.groq.com/openai/v1/chat/completions"


class AIError(RuntimeError):
    pass


class ProviderUnavailable(AIError):
    def __init__(self, message: str, cooldown: float = 300):
        super().__init__(message)
        self.cooldown = cooldown


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
        raise ProviderUnavailable(
            "API yêu cầu chờ lâu hơn 60 giây.", cooldown=delay if delay > 60 else 300
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
        fail_fast: bool = False,
    ):
        self.fail_fast = fail_fast
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
            attempts = 1 if self.fail_fast else 3
            for attempt in range(attempts):
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
                    if attempt == attempts - 1:
                        raise ProviderUnavailable(
                            f"Chưa kết nối được {self.label}; không gửi tin nhắn trả lời."
                        ) from None
                    await asyncio.sleep(2**attempt)
                    continue
                if response.status_code in (408, 429) or response.status_code >= 500:
                    if attempt == attempts - 1:
                        try:
                            delay = retry_delay(
                                response.headers.get("retry-after"), attempt + 1
                            )
                        except ProviderUnavailable as error:
                            delay = error.cooldown
                        raise ProviderUnavailable(
                            f"{self.label} đang giới hạn hoặc lỗi dịch vụ (HTTP {response.status_code}).",
                            cooldown=max(
                                300 if response.status_code == 429 else 60, delay
                            ),
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


DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "cloudflare": "@cf/qwen/qwen3-30b-a3b-fp8",
}


def provider_configs(secrets: dict[str, str], settings: Settings):
    configs = [settings]
    if settings.ai_fallback:
        other = "groq" if settings.ai_provider == "cloudflare" else "cloudflare"
        configs.append(
            replace(
                settings,
                ai_provider=other,
                model=settings.fallback_model or DEFAULT_MODELS[other],
            )
        )
    result = []
    for config in configs:
        key = (
            "cloudflare_api_token"
            if config.ai_provider == "cloudflare"
            else "groq_api_key"
        )
        token = secrets.get(key, "")
        account_id = secrets.get("cloudflare_account_id", "")
        validate_connection(token, config, account_id)
        result.append((token, config, account_id))
    return result


class FallbackAI:
    def __init__(self, primary, secondary, *, clock=time.monotonic, log=print):
        self.clients = (primary, secondary)
        self.label = f"{primary.label} → {secondary.label}"
        self.clock, self.log = clock, log
        self.blocked_until = [0.0, 0.0]
        self._lock = asyncio.Lock()

    async def generate(self, history, reserve):
        async with self._lock:
            for index, ai in enumerate(self.clients):
                if self.clock() < self.blocked_until[index]:
                    continue
                try:
                    answer = await ai.generate(history, reserve)
                except ProviderUnavailable as error:
                    self.blocked_until[index] = self.clock() + error.cooldown
                    self.log(
                        f"{ai.label} tạm không khả dụng; nghỉ {error.cooldown:.0f} giây."
                    )
                    continue
                if index:
                    self.log(f"Đã tạo câu trả lời bằng nguồn dự phòng: {ai.label}.")
                return answer
            raise AIError(
                "Cả hai nguồn AI đang lỗi hoặc chờ phục hồi; bỏ lượt này, chờ tin mới."
            )

    async def close(self):
        try:
            await self.clients[0].close()
        finally:
            await self.clients[1].close()


def create_ai(secrets: dict[str, str], settings: Settings, persona: str):
    configs = provider_configs(secrets, settings)
    clients = [
        ChatAI(
            token,
            config,
            persona,
            account_id=account_id,
            fail_fast=settings.ai_fallback,
        )
        for token, config, account_id in configs
    ]
    return FallbackAI(*clients) if settings.ai_fallback else clients[0]
