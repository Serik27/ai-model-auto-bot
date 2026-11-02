import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from google import genai
from google.genai import types

from config.settings import settings
from src.utils.image_helper import read_image_bytes

logger = logging.getLogger(__name__)


def extract_json_from_response(text: str) -> Any:
    """Attempts to parse JSON from model output, handling markdown blocks."""
    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if match:
        cleaned = match.group(1).strip()
    else:
        # Try to find first [ or { to last ] or }
        start_bracket = cleaned.find("[")
        start_brace = cleaned.find("{")
        if start_bracket != -1 and (start_brace == -1 or start_bracket < start_brace):
            end_bracket = cleaned.rfind("]")
            if end_bracket != -1:
                cleaned = cleaned[start_bracket : end_bracket + 1]
        elif start_brace != -1:
            end_brace = cleaned.rfind("}")
            if end_brace != -1:
                cleaned = cleaned[start_brace : end_brace + 1]
    return json.loads(cleaned)


class GeminiCaptionService:
    """
    Generates social media captions, hashtags, and creative photo ideas
    in single Gemini calls to conserve API quota.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._custom_api_key = api_key
        self._clients: dict[str, genai.Client] = {}

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
            raise ValueError("GEMINI_API_KEY is not configured in .env!")
        return self.get_client(keys[0])

    async def generate_structured_captions(
        self,
        images: List[Union[bytes, Path]],
        custom_instructions: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Takes a batch of generated images and returns a list of dictionaries with
        separate captions for Instagram, Threads, and X (Twitter) for each image.
        """
        if not images:
            return []

        contents: list = []
        for idx, item in enumerate(images, 1):
            if isinstance(item, Path):
                img_bytes = read_image_bytes(item)
            else:
                img_bytes = item

            contents.append(types.Part.from_text(text=f"[GENERATED PHOTO #{idx}]"))
            contents.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))

        extra_text = f"\nAdditional guidelines: {custom_instructions}" if custom_instructions else ""

        prompt = (
            "You are an expert social media manager for a luxury AI fashion model and digital influencer.\n"
            f"Review the {len(images)} photo(s) provided above. For EACH photo, write a complete, high-converting social media package in English.\n\n"
            "Return your output strictly as a JSON array of objects with this schema:\n"
            "[\n"
            "  {\n"
            '    "photo_index": 1,\n'
            '    "instagram": "Captivating first-person lifestyle caption in English with natural emojis, engaging hook, and call to action.\\n\\n#hashtag1 #hashtag2 (15-20 trending hashtags separated by spaces)",\n'
            '    "threads": "Casual, conversational, engaging Threads caption in English with a viral hook or question.",\n'
            '    "twitter": "Short, witty, high-engagement tweet strictly under 280 characters with 2-3 top hashtags."\n'
            "  }\n"
            "]\n\n"
            "Tailor each caption specifically to the outfit style, lighting, mood, and setting of each photo. "
            f"Do not repeat the exact same sentences across photos.{extra_text}"
        )
        contents.append(types.Part.from_text(text=prompt))

        model = settings.CAPTION_MODEL
        logger.info(f"Generating structured captions for {len(images)} images using {model}...")

        last_error = None
        for key in self.api_keys:
            client = self.get_client(key)
            try:
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )
                raw_text = response.text or ""
                try:
                    data = extract_json_from_response(raw_text)
                    if isinstance(data, list):
                        return data
                except Exception as parse_err:
                    logger.warning(f"Could not parse JSON captions ({parse_err}), falling back to text splitter...")
                    return self._fallback_parse_captions(raw_text, len(images))

            except Exception as e:
                last_error = e
                logger.warning(f"Structured caption generation with key failed ({e}), trying next key if available...")

        raise last_error or RuntimeError("Could not generate captions with available API keys.")

    def _fallback_parse_captions(self, text: str, count: int) -> List[Dict[str, Any]]:
        """Fallback parser if model output was not valid JSON."""
        results = []
        # Try splitting by PHOTO
        photo_blocks = re.split(r"PHOTO\s*#?\d+", text, flags=re.IGNORECASE)
        blocks = [b.strip() for b in photo_blocks if b.strip()]

        if not blocks:
            blocks = [text]

        for idx, block in enumerate(blocks[:count], 1):
            ig_match = re.search(r"(?:INSTAGRAM|IG)[:\s]*(.*?)(?=(?:🏷️|HASHTAGS|HASHTAG|THREADS|🧵|🐦|X|TWITTER|$))", block, re.DOTALL | re.IGNORECASE)
            tags_match = re.search(r"(?:🏷️|HASHTAGS|HASHTAG)[:\s]*(.*?)(?=(?:THREADS|🧵|🐦|X|TWITTER|$))", block, re.DOTALL | re.IGNORECASE)
            threads_match = re.search(r"(?:THREADS|🧵)[:\s]*(.*?)(?=(?:🐦|X|TWITTER|$))", block, re.DOTALL | re.IGNORECASE)
            x_match = re.search(r"(?:🐦|X|TWITTER)[:\s]*(.*?)$", block, re.DOTALL | re.IGNORECASE)

            ig_text = ig_match.group(1).strip() if ig_match else block
            if tags_match:
                ig_text += f"\n\n{tags_match.group(1).strip()}"

            threads_text = threads_match.group(1).strip() if threads_match else ig_text
            x_text = x_match.group(1).strip() if x_match else (ig_text[:250] + "...")

            results.append({
                "photo_index": idx,
                "instagram": ig_text,
                "threads": threads_text,
                "twitter": x_text,
            })

        while len(results) < count:
            results.append({
                "photo_index": len(results) + 1,
                "instagram": text,
                "threads": text,
                "twitter": text[:280],
            })

        return results

    async def generate_batch_captions(
        self,
        images: List[Union[bytes, Path]],
        custom_instructions: Optional[str] = None,
    ) -> str:
        """Backward compatible method that formats structured captions into a single string."""
        structured = await self.generate_structured_captions(images, custom_instructions)
        lines = []
        for item in structured:
            idx = item.get("photo_index", 1)
            lines.append(f"━━━━━━━━━━━━━━━━━━━━━\n📸 PHOTO #{idx}\n━━━━━━━━━━━━━━━━━━━━━\n")
            lines.append(f"✨ INSTAGRAM:\n{item.get('instagram', '')}\n")
            lines.append(f"🧵 THREADS:\n{item.get('threads', '')}\n")
            lines.append(f"🐦 X (TWITTER):\n{item.get('twitter', '')}\n")
        return "\n".join(lines)

    async def generate_photo_ideas(
        self,
        wishes: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generates 10 creative photo shoot concepts for the AI model.
        Returns a list of 10 dicts with title, visual description, professional prompt, and post caption.
        """
        wishes_context = (
            f"The user has specific preferences/theme: \"{wishes}\". Incorporate these desires into the concepts while offering creative variety."
            if wishes
            else "Create 10 high-performing, viral, and stylish concepts across luxury lifestyle, editorial fashion, casual street, night out, fitness, cozy cafe, and tropical travel."
        )

        prompt = (
            "You are an elite creative director and social media strategist for luxury AI virtual models and digital influencers.\n"
            "Generate EXACTLY 10 distinct, visually stunning, high-engagement photo concepts for an AI model.\n\n"
            f"{wishes_context}\n\n"
            "Return your output STRICTLY as a JSON array of exactly 10 objects with this exact structure:\n"
            "[\n"
            "  {\n"
            '    "number": 1,\n'
            '    "title": "Коротка приваблива назва ідеї українською мовою (наприклад: Ранок у пентхаусі)",\n'
            '    "visual_description": "Детальний опис образу українською мовою: поза моделі, одяг, зачіска, локація, освітлення, атмосфера",\n'
            '    "generation_prompt": "A professional English image prompt ready for raw 8K photorealistic generation (shot on Hasselblad 85mm f/1.4, detailed clothing fabrics, natural skin texture, cinematic lighting, ultra-realistic, highly detailed environment)",\n'
            '    "post_caption": "Engaging lifestyle caption in English with natural emojis, intriguing hook, and question + 10-15 trending hashtags separated by spaces"\n'
            "  }\n"
            "]\n\n"
            "Ensure every prompt is masterfully detailed and ready to copy-paste for generation."
        )

        model = settings.CAPTION_MODEL
        logger.info(f"Generating 10 photo ideas using {model}...")

        last_error = None
        for key in self.api_keys:
            client = self.get_client(key)
            try:
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )
                raw_text = response.text or ""
                data = extract_json_from_response(raw_text)
                if isinstance(data, list) and len(data) > 0:
                    return data
            except Exception as e:
                last_error = e
                logger.warning(f"Ideas generation with key failed ({e}), trying next key if available...")

        raise last_error or RuntimeError("Could not generate photo ideas with available API keys.")


gemini_caption_service = GeminiCaptionService()
