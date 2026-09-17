from .admin import router as admin_router
from .common import router as common_router
from .models import router as models_router
from .kits import router as kits_router
from .orders import router as orders_router
from .tasks import router as tasks_router

# Порядок важен: common_router должен быть в конце (у него fallback-обработчик),
# но перед этим обработчики ignore и middleware
routers = [
    admin_router,
    models_router,
    kits_router,
    orders_router,
    tasks_router,
    common_router,
]
