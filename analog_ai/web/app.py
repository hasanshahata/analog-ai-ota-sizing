"""FastAPI application for the ideal-tail sizing service (Phase W2).

Routes (frozen, versioned):
    GET  /api/v1/health   - readiness (loading | ready | failed), no loads
    POST /api/v1/size     - guarded sizing via the single-worker runtime

Safety rules enforced here:
- the browser never sees server paths, stack traces, checkpoint internals,
  or private campaign data;
- only user_verdict=True + non-null geometry can produce status="success";
- no engine load happens per request (one-time runtime initialization).

There is deliberately no hard timeout that kills a sizing call: the worker
is not interruptible and abandoning it mid-search would violate fail-closed
behavior. The endpoint runs in a threadpool, so /health stays responsive.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .runtime import RuntimeNotReady, SizingFailure, SizingRuntime
from .schemas import (STATUS_SUCCESS, SizeRequest, build_error_response,
                      build_success_response, build_unresolved_response,
                      derive_status, validation_error_response)

log = logging.getLogger("analog_ai.web")

_STATIC_DIR = Path(__file__).resolve().parents[2] / "web_app" / "static"


def create_app(runtime: SizingRuntime | None = None,
               load_on_startup: bool | None = None) -> FastAPI:
    """Build the app. An injected runtime is never auto-loaded (tests use
    fakes); a self-constructed runtime loads on a background thread."""
    owns_runtime = runtime is None
    rt = runtime or SizingRuntime()
    do_load = load_on_startup if load_on_startup is not None else owns_runtime

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if do_load and rt.state == "loading":
            rt.load_async()
        yield

    app = FastAPI(title="Analog AI - ideal-tail 5T OTA sizing",
                  version="0.1.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        # map FastAPI's validation error onto the frozen error format
        parts = []
        for e in exc.errors():
            loc = ".".join(str(x) for x in e.get("loc", []) if x != "body")
            parts.append(f"{loc}: {e.get('msg')}")
        return JSONResponse(status_code=422, content=build_error_response(
            "validation_error", "; ".join(parts)))

    @app.get("/api/v1/health")
    def health() -> dict:
        return rt.health()

    @app.post("/api/v1/size")
    def size(req: SizeRequest) -> JSONResponse:
        if rt.state != "ready":
            return JSONResponse(status_code=503, content=build_error_response(
                "not_ready",
                f"sizing engine not ready (state: {rt.state}); "
                "retry after /api/v1/health reports ready"))
        request_id = "req-" + uuid.uuid4().hex[:12]
        canonical = req.to_canonical()
        t0 = time.perf_counter()
        try:
            record = rt.size(canonical, seed=0)
        except RuntimeNotReady as exc:
            return JSONResponse(status_code=503, content=build_error_response(
                "not_ready", str(exc)))
        except SizingFailure as exc:
            return JSONResponse(status_code=500, content=build_error_response(
                "sizing_failed", str(exc)))
        elapsed = time.perf_counter() - t0
        status = derive_status(record)
        if status == STATUS_SUCCESS:
            payload = build_success_response(record, request_id)
        else:
            payload = build_unresolved_response(record, request_id)
        # structured log: no spec values, no hidden validation data
        log.info("size %s status=%s path=%s oracle_evals=%s elapsed=%.1fs",
                 request_id, payload["status"],
                 payload.get("pipeline_status") or record.get("status"),
                 record.get("n_oracle_evals"), elapsed)
        return JSONResponse(status_code=200, content=payload)

    if _STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True),
                  name="static")
    return app
