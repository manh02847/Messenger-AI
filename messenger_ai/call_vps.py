"""Dedicated, unprivileged VPS desktop and audio relay; no Facebook credentials."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
import sys
from pathlib import Path

from .call_lab import MODELS, CallRelay, LabConfig

STATE = Path("/var/lib/messenger-ai-call")
RUNTIME = Path("/run/messenger-ai-call")


class HostError(RuntimeError):
    pass


def read_settings(root: Path) -> dict:
    try:
        data = json.loads((root / "settings.json").read_text())
    except (OSError, ValueError):
        raise HostError(
            "Chưa đọc được cấu hình gọi VPS; chạy lại setup_call_vps.py."
        ) from None
    if not isinstance(data, dict):
        raise HostError("Cấu hình gọi VPS chưa hợp lệ.")
    if (
        data.get("model") not in MODELS
        or type(data.get("max_seconds")) is not int
        or not 15 <= data["max_seconds"] <= 900
        or not isinstance(data.get("google_api_key"), str)
        or not data["google_api_key"].isascii()
        or not data["google_api_key"]
        or any(c.isspace() for c in data["google_api_key"])
        or not isinstance(data.get("relay_token"), str)
        or not data["relay_token"].isascii()
        or not 32 <= len(data["relay_token"]) <= 200
        or not isinstance(data.get("browser"), str)
        or not Path(data["browser"]).is_absolute()
    ):
        raise HostError("Cấu hình gọi VPS chưa hợp lệ.")
    return data


def commands(root: Path, runtime: Path, browser: str) -> list[tuple[str, list[str]]]:
    return [
        (
            "Màn hình",
            [
                "Xtigervnc",
                ":77",
                "-geometry",
                "1280x800",
                "-depth",
                "24",
                "-localhost",
                "-rfbport",
                "5977",
                "-SecurityTypes",
                "VncAuth",
                "-PasswordFile",
                str(root / "vnc.passwd"),
                "-nolisten",
                "tcp",
                "-auth",
                str(runtime / "Xauthority"),
                "-MaxDisconnectionTime",
                "0",
                "-MaxIdleTime",
                "0",
                "-FrameRate",
                "20",
            ],
        ),
        (
            "Âm thanh",
            [
                "pulseaudio",
                "--daemonize=no",
                "--exit-idle-time=-1",
                "--use-pid-file=no",
                "-n",
                "--load=module-native-protocol-unix",
                "--load=module-null-sink sink_name=call_speaker",
                "--load=module-null-sink sink_name=call_microphone",
                "--load=module-always-sink",
            ],
        ),
        ("Cửa sổ", ["openbox", "--sm-disable"]),
        (
            "Điều khiển",
            [
                "websockify",
                "--web",
                "/usr/share/novnc",
                "127.0.0.1:6080",
                "127.0.0.1:5977",
            ],
        ),
        (
            "Chrome",
            [
                browser,
                "--user-data-dir=" + str(root / "chrome-profile"),
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-dev-shm-usage",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--window-size=1280,800",
                "https://www.facebook.com/",
            ],
        ),
    ]


async def quiet(*args, env=None) -> int:
    proc = await asyncio.create_subprocess_exec(
        *args,
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        return await asyncio.wait_for(proc.wait(), 3)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise


async def prepare_authority(runtime: Path):
    path = runtime / "Xauthority"
    path.touch(mode=0o600, exist_ok=True)
    process = await asyncio.create_subprocess_exec(
        "xauth",
        "-f",
        str(path),
        "source",
        "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(
            process.communicate(
                ("add :77 MIT-MAGIC-COOKIE-1 " + secrets.token_hex(16) + "\n").encode()
            ),
            3,
        )
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise HostError("Chưa tạo được quyền truy cập màn hình ảo.")


async def wait_ready(args, process, env):
    async with asyncio.timeout(15):
        while process.returncode is None:
            if await quiet(*args, env=env) == 0:
                return
            await asyncio.sleep(0.2)
    raise HostError("Một thành phần desktop chưa sẵn sàng; kiểm tra gói cài đặt.")


async def terminate(process):
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        await asyncio.wait_for(process.wait(), 5)
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
    except ProcessLookupError:
        await process.wait()


async def run(root: Path = STATE, runtime: Path = RUNTIME, *, port=8765):
    from websockets.asyncio.server import serve

    if os.geteuid() == 0:
        raise HostError(
            "Chrome VPS cần chạy bằng user messenger-call qua system service."
        )
    data = read_settings(root)
    if not (root / "vnc.passwd").is_file():
        raise HostError(
            "Thiếu mật khẩu màn hình; chạy setup_call_vps.py password bằng root."
        )
    runtime.joinpath("pulse").mkdir(mode=0o700, exist_ok=True)
    env = {
        **os.environ,
        "DISPLAY": ":77",
        "XAUTHORITY": str(runtime / "Xauthority"),
        "XDG_RUNTIME_DIR": str(runtime),
        "PULSE_SERVER": "unix:" + str(runtime / "pulse/native"),
        "PULSE_SINK": "call_speaker",
        "PULSE_SOURCE": "call_microphone.monitor",
    }
    children, watchers = [], []
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    relay = CallRelay(
        LabConfig(
            data["google_api_key"],
            data["relay_token"],
            data["model"],
            data["max_seconds"],
        )
    )
    try:
        await prepare_authority(runtime)
        async with serve(
            relay.handle,
            "127.0.0.1",
            port,
            process_request=relay.origin_check,
            max_size=16000,
            max_queue=8,
            compression=None,
            ping_interval=15,
            ping_timeout=15,
            close_timeout=3,
        ):
            for name, args in commands(root, runtime, data["browser"]):
                if stopped.is_set():
                    return
                process = await asyncio.create_subprocess_exec(
                    *args,
                    env=env,
                    start_new_session=True,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                children.append((name, process))
                if name == "Màn hình":
                    await wait_ready(["xdpyinfo", "-display", ":77"], process, env)
                if name == "Âm thanh":
                    await wait_ready(["pactl", "info"], process, env)
                    for option, value in (
                        ("set-default-sink", "call_speaker"),
                        ("set-default-source", "call_microphone.monitor"),
                    ):
                        if await quiet("pactl", option, value, env=env):
                            raise HostError("Chưa tạo được thiết bị âm thanh ảo.")
            print(
                "Đã mở desktop Chrome trên VPS; vào noVNC để đăng nhập Facebook và bật chế độ tự động.",
                flush=True,
            )
            watchers = [asyncio.create_task(proc.wait()) for _, proc in children]
            stop_task = asyncio.create_task(stopped.wait())
            watchers.append(stop_task)
            done, _ = await asyncio.wait(watchers, return_when=asyncio.FIRST_COMPLETED)
            if stop_task not in done:
                index = next(i for i, task in enumerate(watchers[:-1]) if task in done)
                raise HostError(
                    f"{children[index][0]} đã dừng; systemd sẽ thử khởi động lại."
                )
    finally:
        for task in watchers:
            task.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)
        await asyncio.gather(*(terminate(proc) for _, proc in reversed(children)))
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


def main():
    os.umask(0o077)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except HostError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print(
            "Gọi VPS chưa khởi động được; kiểm tra cấu hình/cổng và chạy lại bộ cài.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
