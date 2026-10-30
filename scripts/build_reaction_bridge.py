"""Reproduce the Linux amd64 reaction timestamp fix from pinned public source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://github.com/m008v/fbchat-v2.git"
COMMIT = "aa7abd0386ef1d4cabf8ce592d0f2cf308d8f4f6"
META_COMMIT = "cea2e38c9107be591bcd1b7a6562ccc72400ce23"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--go", default="go", help="Go 1.26.10 executable")
    parser.add_argument("--output", type=Path, help="Optional destination; defaults to bin/")
    args = parser.parse_args()
    version = run(args.go, "env", "GOVERSION", capture_output=True, text=True).stdout.strip()
    if version != "go1.26.10":
        raise SystemExit("Use Go 1.26.10 to reproduce the pinned build.")
    manifest = json.loads((ROOT / "assets.json").read_text())
    entry = manifest["bridge_patches"]["fbchat-bridge-e2ee-linux-amd64"]
    patch = ROOT / "patches/fbchat-v2-2.3.4-reaction-timestamp.patch"
    if hashlib.sha256(patch.read_bytes()).hexdigest() != entry["patch_sha256"]:
        raise SystemExit("Source patch checksum mismatch.")
    with tempfile.TemporaryDirectory(prefix="reaction-bridge-") as temporary:
        source = Path(temporary) / "source"
        run("git", "clone", "--branch", "v2.3.4", "--depth", "1", "--recurse-submodules", "--shallow-submodules", SOURCE, str(source))
        for folder, expected in ((source, COMMIT), (source / "bridge-e2ee/meta", META_COMMIT)):
            actual = run("git", "-C", str(folder), "rev-parse", "HEAD", capture_output=True, text=True).stdout.strip()
            if actual != expected:
                raise SystemExit("Pinned source commit mismatch.")
        run("git", "apply", "--check", str(patch), cwd=source)
        run("git", "apply", str(patch), cwd=source)
        env = {**os.environ, "CGO_ENABLED": "0", "GOTOOLCHAIN": "local", "GOOS": "linux", "GOARCH": "amd64"}
        module = source / "bridge-e2ee"
        run(args.go, "test", "./...", cwd=module, env=env)
        built = Path(temporary) / "fbchat-bridge-e2ee-linux-amd64"
        run(args.go, "build", "-trimpath", "-buildvcs=false", "-ldflags", "-s -w -buildid=", "-o", str(built), ".", cwd=module, env=env)
        if hashlib.sha256(built.read_bytes()).hexdigest() != entry["sha256"]:
            raise SystemExit("Rebuilt binary differs from the committed SHA-256; not installed.")
        destination = args.output or ROOT / "bin/fbchat-bridge-e2ee-linux-amd64"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            raise SystemExit("Refusing a symlink output.")
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
            output.write(built.read_bytes())
            name = Path(output.name)
        try:
            name.chmod(0o700)
            os.replace(name, destination)
        finally:
            name.unlink(missing_ok=True)
        print("Rebuilt bridge matches the pinned binary SHA-256.")


if __name__ == "__main__":
    main()
