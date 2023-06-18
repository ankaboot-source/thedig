__license__ = "AGPL"
__author__ = "Badreddine Lejmi <badreddine@ankaboot.fr>"
__version__ = "0.1dev"

# import miners to being available in the API scope
# from transmutation import miners

# import API
from .linkedin import router as linkedin_router
from .whoiscompany import router as whoiscompany_router
from .transmuter import router as transmuter_router

# finally API router
from fastapi import APIRouter

router = APIRouter()
router.include_router(whoiscompany_router)
router.include_router(linkedin_router)
router.include_router(transmuter_router)

# from .tasks import celery_tasks
# __all__ = ("celery_tasks",)
