import asyncio
import html
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from config.settings import settings
from src.services.gemini_image import (
    gemini_image_service,
    GeminiDailyQuotaError,
    GeminiRateLimitError,
    parse_gemini_error,
    format_wait_time,
)
from src.services.gemini_caption import gemini_caption_service
from src.services.storage import storage_service
from src.utils.image_helper import read_image_bytes

logger = logging.getLogger(__name__)


@dataclass
class GenerationJob:
    job_id: str
    user_id: int
    chat_id: int
    session_id: str
    face_path: Path
    body_path: Path
    pose_path: Optional[Path] = None
    outfit_path: Optional[Path] = None
    background_path: Optional[Path] = None
    pose_text: Optional[str] = None
    outfit_text: Optional[str] = None
    background_text: Optional[str] = None
    extra_prompt: Optional[str] = None
    status_message_id: Optional[int] = None
    batch_index: int = 1
    batch_total: int = 1
    auto_generate_captions: bool = False


class GenerationQueueWorker:
    """
    Asynchronous FIFO Queue worker that enforces strict rate limits
    (2 RPM = 32s delay between generations) to stay within Google's free tier.
    """

    def __init__(self):
        self.queue: asyncio.Queue[GenerationJob] = asyncio.Queue()
        self.last_call_time: float = 0.0
        self.worker_task: Optional[asyncio.Task] = None
        self.bot: Optional[Bot] = None
        self.active_jobs_count: int = 0

    def start(self, bot: Bot):
        self.bot = bot
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._process_queue())
            logger.info("GenerationQueueWorker started successfully.")

    async def add_job(self, job: GenerationJob) -> int:
        """Adds a job to the queue and returns current queue position."""
        await self.queue.put(job)
        queue_len = self.queue.qsize()
        logger.info(
            f"Job {job.job_id} queued for user {job.user_id}. Position in queue: {queue_len}"
        )
        return queue_len

    def get_queue_size(self) -> int:
        return self.queue.qsize()

    async def _wait_for_rate_limit(self, job: GenerationJob):
        """Enforces minimum interval between image generation requests."""
        now = time.time()
        elapsed = now - self.last_call_time
        required_delay = float(settings.RATE_LIMIT_DELAY)

        if elapsed < required_delay and self.last_call_time > 0:
            wait_time = required_delay - elapsed
            logger.info(
                f"Rate limit enforcement: waiting {wait_time:.1f}s before processing next job"
            )
            if self.bot and job.status_message_id:
                try:
                    await self.bot.edit_message_text(
                        chat_id=job.chat_id,
                        message_id=job.status_message_id,
                        text=(
                            f"⏳ **В черзі генерації** (Фото {job.batch_index}/{job.batch_total})\n\n"
                            f"⏱️ Очікування перед запуском: **~{int(wait_time)} сек**\n"
                            "_(Дотримання безкоштовного ліміту Gemini API: 2 запити/хв)_"
                        ),
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

            await asyncio.sleep(wait_time)

    async def _process_queue(self):
        """Worker loop that continuously processes generation jobs one by one."""
        while True:
            job: GenerationJob = await self.queue.get()
            self.active_jobs_count += 1

            try:
                await self._execute_job(job)
            except Exception as e:
                logger.error(f"Unexpected error executing job {job.job_id}: {e}", exc_info=True)
                if self.bot:
                    try:
                        await self.bot.send_message(
                            chat_id=job.chat_id,
                            text=f"❌ Сталася неочікувана помилка під час обробки завдання: {e}",
                        )
                    except Exception:
                        pass
            finally:
                self.active_jobs_count -= 1
                self.queue.task_done()

    async def _execute_job(self, job: GenerationJob):
        """Executes a single image generation job with retries and rate limiting."""
        if not self.bot:
            logger.error("Bot instance not set in queue worker!")
            return

        # 1. Wait for rate limit interval
        await self._wait_for_rate_limit(job)

        # 2. Update Telegram status message
        if job.status_message_id:
            try:
                await self.bot.edit_message_text(
                    chat_id=job.chat_id,
                    message_id=job.status_message_id,
                    text=(
                        f"🎨 **Генерація фото {job.batch_index}/{job.batch_total}...**\n\n"
                        "🔄 Поєдную обличчя, фігуру, одяг, позу та фон моделі через Gemini Nano Banana AI...\n"
                        "⏳ Зачекайте декілька секунд..."
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        # 3. Read input image files
        try:
            face_bytes = read_image_bytes(job.face_path)
            body_bytes = read_image_bytes(job.body_path)
            pose_bytes = read_image_bytes(job.pose_path) if job.pose_path and job.pose_path.exists() else None
            outfit_bytes = read_image_bytes(job.outfit_path) if job.outfit_path and job.outfit_path.exists() else None
            bg_bytes = read_image_bytes(job.background_path) if job.background_path and job.background_path.exists() else None
        except Exception as e:
            await self.bot.send_message(
                chat_id=job.chat_id,
                text=f"❌ Помилка читання файлів референсів: {e}",
            )
            return

        # 4. Attempt generation with retry on 429
        max_attempts = settings.MAX_RETRIES
        generated_bytes = None

        for attempt in range(1, max_attempts + 1):
            try:
                self.last_call_time = time.time()
                generated_bytes = await gemini_image_service.generate_consistent_photo(
                    face_bytes=face_bytes,
                    body_bytes=body_bytes,
                    pose_bytes=pose_bytes,
                    outfit_bytes=outfit_bytes,
                    background_bytes=bg_bytes,
                    pose_text=job.pose_text,
                    outfit_text=job.outfit_text,
                    background_text=job.background_text,
                    extra_notes=job.extra_prompt,
                )
                break
            except GeminiDailyQuotaError as e:
                logger.error(f"Gemini API daily quota exhausted: {e}")
                quota_msg = (
                    "⚠️ **Вичерпано добовий ліміт запитів Gemini API**\n\n"
                    "Google встановлює денне обмеження безкоштовних генерацій зображень (Daily Quota).\n\n"
                    f"⏱️ **Оновлення квоти:** через **{e.wait_text}** (скидання о 00:00 UTC / 03:00 за Києвом).\n\n"
                    "💡 **Як продовжити генерацію прямо зараз:**\n"
                    "1. Додайте новий/інший безкоштовний ключ `GEMINI_API_KEY` (з іншого Google акаунту) у файл `.env`\n"
                    "2. Можна вказати кілька ключів через кому: `GEMINI_API_KEY=ключ1,ключ2` — бот автоматично перемикатиметься між ними!\n"
                    "3. Або зачекайте до скидання добового ліміту."
                )
                if job.status_message_id:
                    try:
                        await self.bot.edit_message_text(
                            chat_id=job.chat_id,
                            message_id=job.status_message_id,
                            text=quota_msg,
                            parse_mode="Markdown",
                        )
                    except Exception:
                        await self.bot.send_message(chat_id=job.chat_id, text=quota_msg, parse_mode="Markdown")
                else:
                    await self.bot.send_message(chat_id=job.chat_id, text=quota_msg, parse_mode="Markdown")
                return

            except GeminiRateLimitError as e:
                if attempt < max_attempts:
                    backoff = max(e.retry_after, settings.RETRY_BACKOFF_SECONDS)
                    logger.warning(
                        f"Gemini API rate limit hit on attempt {attempt}. Retrying in {backoff}s..."
                    )
                    try:
                        if job.status_message_id:
                            await self.bot.edit_message_text(
                                chat_id=job.chat_id,
                                message_id=job.status_message_id,
                                text=(
                                    f"⚠️ **Досягнуто ліміт швидкості Gemini API (2 RPM).**\n\n"
                                    f"Очікую {backoff} секунд перед повторною спробою ({attempt}/{max_attempts})..."
                                ),
                                parse_mode="Markdown",
                            )
                    except Exception:
                        pass
                    await asyncio.sleep(backoff)
                else:
                    logger.error(f"Generation rate limit exceeded after {max_attempts} attempts.")
                    fail_msg = (
                        "❌ **Перевищено ліміт запитів до Gemini API (2 RPM).**\n\n"
                        "Зачекайте 1 хвилину та спробуйте створити фото знову."
                    )
                    if job.status_message_id:
                        try:
                            await self.bot.edit_message_text(
                                chat_id=job.chat_id,
                                message_id=job.status_message_id,
                                text=fail_msg,
                                parse_mode="Markdown",
                            )
                        except Exception:
                            await self.bot.send_message(chat_id=job.chat_id, text=fail_msg, parse_mode="Markdown")
                    else:
                        await self.bot.send_message(chat_id=job.chat_id, text=fail_msg, parse_mode="Markdown")
                    return

            except Exception as e:
                is_rate_limit, is_daily, retry_msg, retry_secs = parse_gemini_error(e)
                if is_daily:
                    wait_str = format_wait_time(retry_secs, retry_msg)
                    logger.error(f"Gemini API daily quota hit: {e}")
                    quota_msg = (
                        "⚠️ **Вичерпано добовий ліміт запитів Gemini API**\n\n"
                        "Google встановлює денне обмеження безкоштовних генерацій зображень (Daily Quota).\n\n"
                        f"⏱️ **Оновлення квоти:** через **{wait_str}** (скидання о 00:00 UTC / 03:00 за Києвом).\n\n"
                        "💡 **Як продовжити генерацію прямо зараз:**\n"
                        "1. Додайте новий ключ `GEMINI_API_KEY` (з іншого Google акаунту) у файл `.env`\n"
                        "2. Можна вказати кілька ключів через кому: `GEMINI_API_KEY=key1,key2`\n"
                        "3. Або зачекайте до скидання добового ліміту."
                    )
                    if job.status_message_id:
                        try:
                            await self.bot.edit_message_text(
                                chat_id=job.chat_id,
                                message_id=job.status_message_id,
                                text=quota_msg,
                                parse_mode="Markdown",
                            )
                        except Exception:
                            await self.bot.send_message(chat_id=job.chat_id, text=quota_msg, parse_mode="Markdown")
                    else:
                        await self.bot.send_message(chat_id=job.chat_id, text=quota_msg, parse_mode="Markdown")
                    return

                if is_rate_limit and attempt < max_attempts:
                    backoff = settings.RETRY_BACKOFF_SECONDS
                    logger.warning(
                        f"Gemini API rate limit hit on attempt {attempt}. Retrying in {backoff}s..."
                    )
                    try:
                        if job.status_message_id:
                            await self.bot.edit_message_text(
                                chat_id=job.chat_id,
                                message_id=job.status_message_id,
                                text=(
                                    f"⚠️ **Досягнуто ліміт Gemini API (2 RPM).**\n\n"
                                    f"Очікую {backoff} секунд перед повторною спробою ({attempt}/{max_attempts})..."
                                ),
                                parse_mode="Markdown",
                            )
                    except Exception:
                        pass
                    await asyncio.sleep(backoff)
                else:
                    logger.error(f"Generation failed after attempt {attempt}: {e}")
                    err_clean = str(e)
                    if len(err_clean) > 250:
                        err_clean = err_clean[:250] + "..."
                    fail_msg = (
                        f"❌ **Помилка генерації зображення:**\n`{err_clean}`\n\n"
                        "💡 Перевірте валідність `GEMINI_API_KEY` або спробуйте пізніше."
                    )
                    if job.status_message_id:
                        try:
                            await self.bot.edit_message_text(
                                chat_id=job.chat_id,
                                message_id=job.status_message_id,
                                text=fail_msg,
                                parse_mode="Markdown",
                            )
                        except Exception:
                            await self.bot.send_message(chat_id=job.chat_id, text=fail_msg, parse_mode="Markdown")
                    else:
                        await self.bot.send_message(chat_id=job.chat_id, text=fail_msg, parse_mode="Markdown")
                    return

        if not generated_bytes:
            return

        # 5. Save generated image to disk
        filename = f"{int(time.time())}_{job.job_id[:8]}.jpg"
        saved_path = await storage_service.save_generated_image(
            user_id=job.user_id,
            image_bytes=generated_bytes,
            filename=filename,
        )

        # 6. Add to session history for batch captioning
        await storage_service.add_to_session(
            user_id=job.user_id,
            session_id=job.session_id,
            image_path=saved_path,
            metadata={"job_id": job.job_id, "extra_prompt": job.extra_prompt},
        )

        # 7. Send the photo to the user in Telegram
        caption_text = (
            f"✨ **Фото AI-моделі згенеровано!** (Фото {job.batch_index}/{job.batch_total})\n\n"
            f"👤 Обличчя та тіло моделі збережено\n"
            f"👗 Одяг, позу та фон адаптовано\n"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📝 Описи та хештеги для сесії",
                        callback_data=f"caption_session:{job.session_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="✨ Створити ще одне фото",
                        callback_data="start_new_photo",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🏠 Головне меню",
                        callback_data="main_menu",
                    )
                ],
            ]
        )

        await self.bot.send_photo(
            chat_id=job.chat_id,
            photo=FSInputFile(str(saved_path)),
            caption=caption_text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

        # Delete or update status message
        if job.status_message_id:
            try:
                await self.bot.delete_message(chat_id=job.chat_id, message_id=job.status_message_id)
            except Exception:
                pass

        # 8. If batch is completed and auto_generate_captions is True, generate captions
        if job.auto_generate_captions and job.batch_index == job.batch_total:
            await self._trigger_batch_captions(job.user_id, job.chat_id, job.session_id)

    async def _trigger_batch_captions(self, user_id: int, chat_id: int, session_id: str):
        """Automatically generates captions for all photos in the session, sent separately per platform."""
        if not self.bot:
            return

        session_images = await storage_service.get_session_images(user_id, session_id)
        if not session_images:
            return

        status_msg = await self.bot.send_message(
            chat_id=chat_id,
            text=f"📝 **Генерую окремі описи для Instagram, Threads та X ({len(session_images)} фото)...**",
            parse_mode="Markdown",
        )

        try:
            structured_captions = await gemini_caption_service.generate_structured_captions(session_images)
            try:
                await self.bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
            except Exception:
                pass

            for item in structured_captions:
                idx = item.get("photo_index", 1)
                prefix = f" (Фото #{idx})" if len(structured_captions) > 1 else ""

                ig_text = item.get("instagram", "").strip()
                if ig_text:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=f"📸 <b>Instagram{prefix}:</b>\n\n{html.escape(ig_text)}",
                        parse_mode="HTML",
                    )
                    await asyncio.sleep(0.3)

                threads_text = item.get("threads", "").strip()
                if threads_text:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=f"🧵 <b>Threads{prefix}:</b>\n\n{html.escape(threads_text)}",
                        parse_mode="HTML",
                    )
                    await asyncio.sleep(0.3)

                x_text = item.get("twitter", "").strip()
                if x_text:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=f"🐦 <b>X (Twitter){prefix}:</b>\n\n{html.escape(x_text)}",
                        parse_mode="HTML",
                    )
                    await asyncio.sleep(0.3)

            await self.bot.send_message(
                chat_id=chat_id,
                text="✅ <b>Всі тексти надіслано окремо для швидкого копіювання!</b>",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✨ Створити ще одне фото",
                                callback_data="start_new_photo",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="🏠 Головне меню",
                                callback_data="main_menu",
                            )
                        ],
                    ]
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Failed to generate batch captions: {e}")
            try:
                await self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_msg.message_id,
                    text=f"❌ Помилка генерації описів: {e}",
                )
            except Exception:
                pass


queue_worker = GenerationQueueWorker()
