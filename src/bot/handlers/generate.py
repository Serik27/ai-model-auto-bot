import asyncio
import html
import io
import logging
import uuid
from pathlib import Path
from typing import Dict, List
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config.settings import settings
from src.bot.keyboards.inline import (
    get_cancel_keyboard,
    get_confirm_generation_keyboard,
    get_main_menu_keyboard,
    get_post_generation_keyboard,
)
from src.bot.states import GeneratePhotoStates
from src.services.gemini_caption import gemini_caption_service
from src.services.queue_worker import GenerationJob, queue_worker
from src.services.storage import storage_service
from src.utils.image_helper import validate_and_process_image
from src.utils.telegram_helper import safe_edit_message

logger = logging.getLogger(__name__)
router = Router(name="generate_router")

STEP_1_PROMPT = (
    "📸 **Крок 1/3: Поза моделі (фото або текст)**\n\n"
    "• Надішліть **фото** з бажаною позою\n"
    "• АБО опишіть позу **текстом** (наприклад: *'сидить у кріслі, впевнений погляд у камеру'*)\n"
    "• Або натисніть кнопку нижче, щоб **пропустити** (буде обрано природну модельну позу)."
)

STEP_2_PROMPT = (
    "👗 **Крок 2/3: Одяг моделі (фото або текст)**\n\n"
    "• Надішліть **фото** бажаного образу чи сукні\n"
    "• АБО опишіть одяг **текстом** (наприклад: *'елегантний шовковий брючний костюм смарагдового кольору'*)\n"
    "• Або натисніть кнопку нижче, щоб **пропустити** (стильний сучасний лук під атмосферу кадру)."
)

STEP_3_PROMPT = (
    "🏞️ **Крок 3/3: Локація / Фон (фото або текст)**\n\n"
    "• Надішліть **фото** бажаного фону чи інтер'єру\n"
    "• АБО опишіть локацію **текстом** (наприклад: *'панорамний балкон з видом на вечірнє місто'*)\n"
    "• Або натисніть кнопку нижче, щоб **пропустити** (естетична локація з гармонійним освітленням)."
)

STEP_4_PROMPT = (
    "✨ **Додаткові побажання (необов'язково):**\n\n"
    "Напишіть текстом будь-які деталі до фото (наприклад: *'золота година, тепле світло, вітер у волоссі'*), "
    "або натисніть кнопку нижче, щоб пропустити:"
)


@router.message(Command("generate"))
@router.callback_query(F.data == "start_new_photo")
async def start_generation_flow(event: Message | CallbackQuery, state: FSMContext):
    """Starts step-by-step wizard to collect pose, outfit, and background references."""
    user = event.from_user
    if not user:
        return

    profile = storage_service.get_model_profile(user.id)
    if not profile["is_complete"]:
        missing = []
        if not profile["has_face"]:
            missing.append("обличчя")
        if not profile["has_body"]:
            missing.append("фігуру")

        text = (
            f"⚠️ **Увага!** Для генерації потрібно спочатку зберегти: **{', '.join(missing)}** моделі.\n\n"
            "Перейдіть у «👩 Профіль AI-моделі» та завантажте необхідні фото."
        )
        if isinstance(event, CallbackQuery):
            await safe_edit_message(event.message, text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
            await event.answer()
        else:
            await event.answer(text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
        return

    # Clear current draft and start fresh
    storage_service.clear_draft(user.id)
    await state.clear()
    await state.set_state(GeneratePhotoStates.waiting_for_pose)

    if isinstance(event, CallbackQuery):
        await safe_edit_message(event.message, STEP_1_PROMPT, reply_markup=get_cancel_keyboard(show_skip=True), parse_mode="Markdown")
        await event.answer()
    else:
        await event.answer(STEP_1_PROMPT, reply_markup=get_cancel_keyboard(show_skip=True), parse_mode="Markdown")


# --- Step 1: Pose Handlers ---

@router.message(GeneratePhotoStates.waiting_for_pose, F.photo)
async def process_pose_photo(message: Message, state: FSMContext, bot: Bot):
    """Saves pose reference image."""
    photo = message.photo[-1]
    user_id = message.from_user.id

    wait_msg = await message.answer("⏳ Зберігаю референс пози...")
    try:
        file_io = io.BytesIO()
        await bot.download(photo, destination=file_io)
        processed = validate_and_process_image(file_io.getvalue())
        await storage_service.save_draft_image(user_id, "pose", processed)

        await state.update_data(pose_mode="photo", pose_text=None)
        await state.set_state(GeneratePhotoStates.waiting_for_outfit)
        await wait_msg.delete()
        await message.answer(
            STEP_2_PROMPT,
            reply_markup=get_cancel_keyboard(show_skip=True),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error processing pose photo: {e}")
        await wait_msg.edit_text(f"❌ Помилка: {e}", reply_markup=get_cancel_keyboard(show_skip=True))


@router.message(GeneratePhotoStates.waiting_for_pose, F.text)
async def process_pose_text(message: Message, state: FSMContext):
    """Saves pose text description."""
    pose_desc = message.text.strip()
    await state.update_data(pose_mode="text", pose_text=pose_desc)
    await state.set_state(GeneratePhotoStates.waiting_for_outfit)
    await message.answer(
        STEP_2_PROMPT,
        reply_markup=get_cancel_keyboard(show_skip=True),
        parse_mode="Markdown",
    )


@router.callback_query(GeneratePhotoStates.waiting_for_pose, F.data == "skip_step")
async def cb_skip_pose(callback: CallbackQuery, state: FSMContext):
    """Skips pose step and proceeds to outfit."""
    await state.update_data(pose_mode="skipped", pose_text=None)
    await state.set_state(GeneratePhotoStates.waiting_for_outfit)
    await safe_edit_message(
        callback.message,
        STEP_2_PROMPT,
        reply_markup=get_cancel_keyboard(show_skip=True),
        parse_mode="Markdown",
    )
    await callback.answer()


# --- Step 2: Outfit Handlers ---

@router.message(GeneratePhotoStates.waiting_for_outfit, F.photo)
async def process_outfit_photo(message: Message, state: FSMContext, bot: Bot):
    """Saves outfit reference image."""
    photo = message.photo[-1]
    user_id = message.from_user.id

    wait_msg = await message.answer("⏳ Зберігаю референс одягу...")
    try:
        file_io = io.BytesIO()
        await bot.download(photo, destination=file_io)
        processed = validate_and_process_image(file_io.getvalue())
        await storage_service.save_draft_image(user_id, "outfit", processed)

        await state.update_data(outfit_mode="photo", outfit_text=None)
        await state.set_state(GeneratePhotoStates.waiting_for_background)
        await wait_msg.delete()
        await message.answer(
            STEP_3_PROMPT,
            reply_markup=get_cancel_keyboard(show_skip=True),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error processing outfit photo: {e}")
        await wait_msg.edit_text(f"❌ Помилка: {e}", reply_markup=get_cancel_keyboard(show_skip=True))


@router.message(GeneratePhotoStates.waiting_for_outfit, F.text)
async def process_outfit_text(message: Message, state: FSMContext):
    """Saves outfit text description."""
    outfit_desc = message.text.strip()
    await state.update_data(outfit_mode="text", outfit_text=outfit_desc)
    await state.set_state(GeneratePhotoStates.waiting_for_background)
    await message.answer(
        STEP_3_PROMPT,
        reply_markup=get_cancel_keyboard(show_skip=True),
        parse_mode="Markdown",
    )


@router.callback_query(GeneratePhotoStates.waiting_for_outfit, F.data == "skip_step")
async def cb_skip_outfit(callback: CallbackQuery, state: FSMContext):
    """Skips outfit step and proceeds to background."""
    await state.update_data(outfit_mode="skipped", outfit_text=None)
    await state.set_state(GeneratePhotoStates.waiting_for_background)
    await safe_edit_message(
        callback.message,
        STEP_3_PROMPT,
        reply_markup=get_cancel_keyboard(show_skip=True),
        parse_mode="Markdown",
    )
    await callback.answer()


# --- Step 3: Background Handlers ---

@router.message(GeneratePhotoStates.waiting_for_background, F.photo)
async def process_background_photo(message: Message, state: FSMContext, bot: Bot):
    """Saves background reference image."""
    photo = message.photo[-1]
    user_id = message.from_user.id

    wait_msg = await message.answer("⏳ Зберігаю референс фону...")
    try:
        file_io = io.BytesIO()
        await bot.download(photo, destination=file_io)
        processed = validate_and_process_image(file_io.getvalue())
        await storage_service.save_draft_image(user_id, "background", processed)

        await state.update_data(bg_mode="photo", bg_text=None)
        await state.set_state(GeneratePhotoStates.waiting_for_extra_prompt)
        await wait_msg.delete()
        await message.answer(
            STEP_4_PROMPT,
            reply_markup=get_cancel_keyboard(show_skip=True),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error processing background photo: {e}")
        await wait_msg.edit_text(f"❌ Помилка: {e}", reply_markup=get_cancel_keyboard(show_skip=True))


@router.message(GeneratePhotoStates.waiting_for_background, F.text)
async def process_background_text(message: Message, state: FSMContext):
    """Saves background text description."""
    bg_desc = message.text.strip()
    await state.update_data(bg_mode="text", bg_text=bg_desc)
    await state.set_state(GeneratePhotoStates.waiting_for_extra_prompt)
    await message.answer(
        STEP_4_PROMPT,
        reply_markup=get_cancel_keyboard(show_skip=True),
        parse_mode="Markdown",
    )


@router.callback_query(GeneratePhotoStates.waiting_for_background, F.data == "skip_step")
async def cb_skip_background(callback: CallbackQuery, state: FSMContext):
    """Skips background step and proceeds to extra prompt."""
    await state.update_data(bg_mode="skipped", bg_text=None)
    await state.set_state(GeneratePhotoStates.waiting_for_extra_prompt)
    await safe_edit_message(
        callback.message,
        STEP_4_PROMPT,
        reply_markup=get_cancel_keyboard(show_skip=True),
        parse_mode="Markdown",
    )
    await callback.answer()


# --- Step 4: Extra Prompt Handlers ---

@router.message(GeneratePhotoStates.waiting_for_extra_prompt, F.text)
async def process_extra_prompt(message: Message, state: FSMContext):
    """Stores extra prompt guidelines and shows confirmation."""
    extra_text = message.text.strip()
    await state.update_data(extra_prompt=extra_text)
    await show_confirmation_screen(message, state, extra_text)


@router.callback_query(GeneratePhotoStates.waiting_for_extra_prompt, F.data == "skip_step")
async def cb_skip_extra_prompt(callback: CallbackQuery, state: FSMContext):
    """Skips extra prompt and proceeds to confirmation."""
    await state.update_data(extra_prompt=None)
    await show_confirmation_screen(callback.message, state, None)
    await callback.answer()


async def show_confirmation_screen(message: Message, state: FSMContext, extra_notes: str | None):
    """Displays checklist and confirmation buttons."""
    await state.set_state(GeneratePhotoStates.confirm_generation)
    data = await state.get_data()

    pose_mode = data.get("pose_mode", "photo")
    pose_text = data.get("pose_text")
    if pose_mode == "photo":
        pose_display = "✅ Фото"
    elif pose_mode == "text" and pose_text:
        pose_display = f"📝 Текст: `{pose_text[:35]}...`" if len(pose_text) > 35 else f"📝 Текст: `{pose_text}`"
    else:
        pose_display = "⏩ Пропущено (авто)"

    outfit_mode = data.get("outfit_mode", "photo")
    outfit_text = data.get("outfit_text")
    if outfit_mode == "photo":
        outfit_display = "✅ Фото"
    elif outfit_mode == "text" and outfit_text:
        outfit_display = f"📝 Текст: `{outfit_text[:35]}...`" if len(outfit_text) > 35 else f"📝 Текст: `{outfit_text}`"
    else:
        outfit_display = "⏩ Пропущено (авто)"

    bg_mode = data.get("bg_mode", "photo")
    bg_text = data.get("bg_text")
    if bg_mode == "photo":
        bg_display = "✅ Фото"
    elif bg_mode == "text" and bg_text:
        bg_display = f"📝 Текст: `{bg_text[:35]}...`" if len(bg_text) > 35 else f"📝 Текст: `{bg_text}`"
    else:
        bg_display = "⏩ Пропущено (авто)"

    notes_display = f"`{extra_notes}`" if extra_notes else "Не вказано (стандартний фотосет)"

    text = (
        "📋 **Перевірка налаштувань перед генерацією:**\n\n"
        "• 👤 Обличчя моделі: **✅ Готово**\n"
        "• 🧍‍♀️ Фігура/Тіло: **✅ Готово**\n"
        f"• 📸 Поза: **{pose_display}**\n"
        f"• 👗 Одяг: **{outfit_display}**\n"
        f"• 🏞️ Фон: **{bg_display}**\n"
        f"• ✍️ Побажання: {notes_display}\n\n"
        "⏱️ **Ліміт безкоштовного тарифу:** 2 фото/хвилину (пауза ~32с між запитами).\n\n"
        "Оберіть дію 👇"
    )

    await message.answer(text, reply_markup=get_confirm_generation_keyboard(), parse_mode="Markdown")


@router.callback_query(GeneratePhotoStates.confirm_generation, F.data == "confirm_and_launch")
async def cb_confirm_and_launch(callback: CallbackQuery, state: FSMContext):
    """Puts job into generation queue."""
    user_id = callback.from_user.id
    data = await state.get_data()
    extra_prompt = data.get("extra_prompt")

    profile = storage_service.get_model_profile(user_id)
    draft = storage_service.get_draft(user_id)

    if not profile["is_complete"]:
        await callback.answer("Помилка: профіль моделі не заповнено!", show_alert=True)
        return

    pose_mode = data.get("pose_mode", "photo")
    outfit_mode = data.get("outfit_mode", "photo")
    bg_mode = data.get("bg_mode", "photo")

    pose_path = draft["pose"] if pose_mode == "photo" else None
    outfit_path = draft["outfit"] if outfit_mode == "photo" else None
    bg_path = draft["background"] if bg_mode == "photo" else None

    # Check existing batch or create session
    batch_list: List[Dict] = data.get("batch_jobs", [])

    # Create persistent copies for current item
    job_id = str(uuid.uuid4())
    session_id = data.get("session_id", str(uuid.uuid4()))

    status_msg = await safe_edit_message(
        callback.message,
        "⏳ **Додаю завдання до черги генерації...**\nОчікуйте оновлення статусу.",
        parse_mode="Markdown",
    )

    # If there are accumulated batch items
    all_jobs_info = batch_list + [
        {
            "job_id": job_id,
            "face_path": profile["face_path"],
            "body_path": profile["body_path"],
            "pose_path": pose_path,
            "outfit_path": outfit_path,
            "background_path": bg_path,
            "pose_text": data.get("pose_text"),
            "outfit_text": data.get("outfit_text"),
            "background_text": data.get("bg_text"),
            "extra_prompt": extra_prompt,
        }
    ]

    total_batch = len(all_jobs_info)

    for idx, item in enumerate(all_jobs_info, 1):
        job = GenerationJob(
            job_id=item["job_id"],
            user_id=user_id,
            chat_id=callback.message.chat.id,
            session_id=session_id,
            face_path=item["face_path"],
            body_path=item["body_path"],
            pose_path=item.get("pose_path"),
            outfit_path=item.get("outfit_path"),
            background_path=item.get("background_path"),
            pose_text=item.get("pose_text"),
            outfit_text=item.get("outfit_text"),
            background_text=item.get("background_text"),
            extra_prompt=item.get("extra_prompt"),
            status_message_id=status_msg.message_id if idx == 1 else None,
            batch_index=idx,
            batch_total=total_batch,
            auto_generate_captions=True,
        )
        pos = await queue_worker.add_job(job)

    est_wait = (pos - 1) * settings.RATE_LIMIT_DELAY
    await status_msg.edit_text(
        f"✅ **Успішно додано до черги!**\n\n"
        f"• Кількість фото в сесії: **{total_batch}**\n"
        f"• Ваша позиція в черзі: **#{pos}**\n"
        f"• Орієнтовне очікування: **~{est_wait} сек**\n\n"
        "🎨 Як тільки фото буде готове, бот надішле його сюди!",
        parse_mode="Markdown",
    )

    await state.clear()
    await callback.answer("Генерацію запущено!")


@router.callback_query(GeneratePhotoStates.confirm_generation, F.data == "add_another_to_batch")
async def cb_add_another_to_batch(callback: CallbackQuery, state: FSMContext):
    """Saves current draft item to batch list and prompts for next photo references."""
    user_id = callback.from_user.id
    data = await state.get_data()
    profile = storage_service.get_model_profile(user_id)
    draft = storage_service.get_draft(user_id)

    if not profile["is_complete"]:
        await callback.answer("Помилка: профіль моделі не заповнено!", show_alert=True)
        return

    job_id = str(uuid.uuid4())
    batch_dir = storage_service._user_dir(user_id) / "batch_temp" / job_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    pose_mode = data.get("pose_mode", "photo")
    outfit_mode = data.get("outfit_mode", "photo")
    bg_mode = data.get("bg_mode", "photo")

    pose_copy = None
    if pose_mode == "photo" and draft["pose"] and draft["pose"].exists():
        pose_copy = batch_dir / "pose.jpg"
        pose_copy.write_bytes(draft["pose"].read_bytes())

    outfit_copy = None
    if outfit_mode == "photo" and draft["outfit"] and draft["outfit"].exists():
        outfit_copy = batch_dir / "outfit.jpg"
        outfit_copy.write_bytes(draft["outfit"].read_bytes())

    bg_copy = None
    if bg_mode == "photo" and draft["background"] and draft["background"].exists():
        bg_copy = batch_dir / "bg.jpg"
        bg_copy.write_bytes(draft["background"].read_bytes())

    batch_list: List[Dict] = data.get("batch_jobs", [])
    batch_list.append(
        {
            "job_id": job_id,
            "face_path": profile["face_path"],
            "body_path": profile["body_path"],
            "pose_path": pose_copy,
            "outfit_path": outfit_copy,
            "background_path": bg_copy,
            "pose_text": data.get("pose_text"),
            "outfit_text": data.get("outfit_text"),
            "background_text": data.get("bg_text"),
            "extra_prompt": data.get("extra_prompt"),
        }
    )

    session_id = data.get("session_id", str(uuid.uuid4()))
    storage_service.clear_draft(user_id)

    # Update state and start next photo
    await state.clear()
    await state.set_state(GeneratePhotoStates.waiting_for_pose)
    await state.update_data(batch_jobs=batch_list, session_id=session_id)

    await safe_edit_message(
        callback.message,
        f"✅ Фото #{len(batch_list)} збережено в пачку!\n\n"
        f"📸 **Тепер оберіть ПОЗУ (фото або текст) для фото #{len(batch_list) + 1}:**",
        reply_markup=get_cancel_keyboard(show_skip=True),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("caption_session:"))
async def cb_caption_session(callback: CallbackQuery):
    """Generates separate social media captions for Instagram, Threads, and X."""
    session_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    session_images = await storage_service.get_session_images(user_id, session_id)
    if not session_images:
        await callback.answer("У цій сесії ще немає згенерованих фото.", show_alert=True)
        return

    wait_msg = await callback.message.answer(
        f"📝 **Генерую окремі описи для Instagram, Threads та X ({len(session_images)} фото)...**\n"
        "⚡ Використовую пакетний виклик Gemini для економії ліміту API...",
        parse_mode="Markdown",
    )

    try:
        structured = await gemini_caption_service.generate_structured_captions(session_images)
        await wait_msg.delete()

        for item in structured:
            idx = item.get("photo_index", 1)
            prefix = f" (Фото #{idx})" if len(structured) > 1 else ""

            ig_text = item.get("instagram", "").strip()
            if ig_text:
                await callback.message.answer(
                    f"📸 <b>Instagram{prefix}:</b>\n\n{html.escape(ig_text)}",
                    parse_mode="HTML",
                )
                await asyncio.sleep(0.3)

            threads_text = item.get("threads", "").strip()
            if threads_text:
                await callback.message.answer(
                    f"🧵 <b>Threads{prefix}:</b>\n\n{html.escape(threads_text)}",
                    parse_mode="HTML",
                )
                await asyncio.sleep(0.3)

            x_text = item.get("twitter", "").strip()
            if x_text:
                await callback.message.answer(
                    f"🐦 <b>X (Twitter){prefix}:</b>\n\n{html.escape(x_text)}",
                    parse_mode="HTML",
                )
                await asyncio.sleep(0.3)

        await callback.message.answer(
            "✅ <b>Всі тексти надіслано окремо для зручного копіювання!</b>",
            reply_markup=get_post_generation_keyboard(session_id),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Error generating captions: {e}")
        await wait_msg.edit_text(
            f"❌ Помилка генерації описів: {e}",
            reply_markup=get_post_generation_keyboard(session_id),
        )

    await callback.answer()
