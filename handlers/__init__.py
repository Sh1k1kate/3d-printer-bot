from .start import router as start_router
from .admin import router as admin_router
from .models import router as models_router
from .kits import router as kits_router
from .orders import router as orders_router
from .tasks import router as tasks_router
from .common import router as common_router

# Порядок важен:
# 1. start_router — команды /start, /help и др.
# 2. Остальные функциональные роутеры.
# 3. common_router — последний (обработчик ignore и fallback).
routers = [
    start_router,
    admin_router,
    models_router,
    kits_router,
    orders_router,
    tasks_router,
    common_router,
]
