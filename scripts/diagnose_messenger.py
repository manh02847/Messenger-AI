"""Observe Messenger/Signal failures without printing payloads or sending replies."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys
import threading
import time


PATTERNS = {
    "SIGNAL_MAC_INVALID": r"mismatching mac|verify ciphertext mac|bad mac|invalid mac",
    "SIGNAL_NO_VALID_SESSION": r"no valid sessions|no session found for user|uninitialized session",
    "SIGNAL_IDENTITY_UNTRUSTED": r"untrusted identity|invalid signature on device key",
    "SIGNAL_PREKEY_MISSING": r"no signed prekey|prekey store didn.t return one.time key",
    "SIGNAL_SENDER_KEY_MISSING": r"no sender key|sender key state failed verification",
    "SIGNAL_OLD_COUNTER": r"received message with old counter",
    "SIGNAL_VERSION_UNSUPPORTED": r"wrong message version|unknown message version|too old message version",
    "BRIDGE_NON_JSON_LINE": r"\[bridge\] bad json",
    "AUTH_REQUIRED": r"auth_required|authentication is required|checkpoint",
    "LOCK_BUSY": r"đang có một bot/discover",
    "FILE_PERMISSION_ERROR": r"permission denied|permissionerror",
}
MATCHERS = {code: re.compile(pattern, re.I) for code, pattern in PATTERNS.items()}
ERROR_CODES = {
    "BRIDGE_NOT_VERIFIED",
    "SDK_NOT_PINNED",
    "COOKIE_MISSING",
    "LOGIN_NOT_VERIFIED",
    "STARTUP_TIMEOUT",
    "LISTENER_STOPPED",
}


class Metrics:
    def __init__(self):
        self.counts = Counter()
        self.lock = threading.RLock()
        self.own_id = ""
        self.failed_ids: set[str] = set()
        self.ready = False
        self.closed = False
        self.on_ready = None

    def increment(self, code):
        with self.lock:
            self.counts[code] += 1

    def log_line(self, line):
        # Every input line is discarded. Only fixed codes can reach the report.
        found = False
        for code, matcher in MATCHERS.items():
            if matcher.search(line):
                self.increment(code)
                found = True
        if not found:
            self.increment("OTHER_LOG_LINES_HIDDEN")

    def event(self, event):
        if not isinstance(event, dict):
            return
        data = event.get("data")
        if not isinstance(data, dict):
            return
        if event.get("type") in ("message", "e2eeMessage"):
            sender = data.get("senderId")
            own = (
                type(sender) in (str, int)
                and bool(self.own_id)
                and str(sender) == self.own_id
            )
            self.increment("OWNER_MESSAGE_EVENTS" if own else "INCOMING_MESSAGE_EVENTS")
            if event["type"] == "message":
                known = type(data.get("threadType")) is int and data["threadType"] in (
                    1,
                    7,
                    10,
                    13,
                    15,
                )
                if own and not known:
                    self.increment("OWNER_CHAT_TYPE_UNKNOWN_OR_GROUP")
            return
        if event.get("type") == "error":
            self.increment(
                "DECRYPT_ERROR_EVENTS"
                if type(data.get("code")) is int and data["code"] == 2
                else "OTHER_BRIDGE_ERROR_EVENTS"
            )
            return
        if (
            event.get("type") != "raw"
            or data.get("from") != "whatsmeow"
            or data.get("type") != "UndecryptableMessage"
        ):
            return
        failure = data.get("data")
        failure = failure if isinstance(failure, dict) else {}
        info = failure.get("Info")
        info = info if isinstance(info, dict) else {}
        own = info.get("IsFromMe")
        self.increment(
            "OWNER_UNDECRYPTABLE_EVENTS"
            if own is True
            else "REMOTE_UNDECRYPTABLE_EVENTS"
            if own is False
            else "UNKNOWN_UNDECRYPTABLE_EVENTS"
        )
        unavailable = failure.get("IsUnavailable")
        self.increment(
            "MISSING_CIPHERTEXT_EVENTS"
            if unavailable is True
            else "DECRYPT_FAILED_EVENTS"
            if unavailable is False
            else "UNCLASSIFIED_DECRYPT_EVENTS"
        )
        mid = info.get("ID")
        if isinstance(mid, str) and 0 < len(mid) <= 500:
            with self.lock:
                if len(self.failed_ids) < 4096:
                    self.failed_ids.add(mid)

    def report(self):
        with self.lock:
            return {
                "ready": self.ready,
                "listener_closed": self.closed,
                "unique_failed_messages": len(self.failed_ids),
                "counts": dict(sorted(self.counts.items())),
            }


class HiddenOutput:
    """A bounded stdout/stderr sink; it never echoes any captured input."""

    encoding = "utf-8"
    MAX_LINE = 16384

    def __init__(self, metrics):
        self.metrics = metrics
        self.pending = ""
        self.discarding = False
        self.lock = threading.RLock()

    def write(self, text):
        with self.lock:
            parts = text.split("\n")
            for index, part in enumerate(parts):
                if not self.discarding:
                    if len(self.pending) + len(part) > self.MAX_LINE:
                        self.pending = ""
                        self.discarding = True
                    else:
                        self.pending += part
                if index < len(parts) - 1:
                    self._finish_line()
        return len(text)

    def _finish_line(self):
        if self.discarding:
            self.metrics.increment("OVERSIZED_LOG_LINES_HIDDEN")
        elif self.pending:
            self.metrics.log_line(self.pending)
        self.pending, self.discarding = "", False

    def finish(self):
        with self.lock:
            self._finish_line()

    def flush(self):
        pass

    def isatty(self):
        return False


def verified_binary(root: Path, manifest: dict, name: str) -> Path:
    path = root / "bin" / name
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 50 * 1024 * 1024
    ):
        raise ValueError("BRIDGE_NOT_VERIFIED")
    expected = {manifest["sha256"][name]}
    patch = manifest.get("bridge_patches", {}).get(name)
    if patch:
        expected.add(patch["sha256"])
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest not in expected:
        raise ValueError("BRIDGE_NOT_VERIFIED")
    return path


@contextmanager
def private_stderr(metrics):
    # Classify before the SDK's generic redactor removes the error suffix.
    # This override lives only in the diagnostic process and prints nothing.
    from fbchat_v2._messaging._listening_e2ee import _BridgeProcess

    previous = vars(_BridgeProcess)["_log_stderr_line"]

    def classify(raw):
        if len(raw) > HiddenOutput.MAX_LINE:
            metrics.increment("OVERSIZED_LOG_LINES_HIDDEN")
        else:
            metrics.log_line(bytes(raw).decode("utf-8", errors="replace"))

    _BridgeProcess._log_stderr_line = staticmethod(classify)
    try:
        yield
    finally:
        _BridgeProcess._log_stderr_line = previous


async def collect(sdk, cookie, device, binary, metrics, seconds, *, startup_seconds=60):
    async with asyncio.timeout(30):
        data = await sdk.dataGetHome(cookie)
    own = str(data.get("FacebookID", "")) if isinstance(data, dict) else ""
    if not re.fullmatch(r"[1-9][0-9]{0,24}", own):
        raise ValueError("LOGIN_NOT_VERIFIED")
    metrics.own_id = own
    listener = sdk.listeningE2EEEvent(
        data,
        binary_path=str(binary),
        device_path=str(device),
        e2ee_memory_only=False,
        log_level="warn",
        debug_errors=True,
    )
    listener.on_message(metrics.event)
    task = asyncio.create_task(listener.connect_mqtt())
    stopped = False
    try:
        deadline = time.monotonic() + startup_seconds
        while time.monotonic() < deadline:
            if task.done():
                await task
                raise RuntimeError("LISTENER_STOPPED")
            if await asyncio.to_thread(
                listener.wait_until_connected, 0.25, require_e2ee=True
            ):
                metrics.ready = True
                if metrics.on_ready is not None:
                    metrics.on_ready()
                break
        if not metrics.ready:
            raise TimeoutError("STARTUP_TIMEOUT")
        done, _ = await asyncio.wait([task], timeout=seconds)
        if done:
            await task
            raise RuntimeError("LISTENER_STOPPED")
    finally:
        try:
            await asyncio.to_thread(listener.stop)
            stopped = True
        finally:
            try:
                await asyncio.wait_for(task, 10)
            except TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            finally:
                metrics.closed = stopped and task.done()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seconds", type=int, default=30, choices=range(10, 121), metavar="10..120"
    )
    args = parser.parse_args(argv)
    output = sys.stdout
    metrics, step, status = Metrics(), "preflight", "failed"

    def announce_ready():
        output.write(
            f"DIAG_READY: nhắn một tin mới vào tài khoản bot; chờ {args.seconds} giây.\n"
        )
        output.flush()

    metrics.on_ready = announce_ready
    hidden = HiddenOutput(metrics)
    with redirect_stdout(hidden), redirect_stderr(hidden):
        try:
            from scripts.fetch_assets import MANIFEST, ROOT, bridge_name
            from messenger_ai.cli import instance_lock
            from messenger_ai.config import load_secrets

            if importlib.metadata.version("fbchat-v2") != "2.3.4":
                raise ValueError("SDK_NOT_PINNED")
            binary = verified_binary(ROOT, MANIFEST, bridge_name())
            step = "lock"
            with instance_lock(ROOT / "data"):
                step = "credentials"
                cookie = load_secrets(ROOT).get("facebook_cookie", "")
                if not cookie:
                    raise ValueError("COOKIE_MISSING")
                import fbchat_v2

                step = "connection_or_observation"
                with private_stderr(metrics):
                    asyncio.run(
                        collect(
                            fbchat_v2,
                            cookie,
                            ROOT / "data/messenger-device.db",
                            binary,
                            metrics,
                            args.seconds,
                        )
                    )
                status = "complete"
        except (KeyboardInterrupt, asyncio.CancelledError):
            status = "interrupted"
        except BaseException as error:
            detail = str(error)
            if detail in ERROR_CODES:
                metrics.increment(detail)
            else:
                metrics.log_line(detail)
        finally:
            hidden.finish()
    report = {
        "diagnostic_version": 1,
        "status": status,
        "step": step,
        **metrics.report(),
    }
    output.write(json.dumps(report, indent=2, ensure_ascii=True) + "\n")
    return 0 if status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
