from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Returns main navigation menu keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✨ Створити нове фото", callback_data="start_new_photo"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💡 10 ідей для фото та постів", callback_data="start_photo_ideas"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👩 Профіль AI-моделі", callback_data="view_model_profile"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статус та черга", callback_data="view_queue_status"
                ),
                InlineKeyboardButton(
                    text="ℹ️ Допомога", callback_data="view_help"
                ),
            ],
        ]
    )


def get_model_profile_keyboard(has_face: bool, has_body: bool) -> InlineKeyboardMarkup:
    """Returns management buttons for the user's AI model profile."""
    face_text = "🔄 Змінити обличчя" if has_face else "📸 Завантажити обличчя"
    body_text = "🔄 Змінити фігуру/тіло" if has_body else "🧍‍♀️ Завантажити тіло"

    buttons = [
        [InlineKeyboardButton(text=face_text, callback_data="set_face")],
        [InlineKeyboardButton(text=body_text, callback_data="set_body")],
    ]

    if has_face or has_body:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="👀 Переглянути збережені фото",
                    callback_data="preview_model_profile",
                )
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    text="🗑️ Очистити профіль моделі",
                    callback_data="clear_model_profile",
                )
            ]
        )

    buttons.append([InlineKeyboardButton(text="⬅️ Головне меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cancel_keyboard(
    show_skip: bool = False,
    skip_text: str = "⏩ Пропустити цей крок",
    skip_data: str = "skip_step",
) -> InlineKeyboardMarkup:
    """Returns cancellation or skip keyboard for FSM steps."""
    buttons = []
    if show_skip:
        buttons.append([InlineKeyboardButton(text=skip_text, callback_data=skip_data)])
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_action")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_confirm_generation_keyboard() -> InlineKeyboardMarkup:
    """Returns confirmation options before starting generation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Запустити генерацію", callback_data="confirm_and_launch"
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Додати ще одне фото до сесії",
                    callback_data="add_another_to_batch",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Скасувати", callback_data="cancel_action"
                )
            ],
        ]
    )


def get_post_generation_keyboard(session_id: str) -> InlineKeyboardMarkup:
    """Keyboard shown with generated results."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📝 Згенерувати описи та хештеги",
                    callback_data=f"caption_session:{session_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✨ Створити ще одне фото", callback_data="start_new_photo"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Головне меню", callback_data="main_menu"
                )
            ],
        ]
    )


def get_ideas_menu_keyboard() -> InlineKeyboardMarkup:
    """Keyboard shown after generating 10 ideas."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✨ Створити нове фото", callback_data="start_new_photo"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💡 Ще 10 ідей", callback_data="start_photo_ideas"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Головне меню", callback_data="main_menu"
                )
            ],
        ]
    )
