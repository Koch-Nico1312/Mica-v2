"""Bind route declarations to one application's runtime instance."""

from fastapi import APIRouter


def bind_router(runtime, routes) -> APIRouter:
    router = APIRouter()
    for path, method, name in routes:
        handler = getattr(runtime, name)
        if method == "websocket":
            router.add_api_websocket_route(path, handler)
        else:
            router.add_api_route(path, handler, methods=[method.upper()])
    return router
