import logging
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config.settings import settings
from src.bot.keyboards.inline import get_main_menu_keyboard
from src.services.queue_worker import queue_worker
from src.services.storage import storage_service
from src.utils.telegram_helper import safe_edit_message

logger = logging.getLogger(__name__)
router = Router(name="common_router")

START_MESSAGE = (
    "👋 **Вітаємо в AI Model Studio Bot!**\n\n"
    "Цей бот створює реалістичні фото вашої віртуальної AI-моделі за допомогою **Google Gemini (Nano Banana)**.\n\n"
    "✨ **Основні можливості:**\n"
    "• 👤 **Збереження ідентичності**: фіксація обличчя та фігури дівчини\n"
    "• 👗 **Примірка образу**: заміна одягу за референсом\n"
    "• 📸 **Адаптація пози та фону**: перенесення моделі в будь-яку локацію\n"
    "• ⏳ **Розумна черга**: дотримання ліміту безкоштовного плану (2 фото/хв, ~32с між запитами)\n"
    "• 📝 **Пакетний копірайтинг**: створення описів та хештегів для Instagram & X (Twitter) англійською мовою в 1 клік\n\n"
    "Оберіть дію в меню нижче 👇"
)

HELP_MESSAGE = (
    "📖 **Інструкція з використання:**\n\n"
    "1️⃣ **Налаштуйте AI-модель:**\n"
    "   Перейдіть у «👩 Профіль AI-моделі» та завантажте:\n"
    "   • Чітке фото обличчя (портрет крупним планом)\n"
    "   • Фото фігури/тіла моделі (на повний зріст або по пояс)\n\n"
    "2️⃣ **Створення фото:**\n"
    "   Натисніть «✨ Створити нове фото» та покроково надішліть:\n"
    "   • 1. Фото бажаної пози\n"
    "   • 2. Фото одягу (outfit)\n"
    "   • 3. Фото локації (задній фон)\n"
    "   • 4. Додаткові побажання (освітлення, ракурс) або пропустіть\n\n"
    "3️⃣ **Черга та обмеження API:**\n"
    "   Безкоштовний тариф Gemini API має ліміт **2 запити на хвилину**.\n"
    "   Бот автоматично керує чергою і робить паузу ~32 секунди між генераціями.\n\n"
    "4️⃣ **Описи та хештеги:**\n"
    "   Після завершення генерації натисніть «📝 Описи та хештеги для сесії» — бот згенерує професійні тексти для всієї пачки одним запитом."
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Handles /start command."""
    await state.clear()
    await message.answer(START_MESSAGE, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Handles /help command."""
    await message.answer(HELP_MESSAGE, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Handles /cancel command."""
    await state.clear()
    await message.answer(
        "❌ Дію скасовано. Повертаємося до головного меню.",
        reply_markup=get_main_menu_keyboard(),
    )


@router.message(Command("status"))
async def cmd_status(message: Message):
    """Handles /status command."""
    user_id = message.from_user.id if message.from_user else 0
    profile = storage_service.get_model_profile(user_id)
    queue_size = queue_worker.get_queue_size()

    face_status = "✅ Завантажено" if profile["has_face"] else "❌ Не задано"
    body_status = "✅ Завантажено" if profile["has_body"] else "❌ Не задано"

    text = (
        "📊 **Поточний стан системи:**\n\n"
        f"👩 **Ваш профіль моделі:**\n"
        f"• Обличчя: {face_status}\n"
        f"• Фігура/тіло: {body_status}\n\n"
        f"⏳ **Стан черги генерацій:**\n"
        f"• Завдань у черзі: **{queue_size}**\n"
        f"• Активних генерацій: **{queue_worker.active_jobs_count}**\n"
        f"• Затримка між викликами: **{settings.RATE_LIMIT_DELAY} сек** (ліміт 2 RPM)\n"
        f"• Модель генерації: `{settings.IMAGE_MODEL}`\n"
        f"• Модель описів: `{settings.CAPTION_MODEL}`"
    )

    await message.answer(text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    """Returns to main menu."""
    await state.clear()
    await safe_edit_message(
        callback.message,
        START_MESSAGE,
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data == "view_help")
async def cb_view_help(callback: CallbackQuery):
    """Shows help text."""
    await safe_edit_message(
        callback.message,
        HELP_MESSAGE,
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data == "view_queue_status")
async def cb_view_queue_status(callback: CallbackQuery):
    """Shows status via callback."""
    user_id = callback.from_user.id
    profile = storage_service.get_model_profile(user_id)
    queue_size = queue_worker.get_queue_size()

    face_status = "✅ Завантажено" if profile["has_face"] else "❌ Не задано"
    body_status = "✅ Завантажено" if profile["has_body"] else "❌ Не задано"

    text = (
        "📊 **Поточний стан системи:**\n\n"
        f"👩 **Ваш профіль моделі:**\n"
        f"• Обличчя: {face_status}\n"
        f"• Фігура/тіло: {body_status}\n\n"
        f"⏳ **Стан черги генерацій:**\n"
        f"• Завдань у черзі: **{queue_size}**\n"
        f"• Активних генерацій: **{queue_worker.active_jobs_count}**\n"
        f"• Затримка безпеки: **{settings.RATE_LIMIT_DELAY} сек**\n"
        f"• Модель AI: `{settings.IMAGE_MODEL}`"
    )

    await safe_edit_message(callback.message, text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "cancel_action")
async def cb_cancel_action(callback: CallbackQuery, state: FSMContext):
    """Cancels current FSM flow."""
    await state.clear()
    await safe_edit_message(
        callback.message,
        "❌ Дію скасовано.",
        reply_markup=get_main_menu_keyboard(),
    )
    await callback.answer("Скасовано")
