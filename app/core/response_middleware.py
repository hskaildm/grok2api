"""
响应中间件
Response Middleware

用于记录请求日志、生成 TraceID 和计算请求耗时
"""

import json
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import get_config
from app.core.logger import logger

# ---- 调用日志收集 ----
_MAX_LOG_ENTRIES = 500
_call_logs: deque = deque(maxlen=_MAX_LOG_ENTRIES)
_log_lock = Lock()

# 需要记录调用日志的 API 路径前缀
_API_LOG_PREFIXES = (
    "/v1/chat/",
    "/v1/images/",
    "/v1/videos",
    "/v1/responses",
)


def get_call_logs() -> list:
    """返回调用日志列表（最新在前）。"""
    with _log_lock:
        return list(reversed(_call_logs))


def clear_call_logs() -> int:
    """清空调用日志，返回被清除的条数。"""
    with _log_lock:
        count = len(_call_logs)
        _call_logs.clear()
        return count


class ResponseLoggerMiddleware(BaseHTTPMiddleware):
    """
    请求日志/响应追踪中间件
    Request Logging and Response Tracking Middleware
    """

    @staticmethod
    def _should_log_response(path: str, status_code: int, duration_ms: float) -> bool:
        if path == "/health" and not bool(
            get_config("log.log_health_requests", False)
        ):
            return False

        if bool(get_config("log.log_all_requests", False)):
            return True

        try:
            slow_ms = float(get_config("log.request_slow_ms", 3000))
        except (TypeError, ValueError):
            slow_ms = 3000.0

        return status_code >= 400 or duration_ms >= slow_ms

    @staticmethod
    def _should_collect(path: str) -> bool:
        """判断是否需要收集到调用日志。"""
        return any(path.startswith(p) for p in _API_LOG_PREFIXES)

    @staticmethod
    def _extract_model(body_bytes: bytes) -> str:
        """尝试从请求 body 中提取 model 字段。"""
        if not body_bytes:
            return ""
        try:
            data = json.loads(body_bytes)
            return str(data.get("model", ""))
        except Exception:
            return ""

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        if request.client:
            return request.client.host
        return ""

    async def dispatch(self, request: Request, call_next):
        # 生成请求 ID
        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id

        start_time = time.time()
        path = request.url.path

        if path.startswith("/static/") or path in (
            "/",
            "/login",
            "/imagine",
            "/voice",
            "/admin",
            "/admin/login",
            "/admin/config",
            "/admin/cache",
            "/admin/token",
            "/admin/logs",
        ):
            return await call_next(request)

        # 预读 body 用于提取 model（仅对需要收集的路径）
        model = ""
        should_collect = self._should_collect(path)
        if should_collect and request.method in ("POST", "PUT"):
            try:
                body_bytes = await request.body()
                model = self._extract_model(body_bytes)
            except Exception:
                pass

        try:
            response = await call_next(request)

            # 计算耗时
            duration = (time.time() - start_time) * 1000

            # 收集调用日志
            if should_collect:
                entry = {
                    "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "method": request.method,
                    "path": path,
                    "model": model,
                    "status": response.status_code,
                    "duration_ms": round(duration, 2),
                    "ip": self._get_client_ip(request),
                    "trace_id": trace_id,
                }
                with _log_lock:
                    _call_logs.append(entry)

            if self._should_log_response(path, response.status_code, duration):
                log_method = (
                    logger.error
                    if response.status_code >= 500
                    else logger.warning
                    if response.status_code >= 400
                    else logger.info
                )
                log_method(
                    f"Response: {request.method} {request.url.path} - {response.status_code} ({duration:.2f}ms)",
                    extra={
                        "traceID": trace_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "duration_ms": round(duration, 2),
                    },
                )

            return response

        except Exception as e:
            duration = (time.time() - start_time) * 1000

            # 异常也记录到调用日志
            if should_collect:
                entry = {
                    "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "method": request.method,
                    "path": path,
                    "model": model,
                    "status": 500,
                    "duration_ms": round(duration, 2),
                    "ip": self._get_client_ip(request),
                    "trace_id": trace_id,
                    "error": str(e),
                }
                with _log_lock:
                    _call_logs.append(entry)

            logger.opt(exception=e).error(
                f"Response Error: {request.method} {request.url.path} - {str(e)} ({duration:.2f}ms)",
                extra={
                    "traceID": trace_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration, 2),
                    "error": str(e),
                },
            )
            raise
