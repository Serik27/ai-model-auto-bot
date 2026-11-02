import io
import logging
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from src.bot.keyboards.inline import (
    get_cancel_keyboard,
    get_main_menu_keyboard,
    get_model_profile_keyboard,
)
from src.bot.states import ModelSetupStates
from src.services.storage import storage_service
from src.utils.image_helper import validate_and_process_image
from src.utils.telegram_helper import safe_edit_message

logger = logging.getLogger(__name__)
router = Router(name="model_router")


@router.callback_query(F.data == "view_model_profile")
async def cb_view_model_profile(callback: CallbackQuery, state: FSMContext):
    """Displays current status of the AI model profile."""
    await state.clear()
    user_id = callback.from_user.id
    profile = storage_service.get_model_profile(user_id)

    face_status = "✅ Завантажено" if profile["has_face"] else "❌ Не задано"
    body_status = "✅ Завантажено" if profile["has_body"] else "❌ Не задано"

    text = (
        "👩 **Профіль вашої AI-моделі:**\n\n"
        f"• 👤 Обличчя: **{face_status}**\n"
        f"• 🧍‍♀️ Фігура/Тіло: **{body_status}**\n\n"
        "💡 Для якісної генерації потрібні обидва фото:\n"
        "- **Обличчя**: чіткий портрет спереду або під кутом 45° при хорошому світлі.\n"
        "- **Тіло**: фото на повний зріст або по пояс для фіксації фігури та пропорцій."
    )

    await safe_edit_message(
        callback.message,
        text,
        reply_markup=get_model_profile_keyboard(profile["has_face"], profile["has_body"]),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data == "set_face")
async def cb_set_face(callback: CallbackQuery, state: FSMContext):
    """Initiates face photo upload state."""
    await state.set_state(ModelSetupStates.waiting_for_face)
    await safe_edit_message(
        callback.message,
        "📸 **Надішліть фото обличчя вашої AI-моделі:**\n\n"
        "• Найкраще підходить чіткий портрет крупним планом.\n"
        "• Бажано без темних окулярів чи сильних фільтрів.\n"
        "• Це фото визначатиме риси обличчя для всіх майбутніх генерацій.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(ModelSetupStates.waiting_for_face, F.photo)
async def process_model_face(message: Message, state: FSMContext, bot: Bot):
    """Processes uploaded model face photo."""
    photo = message.photo[-1]  # Highest resolution
    user_id = message.from_user.id

    wait_msg = await message.answer("⏳ Обробляю та зберігаю фото обличчя...")

    try:
        file_io = io.BytesIO()
        await bot.download(photo, destination=file_io)
        raw_bytes = file_io.getvalue()

        # Validate and optimize image
        processed_bytes = validate_and_process_image(raw_bytes)
        await storage_service.save_model_face(user_id, processed_bytes)

        profile = storage_service.get_model_profile(user_id)
        await wait_msg.delete()

        if not profile["has_body"]:
            # Prompt user to upload body next
            await state.set_state(ModelSetupStates.waiting_for_body)
            await message.answer(
                "✅ **Обличчя успішно збережено!**\n\n"
                "Тепер надішліть фото **фігури / тіла** моделі (на повний зріст або по пояс):",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown",
            )
        else:
            await state.clear()
            await message.answer(
                "✅ **Обличчя успішно оновлено!**\nПрофіль AI-моделі повністю готовий до створення фото.",
                reply_markup=get_model_profile_keyboard(True, True),
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.error(f"Error saving face for user {user_id}: {e}")
        await wait_msg.edit_text(
            f"❌ Не вдалося зберегти фото: {e}\nСпробуйте надіслати інше фото.",
            reply_markup=get_cancel_keyboard(),
        )


@router.callback_query(F.data == "set_body")
async def cb_set_body(callback: CallbackQuery, state: FSMContext):
    """Initiates body photo upload state."""
    await state.set_state(ModelSetupStates.waiting_for_body)
    await safe_edit_message(
        callback.message,
        "🧍‍♀️ **Надішліть фото фігури / тіла вашої AI-моделі:**\n\n"
        "• Фото на повний зріст або по пояс.\n"
        "• Дозволяє нейромережі точно зберігати форму тіла, зріст та пропорції дівчини.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(ModelSetupStates.waiting_for_body, F.photo)
async def process_model_body(message: Message, state: FSMContext, bot: Bot):
    """Processes uploaded model body photo."""
    photo = message.photo[-1]
    user_id = message.from_user.id

    wait_msg = await message.answer("⏳ Обробляю та зберігаю фото фігури...")

    try:
        file_io = io.BytesIO()
        await bot.download(photo, destination=file_io)
        raw_bytes = file_io.getvalue()

        processed_bytes = validate_and_process_image(raw_bytes)
        await storage_service.save_model_body(user_id, processed_bytes)

        profile = storage_service.get_model_profile(user_id)
        await state.clear()
        await wait_msg.delete()

        await message.answer(
            "✅ **Фото фігури успішно збережено!**\n\n"
            "Тепер ви можете перейти до створення фото за референсами поз, одягу та фону.",
            reply_markup=get_model_profile_keyboard(profile["has_face"], profile["has_body"]),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error saving body for user {user_id}: {e}")
        await wait_msg.edit_text(
            f"❌ Не вдалося зберегти фото: {e}\nСпробуйте надіслати інше фото.",
            reply_markup=get_cancel_keyboard(),
        )


@router.callback_query(F.data == "preview_model_profile")
async def cb_preview_model_profile(callback: CallbackQuery, bot: Bot):
    """Sends current face and body reference photos for user inspection."""
    user_id = callback.from_user.id
    profile = storage_service.get_model_profile(user_id)

    if not profile["has_face"] and not profile["has_body"]:
        await callback.answer("У вас ще немає збережених фото моделі.", show_alert=True)
        return

    await callback.answer("Завантажую збережені фото...")

    if profile["has_face"] and profile["face_path"]:
        await bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=FSInputFile(str(profile["face_path"])),
            caption="👤 **Поточне збережене обличчя моделі**",
            parse_mode="Markdown",
        )

    if profile["has_body"] and profile["body_path"]:
        await bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=FSInputFile(str(profile["body_path"])),
            caption="🧍‍♀️ **Поточна збережена фігура моделі**",
            parse_mode="Markdown",
        )

    await callback.message.answer(
        "Оберіть дію:",
        reply_markup=get_model_profile_keyboard(profile["has_face"], profile["has_body"]),
    )


@router.callback_query(F.data == "clear_model_profile")
async def cb_clear_model_profile(callback: CallbackQuery):
    """Deletes saved model profile."""
    user_id = callback.from_user.id
    storage_service.clear_model_profile(user_id)
    await safe_edit_message(
        callback.message,
        "🗑️ **Профіль моделі очищено.**\nВи можете завантажити нові фото в будь-який момент.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown",
    )
    await callback.answer("Профіль видалено")
