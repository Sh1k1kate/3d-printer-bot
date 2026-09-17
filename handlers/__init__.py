from .admin import router as admin_router
from .models import router as models_router
from .kits import router as kits_router
from .orders import router as orders_router
from .tasks import router as tasks_router

routers = [admin_router, models_router, kits_router, orders_router, tasks_router]
