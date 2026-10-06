"""
Middleware and security utilities for TimeSyncBot REST API.
Includes sliding-window rate limiting, API key authentication, and exception handlers.
"""
import time
import logging
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from tgbot.config import config


class SlidingWindowRateLimiter:
    """
    In-memory sliding window rate limiter.
    Cleans up expired timestamps on access.
    """
    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        # key -> list of request timestamps
        self._records: Dict[str, List[float]] = defaultdict(list)
        self._last_clean: float = time.time()

    def is_allowed(self, client_id: str, limit: int) -> Tuple[bool, int]:
        """
        Check if client_id is within quota.
        Returns: (allowed: bool, retry_after: int)
        """
        now = time.time()
        window_start = now - self.window_seconds
        
        # Periodic general cleanup every 5 minutes
        if now - self._last_clean > 300:
            self._purge_stale(window_start)
            self._last_clean = now

        timestamps = [t for t in self._records[client_id] if t > window_start]
        self._records[client_id] = timestamps

        if len(timestamps) >= limit:
            oldest_in_window = timestamps[0]
            retry_after = max(1, int(self.window_seconds - (now - oldest_in_window)))
            return False, retry_after

        self._records[client_id].append(now)
        return True, 0

    def _purge_stale(self, window_start: float):
        for cid in list(self._records.keys()):
            valid = [t for t in self._records[cid] if t > window_start]
            if valid:
                self._records[cid] = valid
            else:
                del self._records[cid]


rate_limiter = SlidingWindowRateLimiter(window_seconds=60)


class SecurityAndRateLimitMiddleware(BaseHTTPMiddleware):
    """
    HTTP Middleware handling:
    1. Optional X-API-Key verification (grants higher quota)
    2. Per-IP or Per-Key rate limiting
    3. Standardized JSON error response for violations
    """
    async def dispatch(self, request: Request, call_next):
        # Healthcheck and docs bypass rate limiting for reliability
        path = request.url.path
        if path.startswith("/api/v1/docs") or path.startswith("/api/v1/redoc") or path.startswith("/api/v1/openapi.json") or path in ("/api/v1/health", "/health", "/api/health"):
            return await call_next(request)

        # Extract client IP
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        # Check API Key
        api_key = request.headers.get("x-api-key")
        configured_keys = config.API_KEYS

        if api_key:
            if configured_keys and api_key not in configured_keys:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={
                        "error": {
                            "code": "UNAUTHORIZED",
                            "message": "Invalid API Key provided in 'X-API-Key' header.",
                        }
                    },
                )
            # Valid authenticated key: higher limit
            rate_key = f"key:{api_key}"
            limit = config.API_RATE_LIMIT_AUTH
        else:
            # Anonymous client: standard public limit
            rate_key = f"ip:{client_ip}"
            limit = config.API_RATE_LIMIT_PUBLIC

        # Check quota
        allowed, retry_after = rate_limiter.is_allowed(rate_key, limit)
        if not allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(retry_after)},
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": f"Rate limit of {limit} requests/minute exceeded. Try again in {retry_after}s.",
                        "details": {"retry_after_seconds": retry_after},
                    }
                },
            )

        response = await call_next(request)
        return response


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Uniform handler for Pydantic input validation failures."""
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid query or path parameters.",
                "details": exc.errors(),
            }
        },
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Uniform handler for HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
            }
        },
    )


async def global_exception_handler(request: Request, exc: Exception):
    """Fallback handler for uncaught server errors."""
    logging.error(f"❌ Unhandled API Exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred while processing the request.",
            }
        },
    )
