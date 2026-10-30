from .start import router as start_router
from .admin import router as admin_router
from .models import router as models_router
from .kits import router as kits_router
from .orders import router as orders_router
from .tasks import router as tasks_router
from .price import router as price_router

from .common import router as common_router

routers = [
    start_router,
    admin_router,
    models_router,
    kits_router,
    orders_router,
    tasks_router,
    price_router,
    common_router,
]
