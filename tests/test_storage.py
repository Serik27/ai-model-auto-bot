import pytest
import io
from pathlib import Path
from PIL import Image
from src.services.storage import StorageService


@pytest.fixture
def temp_storage(tmp_path: Path):
    return StorageService(base_dir=tmp_path)


def sample_image_bytes() -> bytes:
    img = Image.new("RGB", (100, 100), color="green")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_storage_model_lifecycle(temp_storage: StorageService):
    user_id = 99999

    # Initially empty
    profile = temp_storage.get_model_profile(user_id)
    assert not profile["has_face"]
    assert not profile["has_body"]
    assert not profile["is_complete"]

    # Save face
    face_path = await temp_storage.save_model_face(user_id, sample_image_bytes())
    assert face_path.exists()
    profile = temp_storage.get_model_profile(user_id)
    assert profile["has_face"]
    assert not profile["has_body"]
    assert not profile["is_complete"]

    # Save body
    body_path = await temp_storage.save_model_body(user_id, sample_image_bytes())
    assert body_path.exists()
    profile = temp_storage.get_model_profile(user_id)
    assert profile["has_face"]
    assert profile["has_body"]
    assert profile["is_complete"]

    # Clear profile
    temp_storage.clear_model_profile(user_id)
    profile = temp_storage.get_model_profile(user_id)
    assert not profile["has_face"]
    assert not profile["has_body"]


@pytest.mark.asyncio
async def test_storage_draft_and_sessions(temp_storage: StorageService):
    user_id = 88888
    img_bytes = sample_image_bytes()

    # Save draft parts
    await temp_storage.save_draft_image(user_id, "pose", img_bytes)
    await temp_storage.save_draft_image(user_id, "outfit", img_bytes)
    await temp_storage.save_draft_image(user_id, "background", img_bytes)

    draft = temp_storage.get_draft(user_id)
    assert draft["pose"] is not None
    assert draft["outfit"] is not None
    assert draft["background"] is not None

    # Save generated image and session
    gen_path = await temp_storage.save_generated_image(user_id, img_bytes, "test_gen.jpg")
    assert gen_path.exists()

    session_id = "test-session-123"
    await temp_storage.add_to_session(user_id, session_id, gen_path)
    session_images = await temp_storage.get_session_images(user_id, session_id)
    assert len(session_images) == 1
    assert session_images[0] == gen_path
