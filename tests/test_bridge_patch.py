import bz2
import hashlib
import json
from pathlib import Path

import pytest

from scripts import fetch_assets as assets


def offset(value):
    return (abs(value) | ((1 << 63) if value < 0 else 0)).to_bytes(8, "little")


def example_patch():
    # Negative seek reuses earlier old bytes; diff addition wraps modulo 256.
    control = bz2.compress(b"".join(offset(n) for n in (2, 1, -2, 2, 0, 0)))
    diff = bz2.compress(bytes((1, 255, 0, 0)))
    extra = bz2.compress(b"!")
    return b"BSDIFF40" + offset(len(control)) + offset(len(diff)) + offset(5) + control + diff + extra


def fixture(tmp_path, monkeypatch):
    name = "fbchat-bridge-e2ee-linux-amd64"
    old = b"AB"
    expected = b"BA!AB"
    patch = example_patch()
    folder = tmp_path / "native"
    folder.mkdir()
    archive = folder / "test.bsdiff"
    archive.write_bytes(patch)
    entry = {"format": "bsdiff40", "archive": "native/test.bsdiff", "archive_sha256": hashlib.sha256(patch).hexdigest(), "base_sha256": hashlib.sha256(old).hexdigest(), "sha256": hashlib.sha256(expected).hexdigest()}
    monkeypatch.setattr(assets, "ROOT", tmp_path)
    monkeypatch.setattr(assets, "MANIFEST", {"sha256": {name: entry["base_sha256"]}})
    binary = tmp_path / "bin" / name
    binary.parent.mkdir()
    binary.write_bytes(old)
    return name, entry, binary, expected, archive


def test_bsdiff_negative_seek_and_wrapped_difference():
    assert assets.apply_bsdiff(b"AB", example_patch()) == b"BA!AB"


def test_known_original_is_upgraded_atomically_then_reused_without_archive(tmp_path, monkeypatch):
    name, entry, binary, expected, archive = fixture(tmp_path, monkeypatch)
    assert assets.patched_bridge(name, entry, binary.parent).read_bytes() == expected
    assert binary.stat().st_mode & 0o777 == 0o700
    archive.unlink()
    assert assets.patched_bridge(name, entry, binary.parent) == binary


@pytest.mark.parametrize("damage", ["archive", "binary", "output_digest", "symlink", "format"])
def test_bad_patch_or_unknown_binary_is_not_installed(tmp_path, monkeypatch, damage):
    name, entry, binary, expected, archive = fixture(tmp_path, monkeypatch)
    if damage == "archive":
        archive.write_bytes(b"bad")
    elif damage == "binary":
        binary.write_bytes(b"unknown binary")
    elif damage == "output_digest":
        entry["sha256"] = "0" * 64
    elif damage == "symlink":
        binary.unlink()
        binary.symlink_to(archive)
    else:
        entry["format"] = "unknown"
    before = binary.read_bytes()
    with pytest.raises(RuntimeError):
        assets.patched_bridge(name, entry, binary.parent)
    assert binary.read_bytes() == before


@pytest.mark.parametrize("patch", [b"BSDIFF40", b"BADMAGIC" + bytes(32), b"BSDIFF40" + offset(-1) + offset(0) + offset(1), b"BSDIFF40" + offset(1) + offset(1) + offset(100000000)])
def test_malformed_or_oversized_delta_is_rejected(patch):
    with pytest.raises(RuntimeError):
        assets.apply_bsdiff(b"AB", patch)


def test_committed_delta_and_source_patch_match_independent_manifest_pins():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "assets.json").read_text())
    entry = manifest["bridge_patches"]["fbchat-bridge-e2ee-linux-amd64"]
    assert entry["base_sha256"] == manifest["sha256"]["fbchat-bridge-e2ee-linux-amd64"]
    assert hashlib.sha256((root / entry["archive"]).read_bytes()).hexdigest() == entry["archive_sha256"]
    assert hashlib.sha256((root / "patches/fbchat-v2-2.3.4-reaction-timestamp.patch").read_bytes()).hexdigest() == entry["patch_sha256"]
