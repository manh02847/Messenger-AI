"""Read Google's model IDs on request; never select or enable models automatically."""

from __future__ import annotations

import asyncio

import httpx

from .ai import AIError
from .config import valid_google_model

MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
CATALOG_TIMEOUT = 30


async def list_google_models(
    api_key: str, *, client: httpx.AsyncClient | None = None
) -> tuple[str, ...]:
    if not api_key.strip():
        raise ValueError("Thiếu API key Google; chạy configure-ai google trước.")
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient()
    try:
        async with asyncio.timeout(CATALOG_TIMEOUT):
            models, tokens, page_token = [], set(), ""
            for _ in range(20):
                params = {"pageSize": "1000"}
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get(
                    MODELS_URL,
                    params=params,
                    headers={"x-goog-api-key": api_key},
                    timeout=httpx.Timeout(10, connect=4),
                    follow_redirects=False,
                )
                if response.status_code != 200:
                    raise AIError(
                        f"Không lấy được danh sách Google (HTTP {response.status_code}); "
                        "kiểm tra key, quyền truy cập và billing."
                    )
                try:
                    data = response.json()
                    entries = data.get("models", [])
                    next_token = data.get("nextPageToken", "")
                    if (
                        not isinstance(entries, list)
                        or not isinstance(next_token, str)
                        or len(next_token) > 4096
                        or (next_token and next_token in tokens)
                    ):
                        raise ValueError
                except (ValueError, AttributeError, TypeError):
                    raise AIError(
                        "Danh sách model Google không đúng định dạng."
                    ) from None
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    name = entry.get("name")
                    methods = entry.get("supportedGenerationMethods")
                    if (
                        isinstance(name, str)
                        and name.startswith("models/")
                        and valid_google_model(name[7:])
                        and isinstance(methods, list)
                        and "generateContent" in methods
                        and name[7:] not in models
                    ):
                        models.append(name[7:])
                if not next_token:
                    return tuple(models)
                tokens.add(next_token)
                page_token = next_token
            raise AIError(
                "Danh sách model Google vượt giới hạn phân trang; thử lại sau."
            )
    except (httpx.RequestError, TimeoutError):
        raise AIError(
            "Chưa lấy được danh sách Google do kết nối hoặc timeout."
        ) from None
    finally:
        if owns_client:
            await client.aclose()
