import base64
import io
import hashlib
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from messenger_ai.core import parse_event
from messenger_ai.facebook import FacebookTransport
from messenger_ai.images import (
    MAX_IMAGE_BYTES,
    ImageAttachment,
    ImageError,
    image_attachments,
    prepare_image,
    validate_attachment,
    validate_media_url,
)


def photo(size=(40, 20), color="red", format="PNG", **kwargs):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format=format, **kwargs)
    return output.getvalue()


def encrypted_photo(data):
    key = base64.b64encode(b"k" * 32).decode()
    return ImageAttachment(
        direct_path="/v/t62.7118-24/PRIVATE_PATH",
        media_key=key,
        media_sha256=base64.b64encode(hashlib.sha256(data).digest()).decode(),
        media_enc_sha256=key,
        mime_type="image/png",
        file_size=len(data),
    )


@pytest.mark.parametrize("event_type", ["message", "e2eeMessage"])
def test_parse_photo_only_and_caption_events_with_bounded_attachments(event_type):
    attachments = [None, {"type": "video"}]
    attachments += [
        {"type": "image", "url": f"https://scontent.xx.fbcdn.net/{i}.jpg"}
        for i in range(4)
    ]
    parsed = parse_event(
        {
            "type": event_type,
            "data": {
                "id": "photo",
                "senderId": 222,
                "threadId": 333,
                "threadType": 1,
                "chatJid": "222@msgr",
                "timestampMs": 1000,
                "attachments": attachments,
            },
        }
    )
    assert parsed.text == "" and parsed.is_private
    assert [image.url.rsplit("/", 1)[-1] for image in parsed.images] == [
        "2.jpg",
        "3.jpg",
    ]
    assert image_attachments("not a list") == ()


@pytest.mark.parametrize(
    "url",
    [
        "http://scontent.fbcdn.net/image",
        "file:///root/secrets.json",
        "https://127.0.0.1/image",
        "https://fbcdn.net.evil.example/image",
        "https://evilfacebook.com/image",
        "https://user:password@fbcdn.net/image",
        "https://fbcdn.net:8080/image",
        "https://fbcdn.net:bad/image",
    ],
)
def test_media_url_rejects_non_meta_hosts_and_credentials(url):
    with pytest.raises(ImageError):
        validate_media_url(url)


def test_valid_media_reference_and_private_fields_not_printed():
    assert validate_media_url("https://scontent.xx.fbcdn.net/photo?token=PRIVATE")
    image = encrypted_photo(photo())
    validate_attachment(image, encrypted=True)
    validate_attachment(replace(image, media_enc_sha256=""), encrypted=True)
    assert "PRIVATE_PATH" not in repr(image) and image.media_key not in repr(image)


@pytest.mark.parametrize(
    "changes",
    [
        {"file_size": -1},
        {"file_size": MAX_IMAGE_BYTES + 1},
        {"media_key": "bad"},
        {"media_sha256": "bad"},
        {"media_enc_sha256": "bad"},
        {"direct_path": "https://evil.example/image"},
    ],
)
def test_reject_bad_encrypted_image_before_download(changes):
    with pytest.raises(ImageError):
        validate_attachment(
            replace(encrypted_photo(photo()), **changes), encrypted=True
        )


def test_prepare_rotates_strips_metadata_bounds_dimensions_and_converts_to_jpeg():
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "PRIVATE METADATA"
    prepared = prepare_image(photo((2000, 1000), format="JPEG", exif=exif))
    with Image.open(io.BytesIO(base64.b64decode(prepared.data))) as image:
        assert image.format == "JPEG" and image.mode == "RGB"
        assert image.size == (800, 1600)
        assert not image.getexif()
    assert prepared.mime_type == "image/jpeg"
    assert len(base64.b64decode(prepared.data)) <= 1024 * 1024
    assert prepared.data not in repr(prepared)


def test_transparent_png_has_white_background():
    output = io.BytesIO()
    Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(output, format="PNG")
    prepared = prepare_image(output.getvalue())
    with Image.open(io.BytesIO(base64.b64decode(prepared.data))) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("data", [b"", b"not an image", b"x" * (MAX_IMAGE_BYTES + 1)])
def test_reject_invalid_and_oversized_bytes(data):
    with pytest.raises(ImageError):
        prepare_image(data)


def test_reject_large_pixel_count_and_animated_input(monkeypatch):
    monkeypatch.setattr("messenger_ai.images.MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ImageError):
        prepare_image(photo((20, 20)))
    output = io.BytesIO()
    Image.new("RGB", (10, 10)).save(output, format="GIF")
    with pytest.raises(ImageError):
        prepare_image(output.getvalue())


@pytest.mark.asyncio
async def test_e2ee_uses_pinned_bridge_action_download_and_decryption_metadata(
    tmp_path,
):
    data, calls = photo(), []
    attachment = encrypted_photo(data)

    class Bridge:
        async def call(self, method, params):
            calls.append((method, params))
            return {
                "data": base64.b64encode(data).decode(),
                "fileSize": len(data),
                "mimeType": "image/png",
            }

    transport = FacebookTransport(
        "PRIVATE_COOKIE", tmp_path / "device", tmp_path / "bridge"
    )
    transport.listener = SimpleNamespace(_bridge=Bridge())
    result = await transport.load_image(attachment, encrypted=True)
    assert result.mime_type == "image/jpeg"
    assert calls == [
        (
            "downloadE2EEMedia",
            {
                "directPath": attachment.direct_path,
                "mediaKey": attachment.media_key,
                "mediaSha256": attachment.media_sha256,
                "mediaEncSha256": attachment.media_enc_sha256,
                "mediaType": "image",
                "mimeType": "image/png",
                "fileSize": MAX_IMAGE_BYTES,
            },
        )
    ]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_normal_photo_downloads_with_no_cookie_or_authorization(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        assert (
            "cookie" not in request.headers and "authorization" not in request.headers
        )
        if request.url.path == "/original":
            return httpx.Response(
                302, headers={"location": "https://scontent.xx.fbcdn.net/photo"}
            )
        return httpx.Response(200, content=photo())

    transport = FacebookTransport(
        "PRIVATE_COOKIE", tmp_path / "device", tmp_path / "bridge"
    )
    transport.listener = SimpleNamespace(_bridge=None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport.media_client = client
        result = await transport.load_image(
            ImageAttachment(url="https://scontent.xx.fbcdn.net/original"),
            encrypted=False,
        )
    assert result.mime_type == "image/jpeg" and len(requests) == 2


@pytest.mark.asyncio
async def test_normal_photo_rejects_off_host_redirect_and_redacts_error(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            302, headers={"location": "https://127.0.0.1/PRIVATE_SECRET"}
        )

    transport = FacebookTransport("", tmp_path / "device", tmp_path / "bridge")
    transport.listener = SimpleNamespace(_bridge=None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport.media_client = client
        with pytest.raises(ImageError) as error:
            await transport.load_image(
                ImageAttachment(url="https://fbcdn.net/image"), encrypted=False
            )
    assert len(calls) == 1 and "PRIVATE_SECRET" not in str(error.value)


@pytest.mark.asyncio
async def test_streamed_download_limit_applies_without_content_length(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("messenger_ai.facebook.MAX_IMAGE_BYTES", 64)

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * 32
            yield b"x" * 40

    transport = FacebookTransport("", tmp_path / "device", tmp_path / "bridge")
    transport.listener = SimpleNamespace(_bridge=None)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks()))
    ) as client:
        transport.media_client = client
        with pytest.raises(ImageError):
            await transport.load_image(
                ImageAttachment(url="https://fbcdn.net/image"), encrypted=False
            )
