"""Download the pinned upstream wheel/bridge and verify SHA-256 before use."""

from __future__ import annotations

import bz2
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
    name = bridge_name()
    patch = MANIFEST.get("bridge_patches", {}).get(name)
    if patch is not None:
        return patched_bridge(name, patch, ROOT / "bin", download=download)
    return fetch(name, ROOT / "bin", download=download)


def _offset(value: bytes) -> int:
    if len(value) != 8:
        raise RuntimeError("BSDIFF thiếu số nguyên điều khiển.")
    result = int.from_bytes(value, "little") & ((1 << 63) - 1)
    return -result if value[7] & 0x80 else result


def _bz2_block(value: bytes, limit: int) -> bytes:
    decoder = bz2.BZ2Decompressor()
    try:
        result = decoder.decompress(value, max_length=limit + 1)
    except (OSError, EOFError) as error:
        raise RuntimeError("Khối nén BSDIFF không hợp lệ.") from error
    if len(result) > limit or not decoder.eof or decoder.unused_data:
        raise RuntimeError("Khối BSDIFF vượt giới hạn hoặc chưa hoàn chỉnh.")
    return result


def apply_bsdiff(old: bytes, patch: bytes) -> bytes:
    """Read BSDIFF40 with fixed bounds; no extra runtime package is needed."""
    limit = 50 * 1024 * 1024
    if len(old) > limit or len(patch) > limit or len(patch) < 32 or patch[:8] != b"BSDIFF40":
        raise RuntimeError("Gói BSDIFF40 không hợp lệ.")
    control_size, diff_size, size = (_offset(patch[n:n + 8]) for n in (8, 16, 24))
    if min(control_size, diff_size, size) < 0 or size > limit or 32 + control_size + diff_size > len(patch):
        raise RuntimeError("Kích thước BSDIFF40 không hợp lệ.")
    control = _bz2_block(patch[32:32 + control_size], 4 * 1024 * 1024)
    diff = _bz2_block(patch[32 + control_size:32 + control_size + diff_size], limit)
    extra = _bz2_block(patch[32 + control_size + diff_size:], limit)
    result = bytearray(size)
    new_pos = old_pos = control_pos = diff_pos = extra_pos = 0
    while new_pos < size:
        if control_pos + 24 > len(control):
            raise RuntimeError("BSDIFF thiếu lệnh điều khiển.")
        add, copy, seek = (_offset(control[n:n + 8]) for n in range(control_pos, control_pos + 24, 8))
        control_pos += 24
        if min(add, copy) < 0 or new_pos + add + copy > size or diff_pos + add > len(diff) or extra_pos + copy > len(extra):
            raise RuntimeError("Lệnh BSDIFF vượt giới hạn dữ liệu.")
        result[new_pos:new_pos + add] = diff[diff_pos:diff_pos + add]
        for index in range(max(0, -old_pos), min(add, len(old) - old_pos)):
            result[new_pos + index] = (result[new_pos + index] + old[old_pos + index]) & 0xFF
        new_pos += add
        old_pos += add + seek
        diff_pos += add
        result[new_pos:new_pos + copy] = extra[extra_pos:extra_pos + copy]
        extra_pos += copy
        new_pos += copy
    if control_pos != len(control) or diff_pos != len(diff) or extra_pos != len(extra):
        raise RuntimeError("BSDIFF có dữ liệu thừa.")
    return bytes(result)


def patched_bridge(name: str, patch: dict, directory: Path, *, download=False) -> Path:
    """Install a bundled, separately pinned fix; never replace an unknown binary."""
    expected = patch["sha256"]
    target = directory / name
    if target.is_symlink():
        raise RuntimeError("Từ chối bridge qua symlink.")
    if target.exists():
        if not target.is_file() or target.stat().st_size > 50 * 1024 * 1024:
            raise RuntimeError("Bridge hiện có vượt giới hạn hoặc không phải tệp thường.")
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual == expected:
            target.chmod(0o700)
            return target
        if actual != MANIFEST["sha256"][name]:
            raise RuntimeError("Bridge hiện có không khớp checksum đã ghim; không tự ghi đè.")
    if patch.get("format") != "bsdiff40" or patch.get("base_sha256") != MANIFEST["sha256"][name]:
        raise RuntimeError("Định dạng hoặc bản gốc của bridge patch chưa hợp lệ.")
    relative = Path(patch["archive"])
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError("Đường dẫn bản vá bridge chưa hợp lệ.")
    archive = ROOT / relative
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > 50 * 1024 * 1024:
        raise RuntimeError("Thiếu hoặc lỗi gói bridge đã vá; cập nhật đủ repository.")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != patch["archive_sha256"]:
        raise RuntimeError("Checksum gói bridge đã vá không khớp; không giải nén.")
    base = fetch(name, directory, download=download)
    content = apply_bsdiff(base.read_bytes(), archive.read_bytes())
    if not content or hashlib.sha256(content).hexdigest() != expected:
        raise RuntimeError("Checksum bridge sau vá không khớp; giữ nguyên bản cũ.")
    fd, temporary = tempfile.mkstemp(prefix="bridge-patch-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        Path(temporary).chmod(0o700)
        os.replace(temporary, target)
        return target
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    fetch("fbchat_v2-2.3.4-py3-none-any.whl", ROOT / "vendor")
    print(ensure_bridge(download=True).name)
