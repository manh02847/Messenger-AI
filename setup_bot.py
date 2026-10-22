"""Run with Python 3.11+; no credentials are needed for installation."""

import os
import subprocess
import sys
import venv

from scripts.fetch_assets import ROOT, ensure_bridge, fetch


def main() -> None:
    if sys.version_info < (3, 11):
        raise RuntimeError("Cần Python 3.11 trở lên.")
    os.chdir(ROOT)
    print("Đang tải và kiểm tra thành phần Messenger 2.3.4...", flush=True)
    fetch("fbchat_v2-2.3.4-py3-none-any.whl", ROOT / "vendor")
    ensure_bridge(download=True)
    env = ROOT / ".venv"
    if not env.exists():
        venv.EnvBuilder(with_pip=True).create(env)
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run([str(python), "-m", "messenger_ai", "doctor"], cwd=ROOT, check=True)
    print("\nCài xong. Tiếp theo chạy:")
    print(f'  "{python}" -m messenger_ai configure')
    print("Hướng dẫn từng bước nằm trong README.md.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Cài đặt chưa hoàn tất: {error}", file=sys.stderr)
        raise SystemExit(1)
