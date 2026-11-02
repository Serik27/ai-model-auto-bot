import io
import logging
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image

logger = logging.getLogger(__name__)

MAX_DIMENSION = 2048
JPEG_QUALITY = 90


def validate_and_process_image(
    image_bytes: bytes, max_dim: int = MAX_DIMENSION, quality: int = JPEG_QUALITY
) -> bytes:
    """
    Validates that bytes represent a valid image, converts to RGB if needed,
    resizes if larger than max_dim, and returns clean JPEG bytes.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.verify()
    except Exception as e:
        raise ValueError(f"Uploaded file is not a valid image: {e}")

    # Re-open for actual processing (verify closes or invalidates the image pointer)
    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize proportionally if too large
        width, height = img.size
        if width > max_dim or height > max_dim:
            if width > height:
                new_width = max_dim
                new_height = int(height * (max_dim / width))
            else:
                new_height = max_dim
                new_width = int(width * (max_dim / height))
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            logger.info(f"Resized image from {width}x{height} to {new_width}x{new_height}")

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()


def read_image_bytes(path: Path) -> bytes:
    """Reads image file from disk and returns raw bytes."""
    with open(path, "rb") as f:
        return f.read()


def get_image_dimensions(path: Path) -> Optional[Tuple[int, int]]:
    """Returns (width, height) of an image file."""
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None
