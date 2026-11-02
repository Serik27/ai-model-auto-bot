@echo off
chcp 65001 > nul
echo ===================================================
echo     Запуск AI Model Studio Telegram Bot
echo ===================================================

cd /d "%~dp0\.."

if not exist .env (
    echo [УВАГА] Файл .env не знайдено!
    echo Створюю файл .env на основі .env.example...
    copy .env.example .env
    echo Будь ласка, відкрийте файл .env та вставте ваші ключі:
    echo   1. BOT_TOKEN (від @BotFather)
    echo   2. GEMINI_API_KEY (від Google AI Studio)
    pause
    exit /b
)

python src/main.py
pause
