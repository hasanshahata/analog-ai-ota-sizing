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
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..correlation.spectre_job import CorrelationJobError, render_netlist
from .runtime import RuntimeNotReady, SizingFailure, SizingRuntime
from .schemas import (STATUS_SUCCESS, SizeRequest, build_error_response,
                      build_success_response, build_unresolved_response,
                      derive_status, validation_error_response)

log = logging.getLogger("analog_ai.web")

_STATIC_DIR = Path(__file__).resolve().parents[2] / "web_app" / "static"


class _NoCacheStaticFiles(StaticFiles):
    """Always revalidate static assets so UI updates are never stale."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response
_NETLIST_TEMPLATE = (Path(__file__).resolve().parents[2]
                     / "5T_OTA_netlist_cadence.txt")


class NetlistRequest(BaseModel):
    """Verified geometry (SI) + load for the golden-netlist export."""

    W1: float = Field(..., gt=0, allow_inf_nan=False)
    L1: float = Field(..., gt=0, allow_inf_nan=False)
    W3: float = Field(..., gt=0, allow_inf_nan=False)
    L3: float = Field(..., gt=0, allow_inf_nan=False)
    Itail: float = Field(..., gt=0, allow_inf_nan=False)
    CL_pF: float = Field(..., gt=0, allow_inf_nan=False)


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

    @app.post("/api/v1/netlist", response_class=PlainTextResponse)
    def netlist(req: NetlistRequest) -> PlainTextResponse:
        """Render the golden Spectre netlist for a verified sizing.

        Pure text rendering - independent of the LUT engine. Rejects
        out-of-domain geometry via the canonical validator.
        """
        try:
            template = _NETLIST_TEMPLATE.read_text(encoding="utf-8")
            text = render_netlist(
                template,
                {"L1": req.L1, "W1": req.W1, "L3": req.L3,
                 "W3": req.W3, "Itail": req.Itail},
                cl_f=req.CL_pF * 1e-12)
        except CorrelationJobError as exc:
            return JSONResponse(status_code=422, content=build_error_response(
                "netlist_error",
                "geometry rejected by the netlist validator"))
        except FileNotFoundError:
            return JSONResponse(status_code=500, content=build_error_response(
                "netlist_error", "netlist template is missing on the server"))
        return PlainTextResponse(text)

    if _STATIC_DIR.exists():
        app.mount("/", _NoCacheStaticFiles(directory=str(_STATIC_DIR),
                                           html=True), name="static")
    return app
