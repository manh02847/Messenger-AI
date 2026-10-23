import io
import os
import select
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from messenger_ai.chatgpt_web import parse_cookie_input
from messenger_ai.secret_input import read_cookie_hidden

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="Linux/Unix terminal regression"
)


def through_pty(chunks):
    import pty
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    ready = threading.Event()

    class Status(io.StringIO):
        def flush(self):
            ready.set()

    status = Status()
    with os.fdopen(slave, "r", encoding="utf-8") as source:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(read_cookie_hidden, stdin=source, stderr=status)
            try:
                assert ready.wait(2), "hidden reader did not initialize"
                for chunk in chunks:
                    pending = memoryview(chunk)
                    while pending:
                        pending = pending[os.write(master, pending) :]
                try:
                    result = future.result(timeout=3)
                finally:
                    assert termios.tcgetattr(slave) == original
                # The input was not echoed back to the terminal master.
                assert not select.select([master], [], [], 0.02)[0]
                return result, status.getvalue()
            finally:
                os.close(master)


def test_cookie_over_4095_bytes_survives_real_terminal_without_echo():
    cookie = "a=" + "x" * 4088 + "; token=" + "y" * 6000
    result, visible = through_pty([(cookie + "\n").encode()])
    assert result == cookie
    assert len(result) == 10098
    assert len(parse_cookie_input(result)) == 2
    assert "xxxxx" not in visible and "yyyyy" not in visible


def test_chunked_bracketed_paste_preserves_multiline_and_waits_for_enter():
    cookie = "a=one;\nb=two\n"
    result, _ = through_pty(
        [b"\x1b[20", b"0~", cookie.encode(), b"\x1b[201", b"~", b"\n"]
    )
    assert result == cookie
    assert [(c["name"], c["value"]) for c in parse_cookie_input(result)] == [
        ("a", "one"),
        ("b", "two"),
    ]


def test_overlong_input_is_rejected_instead_of_silently_truncated():
    with pytest.raises(ValueError, match="64 KiB"):
        through_pty([b"\x1b[200~a=" + b"x" * 65536 + b"\x1b[201~\n"])


def test_cancel_restores_terminal():
    with pytest.raises(KeyboardInterrupt):
        through_pty([b"\x03"])


def test_invalid_utf8_restores_terminal_and_does_not_echo():
    with pytest.raises(ValueError, match="UTF-8"):
        through_pty([b"a=\xff\n"])


def test_nonterminal_requires_file_instead_of_echoing_secret():
    with pytest.raises(ValueError, match="--file"):
        read_cookie_hidden(stdin=io.StringIO("a=private"), stderr=io.StringIO())
