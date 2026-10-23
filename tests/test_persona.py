from unittest.mock import AsyncMock, Mock

import pytest

from messenger_ai import ai as ai_module
from messenger_ai import cli
from messenger_ai.config import Settings, load_persona


def test_public_persona_used_when_no_private_file(tmp_path):
    public = tmp_path / "persona.txt"
    public.write_text("\ufeff  Public instructions\n", encoding="utf-8")
    assert load_persona(tmp_path) == "Public instructions"


@pytest.mark.parametrize("public_exists", [True, False])
def test_private_persona_replaces_public_without_modifying_files(tmp_path, public_exists):
    public = tmp_path / "persona.txt"
    private = tmp_path / "persona.local.txt"
    if public_exists:
        public.write_text("Public instructions", encoding="utf-8")
    private.write_text("  Private instructions\n", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert load_persona(tmp_path) == "Private instructions"
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


@pytest.mark.parametrize("kind", ["empty", "invalid_encoding", "directory"])
def test_invalid_private_persona_does_not_silently_fall_back(tmp_path, kind):
    (tmp_path / "persona.txt").write_text("Public instructions", encoding="utf-8")
    private = tmp_path / "persona.local.txt"
    if kind == "directory":
        private.mkdir()
    else:
        private.write_bytes(b" \n" if kind == "empty" else b"\xffPRIVATE_CONTENT")
    with pytest.raises(ValueError, match=r"persona\.local\.txt") as error:
        load_persona(tmp_path)
    assert "PRIVATE_CONTENT" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("interactive", [False, True])
async def test_ai_checks_and_chat_use_private_persona_without_printing_it(
    tmp_path, monkeypatch, capsys, interactive
):
    (tmp_path / "persona.txt").write_text("Public instructions", encoding="utf-8")
    (tmp_path / "persona.local.txt").write_text("PRIVATE_CONTENT", encoding="utf-8")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(Settings, "load", lambda: Settings())
    monkeypatch.setattr(cli, "load_secrets", lambda: {})
    ai = Mock(
        last_used="Test model",
        generate=AsyncMock(return_value="OK"),
        close=AsyncMock(),
    )
    factory = Mock(return_value=ai)
    monkeypatch.setattr(ai_module, "create_ai", factory)
    loop = AsyncMock()
    from messenger_ai import preview

    monkeypatch.setattr(preview, "chat_loop", loop)
    await cli.check_ai(interactive=interactive)
    assert factory.call_args.args[2] == "PRIVATE_CONTENT"
    assert loop.await_count == int(interactive)
    assert "PRIVATE_CONTENT" not in capsys.readouterr().out
    ai.close.assert_awaited_once()
