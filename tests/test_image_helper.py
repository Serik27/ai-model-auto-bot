import io
import pytest
from PIL import Image
from src.utils.image_helper import validate_and_process_image


def test_validate_and_process_image_normal():
    # Create sample RGB image in memory
    img = Image.new("RGB", (800, 600), color="red")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    raw_bytes = buffer.getvalue()

    result = validate_and_process_image(raw_bytes)
    assert len(result) > 0

    # Verify result is a valid JPEG
    with Image.open(io.BytesIO(result)) as processed_img:
        assert processed_img.size == (800, 600)
        assert processed_img.format == "JPEG"


def test_validate_and_process_image_resize_large():
    # Create sample large image (3000x1500)
    img = Image.new("RGB", (3000, 1500), color="blue")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    raw_bytes = buffer.getvalue()

    result = validate_and_process_image(raw_bytes, max_dim=2048)
    with Image.open(io.BytesIO(result)) as processed_img:
        assert processed_img.width <= 2048
        assert processed_img.height <= 2048
        assert processed_img.width == 2048
        assert processed_img.height == 1024


def test_validate_and_process_image_invalid_bytes():
    with pytest.raises(ValueError):
        validate_and_process_image(b"not an image at all")
