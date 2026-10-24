"""Validate incoming photo references and prepare bounded, metadata-free inputs."""

from __future__ import annotations

import base64
import binascii
import io
from dataclasses import dataclass, field
from urllib.parse import urlsplit

MAX_IMAGES = 2
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_SIDE = 1600
MAX_PREPARED_BYTES = 1024 * 1024
MEDIA_TIMEOUT = 20
IMAGE_FAILURE = "Mình chưa mở được ảnh này, bạn thử gửi lại ảnh JPG hoặc PNG nhé."
MEDIA_HOSTS = ("fbcdn.net", "fbsbx.com", "facebook.com", "messenger.com")


class ImageError(RuntimeError):
    def __init__(self):
        super().__init__(
            "Không tải hoặc xử lý được ảnh; kiểm tra định dạng/kích thước."
        )


@dataclass(frozen=True)
class ImageAttachment:
    url: str = field(default="", repr=False)
    direct_path: str = field(default="", repr=False)
    media_key: str = field(default="", repr=False)
    media_sha256: str = field(default="", repr=False)
    media_enc_sha256: str = field(default="", repr=False)
    mime_type: str = "image/jpeg"
    file_size: int = 0


@dataclass(frozen=True)
class ImageInput:
    data: str = field(repr=False)
    mime_type: str = "image/jpeg"

    @property
    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.data}"


def image_attachments(raw: object) -> tuple[ImageAttachment, ...]:
    if not isinstance(raw, list):
        return ()
    images = []
    for item in raw:
        if not isinstance(item, dict) or item.get("type") != "image":
            continue

        def string(name: str, maximum: int = 8192) -> str:
            value = item.get(name, "")
            return value if isinstance(value, str) and len(value) <= maximum else ""

        size = item.get("fileSize", 0)
        images.append(
            ImageAttachment(
                url=string("url"),
                direct_path=string("directPath"),
                media_key=string("mediaKey", 44),
                media_sha256=string("mediaSha256", 44),
                media_enc_sha256=string("mediaEncSha256", 44),
                mime_type=string("mimeType", 100) or "image/jpeg",
                file_size=size if type(size) is int else -1,
            )
        )
        if len(images) > MAX_IMAGES:
            images.pop(0)
    return tuple(images)


def validate_media_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if (
            len(url) > 8192
            or parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or not any(
                host == allowed or host.endswith("." + allowed)
                for allowed in MEDIA_HOSTS
            )
        ):
            raise ImageError()
    except ValueError:
        raise ImageError() from None
    return url


def validate_attachment(image: ImageAttachment, *, encrypted: bool) -> None:
    if image.file_size < 0 or image.file_size > MAX_IMAGE_BYTES:
        raise ImageError()
    if not encrypted:
        validate_media_url(image.url)
        return
    # A positive size makes the pinned bridge's temporary download hard-capped.
    if (
        not image.file_size
        or not image.direct_path.startswith("/")
        or len(image.direct_path) > 8192
    ):
        raise ImageError()
    values = [image.media_key, image.media_sha256]
    if image.media_enc_sha256:
        values.append(image.media_enc_sha256)
    for value in values:
        try:
            if len(value) != 44 or len(base64.b64decode(value, validate=True)) != 32:
                raise ImageError()
        except (ValueError, binascii.Error):
            raise ImageError() from None


def prepare_image(data: bytes) -> ImageInput:
    from PIL import Image, ImageOps

    if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE_BYTES:
        raise ImageError()
    try:
        with Image.open(io.BytesIO(data)) as source:
            if (
                source.format not in ("JPEG", "PNG", "WEBP")
                or source.width * source.height > MAX_IMAGE_PIXELS
                or source.width <= 0
                or source.height <= 0
                or getattr(source, "is_animated", False)
            ):
                raise ImageError()
            source.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
            upright = ImageOps.exif_transpose(source)
            rgba = upright.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=85)
            if output.tell() > MAX_PREPARED_BYTES:
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=65)
            if output.tell() > MAX_PREPARED_BYTES:
                raise ImageError()
            return ImageInput(base64.b64encode(output.getvalue()).decode("ascii"))
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ImageError() from None


def test_image() -> ImageInput:
    """A local red square for check-vision; contains no personal data."""
    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (128, 128), (255, 0, 0)).save(output, format="PNG")
    return prepare_image(output.getvalue())
