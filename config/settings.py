from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram Bot Token
    BOT_TOKEN: str = ""

    # Google Gemini API Key(s) (supports single key or comma-separated list)
    GEMINI_API_KEY: str = ""
    GEMINI_API_KEYS: str = ""

    # Primary and fallback Gemini Image Models
    IMAGE_MODEL: str = "gemini-nano-banana-2.1"
    FALLBACK_IMAGE_MODEL: str = "gemini-3.1-flash-image"

    # Text model for social media captions & hashtags (Gemini 3.8 Flash)
    CAPTION_MODEL: str = "gemini-3.8-flash"

    # Rate limiting: Free plan has 2 requests per minute limit
    # 32 seconds ensures we never exceed 2 RPM
    RATE_LIMIT_DELAY: int = 32

    # Retries on 429 Resource Exhausted
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_SECONDS: int = 60

    # Local storage directory
    DATA_DIR: Path = Path("data")

    @property
    def api_keys(self) -> list[str]:
        """Returns all configured Gemini API keys in order without duplicates."""
        keys: list[str] = []
        for raw in [self.GEMINI_API_KEYS, self.GEMINI_API_KEY]:
            if raw:
                for k in raw.split(","):
                    k_clean = k.strip()
                    if k_clean and k_clean not in keys:
                        keys.append(k_clean)
        return keys

    @property
    def image_models(self) -> list[str]:
        """Returns list of image models: primary model followed by fallback models."""
        models: list[str] = []
        if self.IMAGE_MODEL:
            models.append(self.IMAGE_MODEL.strip())
        if self.FALLBACK_IMAGE_MODEL:
            for m in self.FALLBACK_IMAGE_MODEL.split(","):
                m_clean = m.strip()
                if m_clean and m_clean not in models:
                    models.append(m_clean)
        return models


settings = Settings()
