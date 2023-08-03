"""LinkedIn Miner API"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"


# config
from .config import settings

# fast api
from fastapi import APIRouter
from fastapi import Header

# types
from pydantic import EmailStr
from pydantic import SecretStr
from typing import List

# service
from ..miners.linkedin import LinkedInSearch

# celery tasks
# from .tasks import patch_persons
# from .tasks import celery_tasks

# from .tasks import AsyncResult
# from celery.result import AsyncResult


# init fast api
router = APIRouter()

search_api_params = {
    "google_api_key": settings.google_api_key,
    "google_cx": settings.google_cx,
    "query_type": settings.query_type,
    "bing_api_key": settings.bing_api_key,
    "bing_customconfig": settings.bing_customconfig,
}


@router.get("/linkedin/{email}")
async def linkedin_unique(email: EmailStr, name: str) -> dict:
    """LinkedIn - enrich only one person identified by his name and email

    Args:
        email (EmailStr): email address
        name (str): full name

    Returns:
        dict: dict Schema.org
    """
    miner = LinkedInSearch(search_api_params)
    person = miner.search(name=name, email=email)
    return person


@router.post("/linkedin")
async def linkedin_bulk(
    persons: list[dict],
) -> List[dict]:
    """LinkedIn - enrich several persons and returns them

    Args:
        persons (list[dict]): list of dicts
    Returns:
        list[dict]: list of dicts
    """
    # remove persons with no name
    persons = list(filter(lambda p: p.name, persons))

    miner = LinkedInSearch(bulk=True, search_api_params=search_api_params)

    return miner.bulk(persons)


@router.patch(
    "/linkedin",
)
async def linkedin_callback(
    persons: list[dict],
    x_callback_endpoint: str = Header(),
    x_callback_secret: SecretStr = Header(),
) -> str:
    # remove persons with no name
    # persons = list(filter(lambda p: p.name, persons))
    persons = [p.dict(exclude_unset=True) for p in persons if p.name]

    x_callback_secret.get_secret_value()

    # background.add_task(patch_personDB, x_callback_endpoint, callback_headers, persons)
    LinkedInSearch(bulk=True, search_api_params=search_api_params)

    # t = patch_person['delay'](persons[0].name, persons[0].email, search_api_params, callback_params)
    # t = patch_persons.delay(x_callback_endpoint, callback_headers, persons)
    # return t.id


@router.get("/tasks/{task_id}")
def linkedin_task(task_id: str):
    task_result = celery_tasks.AsyncResult(task_id)

    result = {
        "task_id": task_id,
        "task_status": task_result.status,
        "task_result": task_result.result,
        # "current" : task_result.status.current,
    }
    return result
