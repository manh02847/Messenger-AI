"""Download the pinned upstream wheel/bridge and verify SHA-256 before use."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "assets.json").read_text(encoding="utf-8"))


def bridge_name() -> str:
    system = platform.system().lower()
    arch = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(platform.machine().lower())
    name = f"fbchat-bridge-e2ee-{system}-{arch}"
    if system == "windows":
        name += ".exe"
    if name not in MANIFEST["sha256"]:
        raise RuntimeError("Chưa có bridge dựng sẵn cho hệ điều hành/CPU này.")
    return name


def verify(path: Path, name: str) -> None:
    if not path.is_file() or path.stat().st_size > 50 * 1024 * 1024:
        raise RuntimeError(f"Tệp bridge hoặc wheel chưa hợp lệ: {name}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != MANIFEST["sha256"][name]:
        raise RuntimeError(
            f"Checksum không khớp: {name}. Xóa tệp này rồi chạy lại setup_bot.py."
        )


def fetch(name: str, directory: Path, *, download: bool = True) -> Path:
    if name not in MANIFEST["sha256"]:
        raise ValueError("Tệp không có trong danh sách phiên bản đã ghim.")
    path = directory / name
    if path.exists():
        verify(path, name)
        return path
    if not download:
        raise RuntimeError("Thiếu bridge. Chạy python setup_bot.py trước.")
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="download-", dir=directory)
    try:
        request = urllib.request.Request(
            MANIFEST["base_url"] + name,
            headers={"User-Agent": "messenger-ai-bot-setup/1.0"},
        )
        with os.fdopen(descriptor, "wb") as output:
            with urllib.request.urlopen(request, timeout=40) as response:
                if not response.geturl().startswith("https://"):
                    raise RuntimeError("Từ chối tải qua kết nối không mã hóa.")
                count = 0
                while chunk := response.read(65536):
                    count += len(chunk)
                    if count > 50 * 1024 * 1024:
                        raise RuntimeError("Tệp tải về lớn hơn giới hạn dự kiến.")
                    output.write(chunk)
        temp_path = Path(temporary)
        verify(temp_path, name)
        temp_path.chmod(0o700 if name.startswith("fbchat-bridge") else 0o600)
        os.replace(temp_path, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def ensure_bridge(*, download: bool = False) -> Path:
    return fetch(bridge_name(), ROOT / "bin", download=download)


if __name__ == "__main__":
    fetch("fbchat_v2-2.3.4-py3-none-any.whl", ROOT / "vendor")
    print(ensure_bridge(download=True).name)
