"""Hidden terminal input that does not silently truncate long Linux lines."""

from __future__ import annotations

import os
import sys

MAX_COOKIE_BYTES = 65536
PASTE_START = b"\x1b[200~"
PASTE_END = b"\x1b[201~"


def read_cookie_hidden(*, stdin=None, stderr=None) -> str:
    stdin = stdin if stdin is not None else sys.stdin
    stderr = stderr if stderr is not None else sys.stderr
    if not stdin.isatty():
        raise ValueError("Cần terminal tương tác để nhập ẩn; hoặc dùng --file.")
    if os.name == "nt":
        import getpass

        return getpass.getpass("Cookie ChatGPT (nhập ẩn): ", stream=stderr)

    import termios

    fd = stdin.fileno()
    original = termios.tcgetattr(fd)
    modified = original[:]
    modified[6] = original[6][:]
    modified[0] &= ~(termios.ICRNL | termios.INLCR | termios.IGNCR | termios.IXON)
    modified[3] &= ~(
        termios.ECHO | termios.ECHONL | termios.ICANON | termios.IEXTEN | termios.ISIG
    )
    modified[6][termios.VMIN] = 1
    modified[6][termios.VTIME] = 0
    data = bytearray()
    escape = bytearray()
    pasted = overflow = False
    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, modified)
        stderr.write(
            "\x1b[?2004hCookie ChatGPT (dán ẩn, Enter để xác nhận, Ctrl+C để hủy): "
        )
        stderr.flush()
        complete = False
        while not complete:
            chunk = os.read(fd, 4096)
            if not chunk:
                raise ValueError("Đã hết dữ liệu nhập; chưa nhập cookie.")
            for char in chunk:
                if escape or char == 27:
                    escape.append(char)
                    if escape == PASTE_START:
                        pasted = True
                        escape.clear()
                    elif escape == PASTE_END:
                        pasted = False
                        escape.clear()
                    elif not (
                        PASTE_START.startswith(escape) or PASTE_END.startswith(escape)
                    ):
                        raise ValueError(
                            "Có ký tự điều khiển trong dữ liệu nhập; dùng --file."
                        )
                    continue
                if not pasted:
                    if char in (10, 13):
                        complete = True
                        break
                    if char == 3:
                        raise KeyboardInterrupt
                    if char == 4:
                        raise ValueError("Đã hủy nhập cookie.")
                    if char in (8, 127):
                        if data:
                            data.pop()
                        continue
                    if char == 21:
                        data.clear()
                        overflow = False
                        continue
                if len(data) < MAX_COOKIE_BYTES:
                    data.append(char)
                else:
                    # Drain the paste until confirmation; don't send leftovers to shell.
                    overflow = True
        if overflow:
            raise ValueError("Cookie lớn hơn 64 KiB; chưa nhập cookie.")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError(
                "Dữ liệu cookie không phải UTF-8 hợp lệ; dùng --file."
            ) from None
    finally:
        # Restore the terminal even on Ctrl+C/error. Flush unconsumed pasted data.
        try:
            termios.tcsetattr(fd, termios.TCSAFLUSH, original)
        finally:
            stderr.write("\x1b[?2004l\n")
            stderr.flush()
