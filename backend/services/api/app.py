"""FastAPI composition root; importing it creates no runtime stores."""

from __future__ import annotations
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from starlette.responses import JSONResponse
from backend.services.api.runtime import ApiRuntime
from backend.services.api.auth import ApiTokenGate
from backend.services.api.limits import DEFAULT_MAX_REQUEST_BYTES, RequestSizeLimit
from backend.services.api.routing import bind_router
from backend.services.api.routers import maintenance
from backend.services.api.routers import health
from backend.services.api.routers import approvals
from backend.services.api.routers import tasks
from backend.services.api.routers import planning
from backend.services.api.routers import conversation
from backend.services.api.routers import memory
from backend.services.api.routers import learning
from backend.services.api.routers import connectors
from backend.services.api.routers import schedules
from backend.services.api.routers import improvements
from backend.services.api.routers import evolution
from backend.services.api.routers import voice
from backend.services.api.routers import perception
from backend.services.api.routers import emergency


def create_app(data_dir=None, dependencies=None) -> FastAPI:
    """Construct isolated services and routers for each application."""
    runtime = ApiRuntime(data_dir=data_dir, dependencies=dependencies)
    app = FastAPI(title="MICA local API", version="0.1.0")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        if request.url.path.startswith("/v1/evolution/"):
            # Do not echo private corrections or nonfinite measurement inputs.
            # The framework's default error serializer cannot encode infinity.
            return JSONResponse(status_code=422, content={"detail": [
                {key: issue[key] for key in ("type", "loc", "msg")}
                for issue in error.errors()
            ]})
        return await request_validation_exception_handler(request, error)

    app.state.runtime = runtime
    runtime.app = app
    app.middleware("http")(runtime.protect_storage)
    try:
        maximum = int(
            runtime.environment.get(
                "MICA_MAX_REQUEST_BYTES", str(DEFAULT_MAX_REQUEST_BYTES)
            )
        )
    except ValueError:
        maximum = DEFAULT_MAX_REQUEST_BYTES
    app.add_middleware(RequestSizeLimit, maximum=maximum)
    # Added last, so authentication runs before any body is read or measured.
    app.add_middleware(
        ApiTokenGate, token=runtime.environment.get("MICA_API_TOKEN", "")
    )
    app.include_router(bind_router(runtime, maintenance.ROUTES))
    app.include_router(bind_router(runtime, health.ROUTES))
    app.include_router(bind_router(runtime, approvals.ROUTES))
    app.include_router(bind_router(runtime, tasks.ROUTES))
    app.include_router(bind_router(runtime, planning.ROUTES))
    app.include_router(bind_router(runtime, conversation.ROUTES))
    app.include_router(bind_router(runtime, memory.ROUTES))
    app.include_router(bind_router(runtime, learning.ROUTES))
    app.include_router(bind_router(runtime, connectors.ROUTES))
    app.include_router(bind_router(runtime, schedules.ROUTES))
    app.include_router(bind_router(runtime, improvements.ROUTES))
    app.include_router(bind_router(runtime, evolution.ROUTES))
    app.include_router(bind_router(runtime, voice.ROUTES))
    app.include_router(bind_router(runtime, perception.ROUTES))
    app.include_router(bind_router(runtime, emergency.ROUTES))
    return app
