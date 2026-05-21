from aiogram import Router

from app.bot.handlers.main import build_main_router
from app.bot.middlewares.access_control import AccessControlMiddleware
from app.bot.middlewares.analytics import AnalyticsMiddleware
from app.services.container import AppContainer


def build_router(container: AppContainer) -> Router:
    router = Router()
    access_control = AccessControlMiddleware(admin_ids=container.settings.admin_ids)
    analytics = AnalyticsMiddleware()
    router.message.middleware(access_control)
    router.message.middleware(analytics)
    router.callback_query.middleware(access_control)
    router.callback_query.middleware(analytics)
    router.include_router(build_main_router(container))
    return router
