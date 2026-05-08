from aiogram import Router

from app.bot.handlers.main import build_main_router
from app.services.container import AppContainer


def build_router(container: AppContainer) -> Router:
    router = Router()
    router.include_router(build_main_router(container))
    return router
