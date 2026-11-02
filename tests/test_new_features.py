import pytest
from unittest.mock import AsyncMock, MagicMock
from src.bot.keyboards.inline import get_main_menu_keyboard, get_cancel_keyboard
from src.services.gemini_caption import extract_json_from_response, gemini_caption_service
from src.services.gemini_image import GeminiImageService
from src.utils.telegram_helper import safe_edit_message


def test_main_menu_keyboard_has_ideas_button():
    kb = get_main_menu_keyboard()
    callback_data_list = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "start_photo_ideas" in callback_data_list
    assert "start_new_photo" in callback_data_list


def test_cancel_keyboard_with_skip():
    kb = get_cancel_keyboard(show_skip=True)
    callback_data_list = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "skip_step" in callback_data_list
    assert "cancel_action" in callback_data_list


def test_build_generation_prompt_with_text_and_skip():
    service = GeminiImageService(api_key="mock_key")
    prompt = service.build_generation_prompt(
        has_pose_image=False,
        pose_text="sitting gracefully on a vintage armchair",
        has_outfit_image=False,
        outfit_text="red silk evening gown",
        has_background_image=False,
        background_text=None,
    )

    assert "sitting gracefully on a vintage armchair" in prompt
    assert "red silk evening gown" in prompt
    assert "REFERENCE 1 (FACE REFERENCE)" in prompt
    assert "REFERENCE 2 (BODY / FIGURE REFERENCE)" in prompt
    assert "REFERENCE 3 (POSE REFERENCE)" not in prompt
    assert "REFERENCE 4 (OUTFIT / CLOTHING REFERENCE)" not in prompt


def test_extract_json_from_markdown_block():
    raw = """
    Here is the requested output:
    ```json
    [
      {
        "photo_index": 1,
        "instagram": "Chic Parisian morning vibe ✨",
        "threads": "Coffee first, everything else second.",
        "twitter": "Early mornings in Paris hits different ☕️ #paris"
      }
    ]
    ```
    Enjoy!
    """
    parsed = extract_json_from_response(raw)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["photo_index"] == 1
    assert "Chic Parisian" in parsed[0]["instagram"]


def test_fallback_parse_captions():
    raw_text = """
    PHOTO #1
    INSTAGRAM:
    Golden hour magic in Rome!
    🏷️ HASHTAGS:
    #rome #italy #goldenhour
    THREADS:
    Can we talk about Italian sunsets?
    X (TWITTER):
    Golden hour in Rome > everything else #rome
    """
    parsed = gemini_caption_service._fallback_parse_captions(raw_text, count=1)
    assert len(parsed) == 1
    assert "Golden hour magic in Rome!" in parsed[0]["instagram"]
    assert "#rome" in parsed[0]["instagram"]
    assert "Italian sunsets" in parsed[0]["threads"]
    assert "Golden hour in Rome" in parsed[0]["twitter"]


@pytest.mark.asyncio
async def test_safe_edit_message_with_text():
    mock_msg = MagicMock()
    mock_msg.text = "Hello world"
    mock_msg.edit_text = AsyncMock(return_value=mock_msg)
    mock_msg.answer = AsyncMock()

    await safe_edit_message(mock_msg, "Updated text")
    mock_msg.edit_text.assert_awaited_once_with(
        text="Updated text",
        reply_markup=None,
        parse_mode="Markdown",
    )
    mock_msg.answer.assert_not_called()


@pytest.mark.asyncio
async def test_safe_edit_message_with_media_photo():
    mock_msg = MagicMock()
    mock_msg.text = None
    mock_msg.edit_reply_markup = AsyncMock()
    mock_msg.answer = AsyncMock()

    await safe_edit_message(mock_msg, "Prompt on photo message")
    mock_msg.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    mock_msg.answer.assert_awaited_once_with(
        text="Prompt on photo message",
        reply_markup=None,
        parse_mode="Markdown",
    )
