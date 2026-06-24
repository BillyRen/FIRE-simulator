"""Request-scoped observability: request IDs, timing logs, optional Sentry.

Design notes
------------
- **Pure-ASGI middleware** (not Starlette ``BaseHTTPMiddleware``): the NDJSON
  endpoints do their heavy Monte-Carlo compute *while the response body is
  streaming*, so a ``call_next``-based timer would stop at the first byte and
  badly under-report latency. Wrapping the ASGI ``send`` lets us measure until
  the final body chunk. It also keeps the request-id ``contextvar`` in the same
  task as the endpoint/generator, so ``deps.streaming`` can read it.
- **No PII**: only ``method``/``path``/``status``/``duration`` are logged —
  never request bodies, which carry financial inputs (portfolio, cash flows).
- **Sentry is optional**: ``init_sentry()`` is a no-op unless ``SENTRY_DSN`` is
  set, so importing this module adds zero behaviour for local/dev runs.
"""

from __future__ import annotations

import contextvars
import logging
import os
import time
import uuid

from starlette.responses import JSONResponse

logger = logging.getLogger("fire.request")

# Correlation id for the current request, readable from anywhere (notably the
# NDJSON streaming wrapper in deps.py) to tie streaming-swallowed errors back to
# the originating request line.
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def current_request_id() -> str:
    return request_id_ctx.get()


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


class RequestContextMiddleware:
    """Assign a request id, echo ``X-Request-ID``, and log a one-line request
    summary measured until the final response chunk."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _header(scope, b"x-request-id") or uuid.uuid4().hex[:12]
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        method = scope.get("method", "-")
        path = scope.get("path", "-")
        status = {"code": 0}
        started = {"v": False}
        logged = {"done": False}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                started["v"] = True
                status["code"] = message["status"]
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", request_id.encode("latin-1")))
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                if not logged["done"]:
                    logged["done"] = True
                    duration_ms = (time.perf_counter() - start) * 1000
                    logger.info(
                        "req method=%s path=%s status=%s dur_ms=%.1f id=%s",
                        method, path, status["code"], duration_ms, request_id,
                    )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "req-failed method=%s path=%s dur_ms=%.1f id=%s",
                method, path, duration_ms, request_id,
            )
            capture_exception(exc)
            # If the response already started we can't replace it — let the
            # error propagate. Otherwise synthesise the 500 ourselves so it
            # carries the X-Request-ID header that correlates with the
            # req-failed log line (Starlette's outer error middleware would
            # emit a 500 that never passes back through this wrapper).
            if started["v"]:
                raise
            response = JSONResponse(
                {"error": "INTERNAL_ERROR", "request_id": request_id},
                status_code=500,
                headers={"x-request-id": request_id},
            )
            await response(scope, receive, send)
        finally:
            request_id_ctx.reset(token)


def configure_logging() -> None:
    """Attach a stdout handler to the ``fire`` logger namespace at INFO.

    Done explicitly because uvicorn configures its own ``uvicorn.*`` loggers,
    not the root logger, so our messages would otherwise be dropped.
    """
    fire_logger = logging.getLogger("fire")
    if not fire_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        fire_logger.addHandler(handler)
    fire_logger.setLevel(logging.INFO)
    fire_logger.propagate = False


def init_sentry() -> bool:
    """Initialise Sentry iff ``SENTRY_DSN`` is set. Returns whether enabled.

    No-op with zero behaviour change when the DSN is absent. PII and request
    bodies are explicitly disabled — requests carry financial inputs.
    """
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; skipping.")
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        send_default_pii=False,
        max_request_body_size="never",
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
    )
    logger.info("Sentry initialised (env=%s)", os.getenv("SENTRY_ENVIRONMENT", "production"))
    return True


def capture_exception(exc: BaseException | None = None) -> None:
    """Report an exception to Sentry if available. No-op otherwise.

    ``sentry_sdk.capture_exception`` is itself a no-op when Sentry was never
    initialised, so this is safe to call unconditionally from hot paths.
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    sentry_sdk.capture_exception(exc)
