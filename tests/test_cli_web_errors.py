from unittest.mock import AsyncMock, Mock

import pytest

from messenger_ai import cli
from messenger_ai.ai import ProviderUnavailable


def test_import_refuses_busy_bot_before_requesting_cookie(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["messenger_ai", "import-chatgpt-cookie"])
    secret_prompt = Mock()
    monkeypatch.setattr(cli.getpass, "getpass", secret_prompt)
    with cli.instance_lock(tmp_path / "data"):
        with pytest.raises(SystemExit) as error:
            cli.main()
    assert error.value.code == 1
    assert "systemctl --user stop messenger-ai" in capsys.readouterr().err
    secret_prompt.assert_not_called()


def test_web_check_refuses_busy_bot_without_opening_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["messenger_ai", "check-chatgpt-web"])
    check = AsyncMock()
    monkeypatch.setattr(cli, "check_chatgpt_web", check)
    with cli.instance_lock(tmp_path / "data"):
        with pytest.raises(SystemExit):
            cli.main()
    check.assert_not_called()


@pytest.mark.parametrize("known_error", [True, False])
def test_known_unavailable_message_shown_untrusted_error_hidden(
    tmp_path, monkeypatch, capsys, known_error
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["messenger_ai", "check-chatgpt-web"])
    error = (
        ProviderUnavailable("Chưa cài requirements-web.txt và Chromium; xem README.")
        if known_error
        else Exception("private-secret")
    )
    monkeypatch.setattr(cli, "check_chatgpt_web", AsyncMock(side_effect=error))
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 1
    output = capsys.readouterr().err
    assert "private-secret" not in output
    assert ("Chưa cài requirements-web.txt" in output) is known_error
