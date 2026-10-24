"""Validate incoming photo references and prepare bounded, metadata-free inputs."""

from __future__ import annotations

import base64
import binascii
import io
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

MAX_IMAGES = 2
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_SIDE = 1600
MAX_PREPARED_BYTES = 1024 * 1024
MEDIA_TIMEOUT = 20
IMAGE_FAILURE = "Mình chưa đọc được ảnh này, bạn thử gửi lại sau nhé."
MEDIA_HOSTS = ("fbcdn.net", "fbsbx.com", "facebook.com", "messenger.com")

IMAGE_ERRORS = {
    "IMAGE_ERROR": "Không tải hoặc xử lý được ảnh.",
    "MESSENGER_NOT_READY": "Kết nối Messenger chưa sẵn sàng tải ảnh.",
    "IMAGE_SIZE_INVALID": "Thông tin kích thước ảnh không hợp lệ.",
    "IMAGE_TOO_LARGE": "Ảnh vượt giới hạn dung lượng.",
    "MEDIA_URL_INVALID": "URL ảnh không thuộc host Meta HTTPS được phép.",
    "E2EE_PATH_MISSING": "Thiếu đường dẫn tải ảnh E2EE hợp lệ trong sự kiện.",
    "E2EE_KEY_INVALID": "Thiếu hoặc sai định dạng khóa ảnh E2EE trong sự kiện.",
    "E2EE_HASH_INVALID": "Thiếu hoặc sai định dạng hash ảnh E2EE trong sự kiện.",
    "E2EE_HASH_MISMATCH": "Nội dung ảnh E2EE không khớp hash, không sử dụng ảnh này.",
    "E2EE_NOT_READY": "Bridge chưa sẵn sàng tải media E2EE.",
    "E2EE_SESSION_FAILED": "Bridge chưa lấy được phiên kết nối tải media.",
    "E2EE_DECRYPT_FAILED": "Bridge chưa xác minh/giải mã được ảnh E2EE.",
    "E2EE_DOWNLOAD_FAILED": "Bridge chưa tải được ảnh E2EE.",
    "MEDIA_BAD_RESPONSE": "Bộ tải chưa trả về dữ liệu ảnh hợp lệ.",
    "MEDIA_TIMEOUT": "Hết thời gian tải/xử lý ảnh.",
    "MEDIA_NETWORK_FAILED": "Lỗi kết nối tới máy chủ ảnh.",
    "MEDIA_HTTP_403": "Máy chủ từ chối tải ảnh (HTTP 403).",
    "MEDIA_HTTP_404": "Không tìm thấy ảnh trên máy chủ (HTTP 404).",
    "MEDIA_HTTP_410": "Ảnh không còn trên máy chủ (HTTP 410).",
    "MEDIA_HTTP_ERROR": "Máy chủ ảnh trả lỗi HTTP.",
    "MEDIA_REDIRECT_LIMIT": "Máy chủ ảnh chuyển hướng quá nhiều lần.",
    "IMAGE_DECODER_MISSING": "Thiếu thư viện xử lý ảnh; chạy lại setup_bot.py.",
    "IMAGE_FORMAT_UNSUPPORTED": "Ảnh không thuộc định dạng JPG/PNG/WebP tĩnh được hỗ trợ.",
    "IMAGE_PIXEL_LIMIT": "Ảnh vượt giới hạn số pixel.",
    "IMAGE_DECODE_FAILED": "Không giải mã được dữ liệu ảnh thành hình.",
    "IMAGE_PREPARED_TOO_LARGE": "Ảnh sau xử lý vẫn vượt giới hạn.",
}


class ImageError(RuntimeError):
    def __init__(self, code: str = "IMAGE_ERROR"):
        # Never echo arbitrary exceptions, signed URLs or keys into logs.
        self.code = code if code in IMAGE_ERRORS else "IMAGE_ERROR"
        super().__init__(f"{self.code}: {IMAGE_ERRORS[self.code]}")


def download_error(error: Exception, *, encrypted: bool) -> ImageError:
    message = str(error).lower()
    status = re.search(
        r"(?:status(?: code)?|http|download failed with)[: =]*(403|404|410)\b", message
    )
    if status:
        return ImageError("MEDIA_HTTP_" + status[1])
    if "client not initialised" in message or "e2ee not connected" in message:
        return ImageError("E2EE_NOT_READY")
    if "failed to refresh media connections" in message:
        return ImageError("E2EE_SESSION_FAILED")
    if "sha256" in message or "checksum mismatch" in message:
        return ImageError("E2EE_HASH_MISMATCH")
    if "hmac" in message or "decrypt" in message:
        return ImageError("E2EE_DECRYPT_FAILED")
    if (
        "deadline exceeded" in message
        or "timed out" in message
        or isinstance(error, TimeoutError)
    ):
        return ImageError("MEDIA_TIMEOUT")
    if any(
        part in message
        for part in ("no such host", "connection refused", "tls handshake")
    ):
        return ImageError("MEDIA_NETWORK_FAILED")
    return ImageError("E2EE_DOWNLOAD_FAILED" if encrypted else "MEDIA_NETWORK_FAILED")


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
            raise ImageError("MEDIA_URL_INVALID")
    except ValueError:
        raise ImageError("MEDIA_URL_INVALID") from None
    return url


def validate_attachment(image: ImageAttachment, *, encrypted: bool) -> None:
    if image.file_size < 0:
        raise ImageError("IMAGE_SIZE_INVALID")
    if image.file_size > MAX_IMAGE_BYTES:
        raise ImageError("IMAGE_TOO_LARGE")
    if not encrypted:
        validate_media_url(image.url)
        return
    if not image.direct_path.startswith("/") or len(image.direct_path) > 8192:
        raise ImageError("E2EE_PATH_MISSING")
    values = [
        (image.media_key, "E2EE_KEY_INVALID"),
        (image.media_sha256, "E2EE_HASH_INVALID"),
    ]
    if image.media_enc_sha256:
        values.append((image.media_enc_sha256, "E2EE_HASH_INVALID"))
    for value, code in values:
        try:
            if len(value) != 44 or len(base64.b64decode(value, validate=True)) != 32:
                raise ImageError(code)
        except (ValueError, binascii.Error):
            raise ImageError(code) from None


def prepare_image(data: bytes) -> ImageInput:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ImageError("IMAGE_DECODER_MISSING") from None

    if not isinstance(data, bytes) or not data:
        raise ImageError("MEDIA_BAD_RESPONSE")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError("IMAGE_TOO_LARGE")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ("JPEG", "PNG", "WEBP") or getattr(
                source, "is_animated", False
            ):
                raise ImageError("IMAGE_FORMAT_UNSUPPORTED")
            if (
                source.width * source.height > MAX_IMAGE_PIXELS
                or source.width <= 0
                or source.height <= 0
            ):
                raise ImageError("IMAGE_PIXEL_LIMIT")
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
                raise ImageError("IMAGE_PREPARED_TOO_LARGE")
            return ImageInput(base64.b64encode(output.getvalue()).decode("ascii"))
    except Image.DecompressionBombError:
        raise ImageError("IMAGE_PIXEL_LIMIT") from None
    except (OSError, ValueError):
        raise ImageError("IMAGE_DECODE_FAILED") from None


def test_image() -> ImageInput:
    """A local red square for check-vision; contains no personal data."""
    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (128, 128), (255, 0, 0)).save(output, format="PNG")
    return prepare_image(output.getvalue())
