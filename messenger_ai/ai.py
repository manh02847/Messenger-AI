from __future__ import annotations

import asyncio
import random
import re
import time
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from email.utils import parsedate_to_datetime
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

from .config import GOOGLE_MODELS, Settings

API_URL = "https://api.groq.com/openai/v1/chat/completions"
GOOGLE_REQUEST_TIMEOUT = 8
GOOGLE_MODEL_TIMEOUT = 12
GOOGLE_POOL_TIMEOUT = 20
GOOGLE_GEMMA_TIMEOUT = 10


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


def google_cooldown(response: httpx.Response, default: float) -> float:
    """Honor Google's structured retry hint and daily quota reset, without logging bodies."""
    try:
        details = response.json().get("error", {}).get("details", [])
        for detail in details:
            if detail.get("@type", "").endswith("google.rpc.RetryInfo"):
                delay = detail.get("retryDelay", "")
                if isinstance(delay, str) and re.fullmatch(
                    r"[0-9]+(?:\.[0-9]+)?s", delay
                ):
                    default = max(default, float(delay[:-1]))
            if detail.get("@type", "").endswith("google.rpc.QuotaFailure"):
                for violation in detail.get("violations", []):
                    quota_id = violation.get("quotaId", "").lower()
                    if "perday" in quota_id or "per_day" in quota_id:
                        now = datetime.now(ZoneInfo("America/Los_Angeles"))
                        midnight = (now + timedelta(days=1)).replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )
                        default = max(
                            default, midnight.timestamp() - now.timestamp() + 5
                        )
    except (ValueError, AttributeError, TypeError, OverflowError):
        pass
    return default


def google_payload(
    settings: Settings, persona: str, history: list[dict[str, str]]
) -> dict:
    return {
        "systemInstruction": {"parts": [{"text": persona}]},
        "contents": [
            {
                "role": "model" if item["role"] == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in history
        ],
        "generationConfig": {
            "temperature": 0.6,
            "maxOutputTokens": settings.max_completion_tokens,
            "thinkingConfig": {
                "thinkingLevel": "minimal"
                if settings.model.startswith("gemma-")
                else "low",
                "includeThoughts": False,
            },
        },
    }


def google_text(data: dict) -> str:
    if data.get("promptFeedback", {}).get("blockReason"):
        raise AIError("Google không tạo câu trả lời cho yêu cầu này.")
    candidate = data["candidates"][0]
    reason = candidate.get("finishReason")
    if reason == "MAX_TOKENS":
        raise AIError(
            "Câu trả lời Google chạm max_completion_tokens; chưa gửi bản bị cắt."
        )
    if reason != "STOP":
        raise AIError(
            "Google chưa trả về câu trả lời hoàn chỉnh; không gửi nội dung này."
        )
    parts = candidate["content"]["parts"]
    return final_text(
        "".join(
            part["text"]
            for part in parts
            if not part.get("thought") and isinstance(part.get("text"), str)
        )
    )


def validate_connection(
    api_key: str, settings: Settings, account_id: str = ""
) -> tuple[str, str]:
    provider = settings.ai_provider
    if provider not in ("groq", "cloudflare", "google"):
        raise ValueError("Nhà cung cấp AI chưa được hỗ trợ.")
    label = {"cloudflare": "Cloudflare", "groq": "Groq", "google": "Google"}[provider]
    if not api_key.strip():
        command = "configure-google" if provider == "google" else "configure-ai"
        raise ValueError(f"Thiếu API key/token {label}; chạy {command}.")
    if provider == "google":
        if settings.model not in GOOGLE_MODELS:
            raise ValueError("Model Google chưa được hỗ trợ.")
        return (
            label,
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.model}:generateContent",
        )
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
        self.description = f"{self.label} / {settings.model}"
        self.last_used = ""
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
            "max_tokens"
            if self.provider == "cloudflare"
            and self.settings.model != "@cf/qwen/qwen3.8-27b"
            else "max_completion_tokens"
        )
        payload[token_field] = self.settings.max_completion_tokens
        if self.provider == "groq" and self.settings.model.startswith(
            "openai/gpt-oss-"
        ):
            payload.update(reasoning_effort="low", include_reasoning=False)
        elif self.provider == "groq" and self.settings.model == "qwen/qwen3.8-27b":
            payload.update(reasoning_effort="low", reasoning_format="hidden")
        elif (
            self.provider == "cloudflare"
            and self.settings.model == "@cf/qwen/qwen3.8-27b"
        ):
            payload.update(reasoning_effort="low")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.provider == "google":
            payload = google_payload(self.settings, self.persona, history)
            headers = {"x-goog-api-key": self.api_key}
        async with self._lock:
            if self.provider == "google":
                try:
                    async with asyncio.timeout(GOOGLE_MODEL_TIMEOUT):
                        return await self._request(payload, headers, reserve)
                except TimeoutError:
                    raise ProviderUnavailable(
                        "Google phản hồi quá chậm; chuyển model/nguồn tiếp theo.",
                        cooldown=30,
                    ) from None
            return await self._request(payload, headers, reserve)

    async def _request(self, payload, headers, reserve):
        google = self.provider == "google"
        attempts = 2 if google else (1 if self.fail_fast else 3)
        for attempt in range(attempts):
            wait = self.settings.minimum_ai_interval_seconds - (
                time.monotonic() - self._last_attempt
            )
            if wait > 0:
                await asyncio.sleep(wait)
            if not reserve():
                raise AIError("Đã đạt giới hạn gọi AI trong ngày do bạn đặt.")
            self._last_attempt = time.monotonic()
            request_options = (
                {"timeout": httpx.Timeout(GOOGLE_REQUEST_TIMEOUT, connect=4)}
                if google
                else {}
            )
            try:
                response = await self.client.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    **request_options,
                )
            except httpx.RequestError:
                if google or attempt == attempts - 1:
                    raise ProviderUnavailable(
                        f"Chưa kết nối được {self.label}; không gửi tin nhắn trả lời.",
                        cooldown=30 if google else 300,
                    ) from None
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code in (408, 429) or response.status_code >= 500:
                if google:
                    try:
                        delay = retry_delay(response.headers.get("retry-after"), 0)
                    except ProviderUnavailable as error:
                        delay = error.cooldown
                    delay = google_cooldown(response, delay)
                    quick_retry = (
                        attempt == 0
                        and response.status_code in (500, 502, 503, 504)
                        and time.monotonic() - self._last_attempt <= 2
                        and delay <= 2
                    )
                    if quick_retry:
                        print(
                            f"{self.description}: HTTP {response.status_code}, thử lại một lần trước khi chuyển nguồn."
                        )
                        await asyncio.sleep(delay + random.uniform(0, 0.5))
                        continue
                    raise ProviderUnavailable(
                        f"Google đang giới hạn hoặc lỗi dịch vụ (HTTP {response.status_code}).",
                        cooldown=max(300 if response.status_code == 429 else 20, delay),
                    )
                if attempt == attempts - 1:
                    try:
                        delay = retry_delay(
                            response.headers.get("retry-after"), attempt + 1
                        )
                    except ProviderUnavailable as error:
                        delay = error.cooldown
                    raise ProviderUnavailable(
                        f"{self.label} đang giới hạn hoặc lỗi dịch vụ (HTTP {response.status_code}).",
                        cooldown=max(300 if response.status_code == 429 else 60, delay),
                    )
                await asyncio.sleep(
                    retry_delay(response.headers.get("retry-after"), attempt + 1)
                )
                continue
            if self.provider == "google" and response.status_code == 404:
                raise ProviderUnavailable(
                    "Model Google không khả dụng; kiểm tra model trong AI Studio.",
                    cooldown=3600,
                )
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
                if self.provider == "google":
                    answer = google_text(data)
                    self.last_used = self.description
                    return answer
                choice = data["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise AIError(
                        "Câu trả lời chạm max_completion_tokens (gồm suy luận); "
                        "đây không phải thông báo hết quota API. "
                        "Chạy tune-chat nếu đang dùng mức 768 cũ."
                    )
                answer = final_text(choice["message"]["content"])
                self.last_used = self.description
                return answer
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                raise AIError(
                    f"Phản hồi {self.label} không đúng định dạng mong đợi."
                ) from None
        raise AIError(f"Không nhận được phản hồi từ {self.label}.")

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()


# Compatibility for existing integrations importing the original class name.
GroqAI = ChatAI


CHAT_MODELS = {
    "groq": "qwen/qwen3.8-27b",
    "cloudflare": "@cf/qwen/qwen3.8-27b",
}

DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "cloudflare": "@cf/qwen/qwen3-30b-a3b-fp8",
}


def provider_configs(secrets: dict[str, str], settings: Settings):
    configs = [
        replace(settings, ai_provider="google", model=model)
        for model in settings.google_models
    ]
    configs.append(settings)
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
        key = {
            "cloudflare": "cloudflare_api_token",
            "groq": "groq_api_key",
            "google": "google_api_key",
        }[config.ai_provider]
        token = secrets.get(key, "")
        account_id = secrets.get("cloudflare_account_id", "")
        validate_connection(token, config, account_id)
        result.append((token, config, account_id))
    return result


class FallbackAI:
    def __init__(self, primary, secondary, *others, clock=time.monotonic, log=print):
        self.clients = (primary, secondary, *others)
        self.label = " → ".join(
            getattr(ai, "description", ai.label) for ai in self.clients
        )
        self.description = self.label
        self.last_used = ""
        self.clock, self.log = clock, log
        self.blocked_until = [0.0] * len(self.clients)
        self._lock = asyncio.Lock()

    async def generate(self, history, reserve):
        async with self._lock:
            try:
                async with asyncio.timeout(60):
                    return await self._generate(history, reserve)
            except TimeoutError:
                raise AIError(
                    "Các nguồn AI phản hồi quá chậm; bỏ lượt này, chờ tin mới."
                ) from None

    async def _generate(self, history, reserve):
        google_started = None
        gemma_remaining = GOOGLE_GEMMA_TIMEOUT
        has_flash = any(
            getattr(ai, "provider", None) == "google"
            and getattr(getattr(ai, "settings", None), "model", "").startswith(
                "gemini-"
            )
            for ai in self.clients
        )
        for index, ai in enumerate(self.clients):
            if self.clock() < self.blocked_until[index]:
                continue
            try:
                if getattr(ai, "provider", None) == "google":
                    if google_started is None:
                        google_started = self.clock()
                    remaining = GOOGLE_POOL_TIMEOUT - (self.clock() - google_started)
                    if remaining <= 0:
                        continue
                    gemma = has_flash and ai.settings.model.startswith("gemma-")
                    if gemma and gemma_remaining <= 0:
                        continue
                    gemma_deadline = gemma and gemma_remaining < remaining
                    if gemma:
                        remaining = min(remaining, gemma_remaining)
                    attempt_started = self.clock()
                    try:
                        async with asyncio.timeout(remaining):
                            answer = await ai.generate(history, reserve)
                    except TimeoutError:
                        self.blocked_until[index] = self.clock() + 30
                        if gemma_deadline:
                            gemma_remaining = 0
                            self.log(
                                "Gemma đã hết 10 giây chờ của lượt này; thử Flash tiếp theo."
                            )
                        else:
                            self.log(
                                "Google đã hết thời gian chờ của lượt này; chuyển sang nguồn khác."
                            )
                            # Skip remaining Google models for this turn.
                            google_started = self.clock() - GOOGLE_POOL_TIMEOUT
                        continue
                    finally:
                        if gemma:
                            gemma_remaining -= max(0, self.clock() - attempt_started)
                else:
                    answer = await ai.generate(history, reserve)
            except ProviderUnavailable as error:
                self.blocked_until[index] = self.clock() + error.cooldown
                self.log(
                    f"{getattr(ai, 'description', ai.label)}: {error} Nghỉ {error.cooldown:.0f} giây."
                )
                continue
            self.last_used = getattr(ai, "description", ai.label)
            self.log(f"Đã tạo câu trả lời bằng: {self.last_used}.")
            return answer
        raise AIError(
            "Các nguồn AI đang lỗi hoặc chờ phục hồi; bỏ lượt này, chờ tin mới."
        )

    async def close(self):
        results = await asyncio.gather(
            *(ai.close() for ai in self.clients), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result


def create_ai(secrets: dict[str, str], settings: Settings, persona: str):
    configs = provider_configs(secrets, settings)
    clients = [
        ChatAI(
            token,
            config,
            persona,
            account_id=account_id,
            fail_fast=len(configs) > 1,
        )
        for token, config, account_id in configs
    ]
    return FallbackAI(*clients) if len(clients) > 1 else clients[0]
