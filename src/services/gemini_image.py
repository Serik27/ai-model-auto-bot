import io
import logging
import re
import time
from typing import Dict, List, Optional, Tuple
from google import genai
from google.genai import types
from PIL import Image

from config.settings import settings

logger = logging.getLogger(__name__)


class GeminiDailyQuotaError(Exception):
    """Raised when Google Gemini Free Tier daily quota (RPD) is exhausted."""

    def __init__(
        self,
        retry_message: Optional[str] = None,
        retry_delay_seconds: Optional[int] = None,
        wait_text: Optional[str] = None,
    ):
        self.retry_message = retry_message
        self.retry_delay_seconds = retry_delay_seconds
        self.wait_text = wait_text or format_wait_time(retry_delay_seconds, retry_message)
        super().__init__(
            f"Google Gemini Free Tier daily image quota exhausted. Reset in: {self.wait_text}"
        )


class GeminiRateLimitError(Exception):
    """Raised when short-term rate limit (RPM, e.g. 2 requests/minute) is hit."""

    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Gemini API rate limit (RPM) hit. Retry after {retry_after}s.")


def parse_gemini_error(e: Exception) -> Tuple[bool, bool, Optional[str], Optional[int]]:
    """
    Parses a Gemini API exception to determine if it's a 429 rate limit
    and whether it represents a daily quota exhaustion vs a transient per-minute limit.
    Returns: (is_rate_limit, is_daily_quota, retry_message, retry_delay_seconds)
    """
    err_str = str(e)
    err_lower = err_str.lower()
    is_429 = "429" in err_str or "resource_exhausted" in err_lower or "quota" in err_lower

    if not is_429:
        return False, False, None, None

    is_daily = (
        "requestsperday" in err_lower
        or "free_tier_requests, limit: 0" in err_lower
        or "dayperproject" in err_lower
    )

    match_msg = re.search(r"Please retry in ([^\.]+)", err_str)
    retry_message = match_msg.group(1).strip() if match_msg else None

    match_delay = re.search(r"'retryDelay':\s*'(\d+)s'", err_str)
    retry_delay_seconds = int(match_delay.group(1)) if match_delay else None

    # If retry delay is longer than 2 minutes (e.g. 6000s = 1.6h), it's a daily limit
    if retry_delay_seconds and retry_delay_seconds > 120:
        is_daily = True

    return True, is_daily, retry_message, retry_delay_seconds


def format_wait_time(
    retry_delay_seconds: Optional[int] = None, retry_message: Optional[str] = None
) -> str:
    """Formats human-friendly remaining wait time in Ukrainian."""
    if retry_delay_seconds:
        hours = retry_delay_seconds // 3600
        minutes = (retry_delay_seconds % 3600) // 60
        if hours > 0:
            return f"~{hours} год {minutes} хв"
        elif minutes > 0:
            return f"~{minutes} хв"
        else:
            return f"~{retry_delay_seconds} сек"
    if retry_message:
        return f"~{retry_message}"
    return "найближчим часом (оновлення о 00:00 UTC / 03:00 за Києвом)"


class GeminiImageService:
    """
    Handles image generation and multimodal multi-reference editing
    using Gemini Image models with automatic key rotation and model fallback.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._custom_api_key = api_key
        self._clients: Dict[str, genai.Client] = {}
        self._exhausted_keys: Dict[str, float] = {}  # api_key -> reset_timestamp

    @property
    def api_keys(self) -> List[str]:
        if self._custom_api_key:
            return [self._custom_api_key]
        return settings.api_keys

    @property
    def api_key(self) -> str:
        keys = self.api_keys
        return keys[0] if keys else ""

    def get_client(self, api_key: str) -> genai.Client:
        if api_key not in self._clients:
            self._clients[api_key] = genai.Client(api_key=api_key)
        return self._clients[api_key]

    @property
    def client(self) -> genai.Client:
        keys = self.api_keys
        if not keys:
            raise ValueError(
                "GEMINI_API_KEY is not configured! Please provide it in the .env file."
            )
        return self.get_client(keys[0])

    def get_active_keys(self) -> List[str]:
        """Returns API keys that have not hit daily quota, or whose quota has reset."""
        now = time.time()
        available = []
        for key in self.api_keys:
            reset_time = self._exhausted_keys.get(key, 0.0)
            if now >= reset_time:
                available.append(key)
        return available or self.api_keys

    def mark_key_exhausted(self, key: str, retry_delay_seconds: Optional[int] = None):
        """Marks a key as exhausted for the specified duration or until reset."""
        delay = retry_delay_seconds if retry_delay_seconds and retry_delay_seconds > 0 else 7200
        self._exhausted_keys[key] = time.time() + delay
        logger.warning(
            f"Marked API key (...{key[-6:] if len(key) >= 6 else 'key'}) as exhausted for {delay}s"
        )

    def build_generation_prompt(
        self,
        extra_notes: Optional[str] = None,
        has_pose_image: bool = True,
        has_outfit_image: bool = True,
        has_background_image: bool = True,
        pose_text: Optional[str] = None,
        outfit_text: Optional[str] = None,
        background_text: Optional[str] = None,
    ) -> str:
        """Constructs a professional prompt for character and setting consistency."""
        notes = f"\nAdditional styling requirements: {extra_notes}" if extra_notes else ""

        # Pose instruction
        if has_pose_image:
            pose_desc = (
                "3. REFERENCE 3 (POSE REFERENCE):\n"
                "- Place the woman in the exact posture, body orientation, limb positioning, head angle, and gesture shown in Reference 3."
            )
        elif pose_text:
            pose_desc = f"3. POSE REQUIREMENT:\n- {pose_text}"
        else:
            pose_desc = "3. POSE REQUIREMENT:\n- Natural, flattering, professional fashion model posture suited to the scene."

        # Outfit instruction
        if has_outfit_image:
            outfit_desc = (
                "4. REFERENCE 4 (OUTFIT / CLOTHING REFERENCE):\n"
                "- Dress her in the exact clothing items, fabrics, styling, patterns, and colors shown in Reference 4. The garments must fit her body naturally."
            )
        elif outfit_text:
            outfit_desc = f"4. OUTFIT / CLOTHING REQUIREMENT:\n- {outfit_text}"
        else:
            outfit_desc = "4. OUTFIT / CLOTHING REQUIREMENT:\n- Modern, highly stylish and fashionable outfit suited to the scene."

        # Background instruction
        if has_background_image:
            bg_desc = (
                "5. REFERENCE 5 (BACKGROUND / SETTING REFERENCE):\n"
                "- Place her seamlessly inside the scene, environment, and background shown in Reference 5. Match the depth of field, perspective, light source direction, ambient coloring, and shadows."
            )
        elif background_text:
            bg_desc = f"5. BACKGROUND / SETTING REQUIREMENT:\n- {background_text}"
        else:
            bg_desc = "5. BACKGROUND / SETTING REQUIREMENT:\n- Aesthetic, photorealistic lifestyle or studio environment with cinematic lighting and soft depth of field."

        return (
            "TASK: Generate a single photorealistic, raw 8K photograph of the woman combining all references provided:\n\n"
            "1. REFERENCE 1 (FACE REFERENCE):\n"
            "- Exactly preserve facial identity: eye shape and color, eyebrows, nose, lips, jawline, skin tone, and hair color/texture.\n"
            "- The generated face MUST be 100% identical and instantly recognizable as the woman in Reference 1.\n\n"
            "2. REFERENCE 2 (BODY / FIGURE REFERENCE):\n"
            "- Faithfully match the body proportions, waistline, curves, height, and overall physique of the woman in Reference 2.\n\n"
            f"{pose_desc}\n\n"
            f"{outfit_desc}\n\n"
            f"{bg_desc}\n\n"
            f"AESTHETIC & QUALITY: Editorial fashion photoshoot, Hasselblad raw quality, realistic skin pores, lifelike lighting, zero artificial smoothness.{notes}"
        )

    async def generate_consistent_photo(
        self,
        face_bytes: bytes,
        body_bytes: bytes,
        pose_bytes: Optional[bytes] = None,
        outfit_bytes: Optional[bytes] = None,
        background_bytes: Optional[bytes] = None,
        pose_text: Optional[str] = None,
        outfit_text: Optional[str] = None,
        background_text: Optional[str] = None,
        extra_notes: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> bytes:
        """
        Generates a photo maintaining face, body, and customizable pose, outfit, and background.
        Supports automatic API key rotation and model fallback on quota limits or errors.
        """
        available_keys = self.get_active_keys()
        if not available_keys:
            raise ValueError("No Gemini API keys configured in .env!")

        models_to_try = [model_name] if model_name else settings.image_models

        prompt = self.build_generation_prompt(
            extra_notes=extra_notes,
            has_pose_image=bool(pose_bytes),
            has_outfit_image=bool(outfit_bytes),
            has_background_image=bool(background_bytes),
            pose_text=pose_text,
            outfit_text=outfit_text,
            background_text=background_text,
        )

        contents = [
            types.Part.from_text(text="[REFERENCE 1: FACE OF MODEL]"),
            types.Part.from_bytes(data=face_bytes, mime_type="image/jpeg"),
            types.Part.from_text(text="[REFERENCE 2: BODY & FIGURE OF MODEL]"),
            types.Part.from_bytes(data=body_bytes, mime_type="image/jpeg"),
        ]

        if pose_bytes:
            contents.append(types.Part.from_text(text="[REFERENCE 3: TARGET POSE]"))
            contents.append(types.Part.from_bytes(data=pose_bytes, mime_type="image/jpeg"))

        if outfit_bytes:
            contents.append(types.Part.from_text(text="[REFERENCE 4: TARGET OUTFIT / CLOTHES]"))
            contents.append(types.Part.from_bytes(data=outfit_bytes, mime_type="image/jpeg"))

        if background_bytes:
            contents.append(types.Part.from_text(text="[REFERENCE 5: TARGET BACKGROUND]"))
            contents.append(types.Part.from_bytes(data=background_bytes, mime_type="image/jpeg"))

        contents.append(types.Part.from_text(text=prompt))

        last_exception: Optional[Exception] = None
        last_daily_info: Optional[Tuple[Optional[str], Optional[int]]] = None

        for key_idx, key in enumerate(available_keys):
            client = self.get_client(key)
            key_tag = f"...{key[-6:]}" if len(key) >= 6 else "key"

            for model in models_to_try:
                try:
                    logger.info(
                        f"Calling Gemini API with model: {model} (key: {key_tag})"
                    )

                    response = await client.aio.models.generate_content(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            response_modalities=[types.Modality.IMAGE, types.Modality.TEXT],
                            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                                disable=True
                            ),
                        ),
                    )

                    # Extract generated image bytes
                    if response.candidates and response.candidates[0].content:
                        for part in response.candidates[0].content.parts:
                            if part.inline_data and part.inline_data.data:
                                logger.info(
                                    f"Successfully received generated image using model {model}"
                                )
                                return part.inline_data.data

                    raise RuntimeError("Model response did not contain image data in candidates.")

                except Exception as e:
                    last_exception = e
                    is_rate_limit, is_daily, retry_msg, retry_secs = parse_gemini_error(e)

                    if is_daily:
                        last_daily_info = (retry_msg, retry_secs)
                        logger.warning(
                            f"Daily quota exhausted on key {key_tag} for model {model}. "
                            f"Reset in {retry_msg or retry_secs}s."
                        )
                        self.mark_key_exhausted(key, retry_secs)
                        # Switch to next key immediately instead of trying more models on same exhausted project
                        break

                    if is_rate_limit:
                        logger.warning(
                            f"Per-minute rate limit hit on model {model} (key {key_tag})."
                        )
                        # Transient RPM limit - let the queue worker backoff
                        raise GeminiRateLimitError(retry_after=retry_secs or settings.RETRY_BACKOFF_SECONDS)

                    logger.warning(
                        f"Generation with model {model} failed ({e}). Trying fallback model..."
                    )

        # If all keys/models exhausted
        if last_daily_info:
            retry_msg, retry_secs = last_daily_info
            raise GeminiDailyQuotaError(
                retry_message=retry_msg,
                retry_delay_seconds=retry_secs,
            )

        if last_exception:
            raise last_exception

        raise RuntimeError("No available Gemini model or API key could complete the generation.")


gemini_image_service = GeminiImageService()
