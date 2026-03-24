from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from core.logging import configure_logging, get_logger
from core.config import HTTP_PROXY, HTTPS_PROXY, EXT_TIMEOUT, INT_TIMEOUT, SCHEDULER_ENABLED, require_env
from db.session import init_db
from db.session import AsyncSessionLocal
from db import crud
from api.routes import router
from integrations.bitable_writer import flush_bitable_outbox
from core.scheduler import start_scheduler, stop_scheduler

configure_logging()
logger = get_logger(__name__)


def _proxy_url() -> str | None:
    return HTTP_PROXY or HTTPS_PROXY


@asynccontextmanager
async def lifespan(app: FastAPI):
    # validate env if not MOCK_MODE
    require_env()

    ext_client = httpx.AsyncClient(proxy=_proxy_url(), timeout=EXT_TIMEOUT)
    int_client = httpx.AsyncClient(proxy=None, timeout=INT_TIMEOUT)
    app.state.ext_client = ext_client
    app.state.int_client = int_client
    app.state.wewe_login_watch_tasks = {}

    await init_db()
    try:
        flush_result = await flush_bitable_outbox(ext_client)
        if flush_result.get("synced") or flush_result.get("failed"):
            logger.info("Bitable outbox flush completed on startup: %s", flush_result)
            async with AsyncSessionLocal() as session:
                await crud.log_system(
                    session,
                    level="info",
                    module="bitable",
                    message="Bitable outbox flush completed on startup",
                    details=flush_result,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bitable outbox flush failed on startup: %s", exc)
        async with AsyncSessionLocal() as session:
            await crud.log_system(
                session,
                level="warning",
                module="bitable",
                message="Bitable outbox flush failed on startup",
                details={"error": str(exc)},
            )
    if SCHEDULER_ENABLED:
        try:
            await start_scheduler(app.state)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Scheduler startup failed: %s", exc)
            async with AsyncSessionLocal() as session:
                await crud.log_system(
                    session,
                    level="error",
                    module="scheduler",
                    message="Scheduler startup failed",
                    details={"error": str(exc)},
                )

    yield

    stop_scheduler()
    for task in list(app.state.wewe_login_watch_tasks.values()):
        task.cancel()
    await ext_client.aclose()
    await int_client.aclose()


app = FastAPI(lifespan=lifespan)
app.include_router(router)
