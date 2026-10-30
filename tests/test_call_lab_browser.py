import asyncio
import base64
import json
import math
import os
import shutil
import struct
from pathlib import Path

import pytest
from websockets.asyncio.server import serve

from messenger_ai.call_lab import CallRelay, LabConfig

ROOT = Path(__file__).resolve().parents[1]
NODE = os.environ.get("CODEX_PRIMARY_RUNTIME_NODE") or shutil.which("node")


@pytest.mark.skipif(not NODE, reason="Node is needed for the extension PCM tests")
def test_extension_audio_and_session_protocols():
    import subprocess

    subprocess.run(
        [
            NODE,
            "--test",
            str(ROOT / "scripts/test_call_lab_pcm.cjs"),
            str(ROOT / "scripts/test_call_lab_bridge.cjs"),
            str(ROOT / "scripts/test_call_lab_extension.cjs"),
            str(ROOT / "scripts/test_call_lab_incoming.cjs"),
            str(ROOT / "scripts/test_call_lab_caller.cjs"),
        ],
        check=True,
        capture_output=True,
        timeout=15,
    )


def tone(frequency):
    return base64.b64encode(
        b"".join(
            struct.pack("<h", int(6000 * math.sin(2 * math.pi * frequency * i / 24000)))
            for i in range(24000 * 6)
        )
    ).decode()


class BrowserGoogle:
    def __init__(self, index, frames):
        self.index, self.frames = index, frames
        self.queue = asyncio.Queue()
        self.queue.put_nowait(json.dumps({"setupComplete": {}}))
        self.job = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        if self.job:
            self.job.cancel()
            await asyncio.gather(self.job, return_exceptions=True)

    def output(self, frequency):
        self.queue.put_nowait(
            json.dumps(
                {
                    "serverContent": {
                        "modelTurn": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "audio/pcm;rate=24000",
                                        "data": tone(frequency),
                                    }
                                }
                            ]
                        }
                    }
                }
            )
        )

    async def send(self, raw):
        data = json.loads(raw)
        if "clientContent" in data:
            self.output(660)

            async def later():
                await asyncio.sleep(3.5)
                if self.index == 0:
                    self.queue.put_nowait(
                        json.dumps({"serverContent": {"interrupted": True}})
                    )
                    self.output(880)
                else:
                    self.queue.put_nowait(RuntimeError("Synthetic upstream disconnect"))

            self.job = asyncio.create_task(later())
        if "realtimeInput" in data and len(self.frames) < 8:
            self.frames.append(base64.b64decode(data["realtimeInput"]["audio"]["data"]))

    async def recv(self):
        item = await self.queue.get()
        if isinstance(item, Exception):
            raise item
        return item

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.recv()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not NODE or not os.environ.get("CALL_LAB_CHROME"),
    reason="Set CALL_LAB_CHROME to run the real Chromium/WebRTC fixture",
)
async def test_chrome_extension_routes_remote_audio_and_restores_microphone():
    frames, created = [], []

    def connector(*args, **kwargs):
        item = BrowserGoogle(len(created), frames)
        created.append(item)
        return item

    config = LabConfig("TEST_GOOGLE", "TEST_LOOPBACK_TOKEN_123456789", max_seconds=45)
    relay = CallRelay(config, connector=connector, log=lambda _: None)
    async with serve(
        relay.handle,
        "127.0.0.1",
        0,
        process_request=relay.origin_check,
        max_size=16000,
        compression=None,
        close_timeout=0.2,
    ) as listener:
        port = listener.sockets[0].getsockname()[1]
        env = {
            **os.environ,
            "CALL_LAB_TEST_URL": f"ws://127.0.0.1:{port}",
            "CALL_LAB_TEST_TOKEN": config.token,
        }
        process = await asyncio.create_subprocess_exec(
            NODE,
            str(ROOT / "scripts/test_call_lab_browser.cjs"),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(process.communicate(), 55)
        except BaseException:
            process.kill()
            await process.wait()
            raise
        assert process.returncode == 0, err.decode() + out.decode()
        report = json.loads(out.decode().splitlines()[-1])
        assert all(
            report[key] == "passed"
            for key in (
                "webrtc",
                "ai_audio",
                "interruption",
                "restore_microphone",
                "disconnect_restore",
            )
        )
    assert frames and len(created) == 2
    samples = struct.unpack("<" + "h" * (len(b"".join(frames)) // 2), b"".join(frames))
    crossings = sum(a < 0 <= b for a, b in zip(samples, samples[1:]))
    frequency = crossings / (len(samples) / 16000)
    # The caller sends 440 Hz; the original local microphone is 220 Hz.
    assert 410 < frequency < 470
