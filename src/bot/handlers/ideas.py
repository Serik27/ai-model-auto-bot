import asyncio
import html
import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards.inline import (
    get_cancel_keyboard,
    get_ideas_menu_keyboard,
    get_main_menu_keyboard,
)
from src.bot.states import IdeasGeneratorStates
from src.services.gemini_caption import gemini_caption_service
from src.utils.telegram_helper import safe_edit_message

logger = logging.getLogger(__name__)
router = Router(name="ideas_router")

PROMPT_WISHES_TEXT = (
    "💡 **Генератор 10 ідей для фотосесії та постів**\n\n"
    "Бот згенерує 10 трендових концепцій для вашої AI-моделі:\n"
    "• 📸 Опис пози, образу, стилю та локації\n"
    "• 🎨 Професійний англомовний промпт (готовий для генерації фото)\n"
    "• ✍️ Готовий текст для публікації з хештегами\n\n"
    "✍️ **Напишіть ваші побажання або тему** (наприклад: *'літній відпочинок на яхті'*, "
    "*'streetwear у стилі cyberpunk'*, *'затишна осінь у Парижі'*, *'спорт та фітнес'*).\n\n"
    "Або натисніть кнопку нижче, щоб **пропустити** (бот запропонує топ-10 універсальних трендових ідей):"
)


@router.message(Command("ideas"))
@router.callback_query(F.data == "start_photo_ideas")
async def start_ideas_flow(event: Message | CallbackQuery, state: FSMContext):
    """Initiates the 10 ideas generation flow."""
    await state.clear()
    await state.set_state(IdeasGeneratorStates.waiting_for_wishes)

    keyboard = get_cancel_keyboard(
        show_skip=True,
        skip_text="⏩ Пропустити (трендові ідеї)",
        skip_data="skip_ideas_wishes",
    )

    if isinstance(event, CallbackQuery):
        await safe_edit_message(event.message, PROMPT_WISHES_TEXT, reply_markup=keyboard, parse_mode="Markdown")
        await event.answer()
    else:
        await event.answer(PROMPT_WISHES_TEXT, reply_markup=keyboard, parse_mode="Markdown")


@router.message(IdeasGeneratorStates.waiting_for_wishes, F.text)
async def process_wishes_text(message: Message, state: FSMContext):
    """Processes user wishes and generates 10 ideas."""
    wishes = message.text.strip()
    await state.clear()
    await _generate_and_send_ideas(message, wishes)


@router.callback_query(IdeasGeneratorStates.waiting_for_wishes, F.data == "skip_ideas_wishes")
async def cb_skip_wishes(callback: CallbackQuery, state: FSMContext):
    """Skips wishes and generates 10 trending ideas."""
    await state.clear()
    await callback.answer()
    await _generate_and_send_ideas(callback.message, None)


async def _generate_and_send_ideas(target_msg: Message, wishes: str | None):
    """Generates 10 photo ideas via Gemini and sends them as separate messages."""
    status_msg = await target_msg.answer(
        "⏳ <b>Генерую 10 креативних ідей для фото та постів...</b>\n"
        "⚡ Gemini розробляє концепції, професійні промпти та тексти...",
        parse_mode="HTML",
    )

    try:
        ideas = await gemini_caption_service.generate_photo_ideas(wishes)
        try:
            await status_msg.delete()
        except Exception:
            pass

        intro_theme = f" за вашим запитом: <i>«{html.escape(wishes)}»</i>" if wishes else " (трендовий топ)"
        await target_msg.answer(
            f"✨ <b>Готово! 10 ідей для фотосесії вашої AI-моделі{intro_theme}:</b>\n"
            "<i>💡 Торкніться промпту або опису поста, щоб миттєво скопіювати його в буфер обміну.</i>",
            parse_mode="HTML",
        )
        await asyncio.sleep(0.3)

        for item in ideas:
            num = item.get("number", "")
            title = item.get("title", f"Ідея #{num}")
            visual = item.get("visual_description", "")
            prompt = item.get("generation_prompt", "")
            caption = item.get("post_caption", "")

            msg_text = (
                f"💡 <b>Ідея #{num}: {html.escape(str(title))}</b>\n\n"
                f"📸 <b>Опис образу та локації:</b>\n"
                f"{html.escape(str(visual))}\n\n"
                f"🎨 <b>Професійний промпт для фото:</b>\n"
                f"<pre><code>{html.escape(str(prompt))}</code></pre>\n\n"
                f"✍️ <b>Текст для публікації:</b>\n"
                f"<pre><code>{html.escape(str(caption))}</code></pre>"
            )

            await target_msg.answer(msg_text, parse_mode="HTML")
            await asyncio.sleep(0.3)

        await target_msg.answer(
            "🎉 <b>Всі 10 ідей надіслано!</b>\n\n"
            "Скопіюйте будь-який промпт і використайте його при створенні нового фото:",
            reply_markup=get_ideas_menu_keyboard(),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Error generating photo ideas: {e}", exc_info=True)
        try:
            await status_msg.edit_text(
                f"❌ <b>Помилка під час генерації ідей:</b>\n<code>{html.escape(str(e))}</code>\n\n"
                "Спробуйте ще раз пізніше.",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML",
            )
        except Exception:
            await target_msg.answer(
                f"❌ Помилка: {e}",
                reply_markup=get_main_menu_keyboard(),
            )
