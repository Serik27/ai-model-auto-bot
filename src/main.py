import asyncio
import logging
import sys
from pathlib import Path

# Add project root directory to sys.path so running directly (python src/main.py) works
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from config.settings import settings
from src.bot.handlers import common_router, generate_router, ideas_router, model_router
from src.services.queue_worker import queue_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ai_model_bot")


async def setup_bot_commands(bot: Bot):
    """Configures bot menu commands in Telegram UI."""
    commands = [
        BotCommand(command="start", description="Головне меню"),
        BotCommand(command="generate", description="Створити нове фото"),
        BotCommand(command="ideas", description="10 ідей для фото та постів"),
        BotCommand(command="status", description="Стан черги та ліміти API"),
        BotCommand(command="help", description="Інструкція з використання"),
        BotCommand(command="cancel", description="Скасувати поточну дію"),
    ]
    await bot.set_my_commands(commands)


async def main():
    """Main application entry point."""
    logger.info("Initializing AI Model Telegram Bot...")

    # Validate essential environment variables
    if not settings.BOT_TOKEN:
        logger.error(
            "CRITICAL: BOT_TOKEN is empty! Please create a .env file with your Telegram bot token."
        )
        print("\n" + "=" * 60)
        print("⚠️  ПОМИЛКА: Не вказано BOT_TOKEN!")
        print("1. Створіть файл .env у кореневій папці проекту")
        print("2. Додайте ваші ключі за зразком з .env.example:")
        print("   BOT_TOKEN=ваш_токен_від_BotFather")
        print("   GEMINI_API_KEY=ваш_ключ_від_Google_AI_Studio")
        print("=" * 60 + "\n")
        return

    if not settings.GEMINI_API_KEY:
        logger.warning(
            "GEMINI_API_KEY is not set. Generations will fail until a valid key is provided in .env."
        )

    # Initialize Bot and Dispatcher
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    # Register routers
    dp.include_router(common_router)
    dp.include_router(model_router)
    dp.include_router(ideas_router)
    dp.include_router(generate_router)

    # Start asynchronous queue worker
    queue_worker.start(bot)

    # Configure Telegram commands menu
    try:
        await setup_bot_commands(bot)
    except Exception as e:
        logger.warning(f"Could not setup bot commands: {e}")

    logger.info("Bot is starting polling...")
    try:
        # Drop pending updates to avoid backlog on restart
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Bot session closed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
