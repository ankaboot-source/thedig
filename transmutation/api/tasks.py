"""Background Tasks management using Celery"""

import requests
import time

# config
from .config import settings
from .config import celery_backend, celery_broker

from celery import Celery

# from celery.result import AsyncResult

# service
from ..miners.linkedin import LinkedInSearch

# log
from loguru import logger as log

celery_tasks = Celery(
    __name__,
    broker=celery_broker,
    backend=celery_backend,
    broker_url=celery_broker,
    backend_url=celery_backend,
)

celery_tasks.task_annotations = {"tasks.add": {"rate_limit": "1/min"}}

# app.conf.task_annotations = {"*" : "100/min"}


search_api_params = {
    "google_api_key": settings.google_api_key,
    "google_cx": settings.google_cx,
    "bing_api_key": settings.bing_api_key,
    "bing_customconfig": settings.bing_customconfig,
}

# Load task modules from all registered Django app configs.
celery_tasks.autodiscover_tasks()

# here begin tasks


@celery_tasks.task
def patch_person(name, email, search_api_params: dict, callback_params: dict):
    miner = LinkedInSearch(search_api_params=search_api_params)
    try:
        p_patched = miner.search(name=name, email=email)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            log.info(
                "Search API Rate limits hit. We pause then try again in 1 minute.")
            # Google limits 100 requests / minute
            time.sleep(60)
            p_patched = miner.search(name=name, email=mail)
        else:
            log.error(e)

    if not p_patched:
        return None

    # for SQL link between tables,
    # we need to set worksFor to the Organization primary key
    if p_patched.worksFor:
        w_json = p_patched.worksFor.json(exclude={"type_"})
        p_patched.worksFor = p_patched.worksFor.name
        r = requests.post(
            f"{callback_params['endpoint']}organizations",
            data=w_json,
            headers=callback_params["headers"],
        )

    p_json = p_patched.json(exclude={"type_"})
    r = requests.post(
        f"{callback_params['endpoint']}persons",
        data=p_json,
        headers=callback_params["headers"],
    )

    return r.ok


@celery_tasks.task(bind=True)
def patch_persons(self, endpoint: str, headers: dict, persons: list[dict]) -> int:
    i = 0
    success_i = 0
    miner = LinkedInSearch(bulk=True, search_api_params=search_api_params)
    for p in persons:
        try:
            p_patched = miner.search(name=p["name"], email=p["email"])
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                log.info(
                    "Search API Rate limits hit. We pause then try again in 1 minute."
                )
                # Google limits 100 requests / minute
                import time

                time.sleep(60)
                # self.retry(countdown=60, exc=e)
                p_patched = miner.search(name=p["name"], email=p["email"])
            else:
                log.error(e)

        if not p_patched:
            continue

        # for SQL link between tables,
        # we need to set worksFor to the Organization primary key
        if p_patched.worksFor:
            w_json = p_patched.worksFor.json(exclude={"type_"})
            p_patched.worksFor = p_patched.worksFor.name
            r = requests.post(f"{endpoint}organizations",
                              data=w_json, headers=headers)

        p_json = p_patched.json(exclude={"type_"})
        r = requests.post(f"{endpoint}persons", data=p_json, headers=headers)

        # useless counter but who knows?
        success_i += 1 if r.ok else 0
        i += 1
        self.update_state(
            state="PROGRESS",
            meta={"current": i, "success": success_i, "total": len(persons)},
        )
    return {"current": i, "success": success_i, "total": len(persons)}
