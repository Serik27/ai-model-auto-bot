from src.bot.handlers.common import router as common_router
from src.bot.handlers.model import router as model_router
from src.bot.handlers.generate import router as generate_router
from src.bot.handlers.ideas import router as ideas_router

__all__ = ["common_router", "model_router", "generate_router", "ideas_router"]
