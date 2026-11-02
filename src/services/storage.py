import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
import aiofiles
import aiofiles.os

from config.settings import settings

logger = logging.getLogger(__name__)


class StorageService:
    """Manages file storage for AI model references, drafts, and generated results."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or settings.DATA_DIR
        self.users_dir = self.base_dir / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)

    def _user_dir(self, user_id: int) -> Path:
        path = self.users_dir / str(user_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _model_dir(self, user_id: int) -> Path:
        path = self._user_dir(user_id) / "model"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _draft_dir(self, user_id: int) -> Path:
        path = self._user_dir(user_id) / "draft"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _generations_dir(self, user_id: int) -> Path:
        path = self._user_dir(user_id) / "generations"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _sessions_dir(self, user_id: int) -> Path:
        path = self._user_dir(user_id) / "sessions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def save_model_face(self, user_id: int, image_bytes: bytes) -> Path:
        """Saves reference face photo for the AI model."""
        target_path = self._model_dir(user_id) / "face.jpg"
        async with aiofiles.open(target_path, "wb") as f:
            await f.write(image_bytes)
        logger.info(f"Saved face reference for user {user_id} at {target_path}")
        return target_path

    async def save_model_body(self, user_id: int, image_bytes: bytes) -> Path:
        """Saves reference body/figure photo for the AI model."""
        target_path = self._model_dir(user_id) / "body.jpg"
        async with aiofiles.open(target_path, "wb") as f:
            await f.write(image_bytes)
        logger.info(f"Saved body reference for user {user_id} at {target_path}")
        return target_path

    def get_model_profile(self, user_id: int) -> Dict[str, Any]:
        """Returns the status and paths of the saved model profile."""
        model_dir = self._model_dir(user_id)
        face_path = model_dir / "face.jpg"
        body_path = model_dir / "body.jpg"

        has_face = face_path.exists() and face_path.stat().st_size > 0
        has_body = body_path.exists() and body_path.stat().st_size > 0

        return {
            "has_face": has_face,
            "has_body": has_body,
            "is_complete": has_face and has_body,
            "face_path": face_path if has_face else None,
            "body_path": body_path if has_body else None,
        }

    def clear_model_profile(self, user_id: int) -> None:
        """Removes the saved model references for a user."""
        model_dir = self._model_dir(user_id)
        if model_dir.exists():
            shutil.rmtree(model_dir)
            model_dir.mkdir(parents=True, exist_ok=True)

    async def save_draft_image(self, user_id: int, category: str, image_bytes: bytes) -> Path:
        """Saves draft image (pose, outfit, background)."""
        valid_categories = {"pose", "outfit", "background"}
        if category not in valid_categories:
            raise ValueError(f"Invalid category: {category}. Allowed: {valid_categories}")

        target_path = self._draft_dir(user_id) / f"{category}.jpg"
        async with aiofiles.open(target_path, "wb") as f:
            await f.write(image_bytes)
        return target_path

    def get_draft(self, user_id: int) -> Dict[str, Optional[Path]]:
        """Returns paths of currently uploaded draft parts."""
        draft_dir = self._draft_dir(user_id)
        pose_path = draft_dir / "pose.jpg"
        outfit_path = draft_dir / "outfit.jpg"
        bg_path = draft_dir / "background.jpg"

        return {
            "pose": pose_path if pose_path.exists() else None,
            "outfit": outfit_path if outfit_path.exists() else None,
            "background": bg_path if bg_path.exists() else None,
        }

    def clear_draft(self, user_id: int) -> None:
        """Clears draft images."""
        draft_dir = self._draft_dir(user_id)
        if draft_dir.exists():
            shutil.rmtree(draft_dir)
            draft_dir.mkdir(parents=True, exist_ok=True)

    async def save_generated_image(self, user_id: int, image_bytes: bytes, filename: str) -> Path:
        """Saves final generated AI photo."""
        gen_dir = self._generations_dir(user_id)
        target_path = gen_dir / filename
        async with aiofiles.open(target_path, "wb") as f:
            await f.write(image_bytes)
        return target_path

    async def add_to_session(
        self, user_id: int, session_id: str, image_path: Path, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Tracks generated images in the current batch session for caption generation."""
        session_file = self._sessions_dir(user_id) / f"{session_id}.json"
        data: Dict[str, Any] = {"images": []}

        if session_file.exists():
            try:
                async with aiofiles.open(session_file, "r", encoding="utf-8") as f:
                    content = await f.read()
                    data = json.loads(content)
            except Exception as e:
                logger.warning(f"Failed to read session file {session_file}: {e}")

        data["images"].append({
            "path": str(image_path),
            "metadata": metadata or {},
        })

        async with aiofiles.open(session_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False))

    async def get_session_images(self, user_id: int, session_id: str) -> List[Path]:
        """Returns list of image paths from a given session."""
        session_file = self._sessions_dir(user_id) / f"{session_id}.json"
        if not session_file.exists():
            return []

        try:
            async with aiofiles.open(session_file, "r", encoding="utf-8") as f:
                content = await f.read()
                data = json.loads(content)
            paths = [Path(item["path"]) for item in data.get("images", []) if Path(item["path"]).exists()]
            return paths
        except Exception as e:
            logger.error(f"Error reading session {session_id}: {e}")
            return []


storage_service = StorageService()
