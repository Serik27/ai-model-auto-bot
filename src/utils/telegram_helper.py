import logging
from typing import Optional
from aiogram.types import InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)


async def safe_edit_message(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = "Markdown",
) -> Message:
    """
    Safely edits text of a message if it contains text.
    If the message is a photo/media message (where message.text is None),
    or if edit_text fails due to TelegramBadRequest,
    it removes the inline buttons from the existing message and sends a new message.
    """
    if message.text is not None:
        try:
            return await message.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except Exception as e:
            logger.debug(f"edit_text failed, falling back to answer: {e}")

    # For media messages (photo, video, etc.) or when edit_text failed
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    return await message.answer(
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )
