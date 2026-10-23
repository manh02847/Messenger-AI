from unittest.mock import AsyncMock, Mock

import pytest

from messenger_ai.chatgpt_web import PROFILE, page_diagnostic


def page(
    title="ChatGPT",
    body="private-secret-sidebar",
    url="https://chatgpt.com/?private=secret",
    login=False,
    profile=False,
):
    result = Mock(url=url, title=AsyncMock(return_value=title))
    result.locator.return_value = Mock(inner_text=AsyncMock(return_value=body))

    def roles(role, name):
        visible = profile if name is PROFILE else login
        locator = Mock(count=AsyncMock(return_value=int(visible)))
        locator.filter.return_value = locator
        return locator

    result.get_by_role.side_effect = roles
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,code",
    [
        (
            {"title": "Just a moment...", "body": "private-request-id"},
            "HUMAN_VERIFICATION",
        ),
        ({"body": "Verify you are human"}, "HUMAN_VERIFICATION"),
        ({"body": "Sorry, you have been blocked. private-IP"}, "ACCESS_BLOCKED"),
        (
            {"url": "https://auth.openai.com/login?token=private-secret"},
            "LOGIN_REQUIRED",
        ),
        ({"login": True}, "LOGIN_REQUIRED"),
        ({"profile": True}, "PROFILE_VISIBLE"),
        ({"body": ""}, "EMPTY_PAGE"),
        ({}, "UNRECOGNIZED_UI"),
    ],
)
async def test_diagnostics_only_return_fixed_codes_and_never_page_or_url_data(
    kwargs, code
):
    output = await page_diagnostic(page(**kwargs))
    assert output.startswith(code + ":")
    assert "private" not in output
    assert "secret" not in output
    assert "https://" not in output


@pytest.mark.asyncio
async def test_no_page_is_not_called_bot_detection():
    assert (await page_diagnostic(None)).startswith("BROWSER_NOT_READY:")


@pytest.mark.asyncio
async def test_unreadable_page_is_not_called_bot_detection_and_hides_exception():
    browser_page = page()
    browser_page.title.side_effect = RuntimeError("private-cookie")
    output = await page_diagnostic(browser_page)
    assert output.startswith("DIAGNOSTIC_UNAVAILABLE:")
    assert "private" not in output
