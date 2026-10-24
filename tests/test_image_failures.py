import base64
import hashlib
import io
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from messenger_ai.facebook import FacebookTransport
from messenger_ai.images import (
    MAX_IMAGE_BYTES,
    ImageAttachment,
    ImageError,
    download_error,
    prepare_image,
    validate_attachment,
)


def photo_and_attachment(size):
    output = io.BytesIO()
    Image.new("RGB", (40, 40), "blue").save(output, format="PNG")
    data = output.getvalue()
    return data, ImageAttachment(
        direct_path="/v/PRIVATE_SIGNED_PATH?token=PRIVATE_TOKEN",
        media_key=base64.b64encode(b"k" * 32).decode(),
        media_sha256=base64.b64encode(hashlib.sha256(data).digest()).decode(),
        file_size=size,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, 1, 1000])
async def test_missing_or_imprecise_declared_size_uses_hard_cap_and_valid_hash(
    tmp_path, size
):
    data, attachment = photo_and_attachment(size)
    calls = []

    class Bridge:
        async def call(self, method, params):
            calls.append((method, params))
            return {"data": base64.b64encode(data).decode(), "fileSize": len(data)}

    transport = FacebookTransport("", tmp_path / "device", tmp_path / "binary")
    transport.listener = SimpleNamespace(_bridge=Bridge())
    result = await transport.load_image(attachment, encrypted=True)
    assert result.mime_type == "image/jpeg"
    assert calls[0][0] == "downloadE2EEMedia"
    assert calls[0][1]["fileSize"] == MAX_IMAGE_BYTES
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_corrupted_plaintext_is_rejected_even_with_unknown_size(tmp_path):
    data, attachment = photo_and_attachment(0)

    class Bridge:
        async def call(self, *args):
            return {"data": base64.b64encode(data + b"tampered").decode()}

    transport = FacebookTransport("", tmp_path / "device", tmp_path / "binary")
    transport.listener = SimpleNamespace(_bridge=Bridge())
    with pytest.raises(ImageError) as error:
        await transport.load_image(attachment, encrypted=True)
    assert error.value.code == "E2EE_HASH_MISMATCH"


@pytest.mark.asyncio
async def test_actual_byte_limit_is_still_enforced_after_download(
    tmp_path, monkeypatch
):
    data, attachment = photo_and_attachment(0)
    monkeypatch.setattr("messenger_ai.facebook.MAX_IMAGE_BYTES", 10)

    class Bridge:
        async def call(self, *args):
            return {"data": base64.b64encode(data).decode()}

    transport = FacebookTransport("", tmp_path / "device", tmp_path / "binary")
    transport.listener = SimpleNamespace(_bridge=Bridge())
    with pytest.raises(ImageError) as error:
        await transport.load_image(attachment, encrypted=True)
    assert error.value.code == "IMAGE_TOO_LARGE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code",
    [(403, "MEDIA_HTTP_403"), (404, "MEDIA_HTTP_404"), (500, "MEDIA_HTTP_ERROR")],
)
async def test_http_failure_keeps_safe_error_code_and_never_leaks_url(
    tmp_path, status, code
):
    transport = FacebookTransport(
        "PRIVATE_COOKIE", tmp_path / "device", tmp_path / "binary"
    )
    transport.listener = SimpleNamespace(_bridge=None)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, text="PRIVATE_RESPONSE")
        )
    ) as client:
        transport.media_client = client
        with pytest.raises(ImageError) as error:
            await transport.load_image(
                ImageAttachment(
                    url="https://scontent.fbcdn.net/image?token=PRIVATE_TOKEN"
                ),
                encrypted=False,
            )
    assert error.value.code == code
    assert "PRIVATE" not in str(error.value)


@pytest.mark.asyncio
async def test_bridge_error_is_classified_without_echoing_server_exception(tmp_path):
    _, attachment = photo_and_attachment(0)

    class Bridge:
        async def call(self, *args):
            raise RuntimeError(
                "failed to download E2EE media: download failed with status 403, https://media.fbcdn.net/PRIVATE_TOKEN"
            )

    transport = FacebookTransport("", tmp_path / "device", tmp_path / "binary")
    transport.listener = SimpleNamespace(_bridge=Bridge())
    with pytest.raises(ImageError) as error:
        await transport.load_image(attachment, encrypted=True)
    assert error.value.code == "MEDIA_HTTP_403"
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize(
    "raw,code",
    [
        ("client not initialised PRIVATE", "E2EE_NOT_READY"),
        ("failed to refresh media connections PRIVATE", "E2EE_SESSION_FAILED"),
        ("invalid media sha256 PRIVATE", "E2EE_HASH_MISMATCH"),
        ("invalid hmac PRIVATE", "E2EE_DECRYPT_FAILED"),
        ("context deadline exceeded PRIVATE", "MEDIA_TIMEOUT"),
        ("tls handshake PRIVATE", "MEDIA_NETWORK_FAILED"),
        ("unknown error PRIVATE", "E2EE_DOWNLOAD_FAILED"),
    ],
)
def test_untrusted_download_exception_is_never_printed(raw, code):
    error = download_error(RuntimeError(raw), encrypted=True)
    assert error.code == code
    assert "PRIVATE" not in str(error)
    assert "PRIVATE" not in str(ImageError("PRIVATE"))


def test_decoder_and_pixel_failures_have_distinct_codes(monkeypatch):
    with pytest.raises(ImageError) as invalid:
        prepare_image(b"invalid image")
    assert invalid.value.code == "IMAGE_DECODE_FAILED"
    data, _ = photo_and_attachment(0)
    monkeypatch.setattr("messenger_ai.images.MAX_IMAGE_PIXELS", 10)
    with pytest.raises(ImageError) as huge:
        prepare_image(data)
    assert huge.value.code == "IMAGE_PIXEL_LIMIT"


def test_missing_pillow_has_actionable_error_code(monkeypatch):
    import builtins

    original = builtins.__import__

    def without_pillow(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("PRIVATE_PATH")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_pillow)
    with pytest.raises(ImageError) as error:
        prepare_image(b"bytes")
    assert error.value.code == "IMAGE_DECODER_MISSING"
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"file_size": -1}, "IMAGE_SIZE_INVALID"),
        ({"file_size": MAX_IMAGE_BYTES + 1}, "IMAGE_TOO_LARGE"),
        ({"media_key": ""}, "E2EE_KEY_INVALID"),
        ({"media_sha256": ""}, "E2EE_HASH_INVALID"),
        ({"direct_path": ""}, "E2EE_PATH_MISSING"),
    ],
)
def test_missing_event_metadata_has_specific_safe_error_code(changes, code):
    _, attachment = photo_and_attachment(0)
    with pytest.raises(ImageError) as error:
        validate_attachment(replace(attachment, **changes), encrypted=True)
    assert error.value.code == code
    assert "PRIVATE" not in str(error.value)
