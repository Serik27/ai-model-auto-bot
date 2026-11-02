# PowerShell startup script for AI Model Studio Bot
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $ScriptDir "..")

Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "    Запуск AI Model Studio Telegram Bot" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan

if (-not (Test-Path ".env")) {
    Write-Host "[УВАГА] Файл .env не знайдено!" -ForegroundColor Yellow
    Write-Host "Створюю .env на основі .env.example..." -ForegroundColor Green
    Copy-Item ".env.example" ".env"
    Write-Host "Будь ласка, відкрийте файл .env та вкажіть:" -ForegroundColor Yellow
    Write-Host "  1. BOT_TOKEN" -ForegroundColor White
    Write-Host "  2. GEMINI_API_KEY" -ForegroundColor White
    Read-Host "Натисніть Enter для виходу"
    exit
}

python src/main.py
