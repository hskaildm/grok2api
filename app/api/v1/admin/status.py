"""Admin status endpoint — system health & runtime statistics."""

import platform
import sys
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from app.core.auth import verify_app_key
from app.core.response_middleware import get_call_logs
from app.services.token.manager import get_token_manager

router = APIRouter()


def _format_bytes(b: float) -> str:
    """将字节数格式化为可读字符串。"""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


@router.get("/status", dependencies=[Depends(verify_app_key)])
async def get_status(request: Request):
    """返回系统状态、Token统计和 API 调用统计。"""

    # ── 1. 基础系统信息 ──────────────────────────────────────────────
    now_monotonic = time.monotonic()
    start_time = getattr(request.app.state, "start_time", now_monotonic)
    start_wall = getattr(request.app.state, "start_wall_time", time.time())
    uptime_sec = int(now_monotonic - start_time)

    days, rem = divmod(uptime_sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    uptime_str = " ".join(parts)

    started_at = datetime.fromtimestamp(start_wall, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    system_info = {
        "uptime_seconds": uptime_sec,
        "uptime": uptime_str,
        "started_at": started_at,
        "python_version": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
    }

    # ── 2. 资源占用（psutil） ────────────────────────────────────────
    resource_info = {
        "psutil_available": False,
        "cpu_percent": None,
        "cpu_count": None,
        "memory_used_mb": None,
        "memory_total_mb": None,
        "memory_available_mb": None,
        "memory_percent": None,
        "disk_total": None,
        "disk_used": None,
        "disk_free": None,
        "disk_percent": None,
        "net_sent": None,
        "net_recv": None,
    }
    try:
        import psutil

        # CPU
        resource_info["cpu_percent"] = round(psutil.cpu_percent(interval=None), 1)
        resource_info["cpu_count"] = psutil.cpu_count()

        # 内存
        vm = psutil.virtual_memory()
        proc = psutil.Process()
        proc_mem = proc.memory_info()
        resource_info["memory_used_mb"] = round(proc_mem.rss / 1024 / 1024, 1)
        resource_info["memory_total_mb"] = round(vm.total / 1024 / 1024, 1)
        resource_info["memory_available_mb"] = round(vm.available / 1024 / 1024, 1)
        resource_info["memory_percent"] = round(vm.percent, 1)

        # 磁盘
        disk = psutil.disk_usage("/")
        resource_info["disk_total"] = _format_bytes(disk.total)
        resource_info["disk_used"] = _format_bytes(disk.used)
        resource_info["disk_free"] = _format_bytes(disk.free)
        resource_info["disk_percent"] = round(disk.percent, 1)

        # 网络流量
        net = psutil.net_io_counters()
        resource_info["net_sent"] = _format_bytes(net.bytes_sent)
        resource_info["net_recv"] = _format_bytes(net.bytes_recv)

        resource_info["psutil_available"] = True
    except ImportError:
        pass

    # ── 3. Token 统计 ────────────────────────────────────────────────
    mgr = await get_token_manager()
    raw_stats = mgr.get_stats()

    token_totals = {
        "total": 0,
        "active": 0,
        "cooling": 0,
        "expired": 0,
        "disabled": 0,
        "total_quota": 0,
        "total_consumed": 0,
        "total_today_consumed": 0,
    }
    pool_stats = {}
    for pool_name, stats in raw_stats.items():
        for key in token_totals:
            token_totals[key] += stats.get(key, 0)
        pool_stats[pool_name] = {
            "total": stats["total"],
            "active": stats["active"],
            "cooling": stats["cooling"],
            "expired": stats["expired"],
            "disabled": stats["disabled"],
            "total_quota": stats["total_quota"],
            "avg_quota": round(stats["avg_quota"], 1),
            "total_consumed": stats["total_consumed"],
            "avg_consumed": round(stats["avg_consumed"], 1),
        }

    token_info = {
        "totals": token_totals,
        "pools": pool_stats,
    }

    # ── 4. API 调用统计 ──────────────────────────────────────────────
    logs = get_call_logs()

    total_calls = len(logs)
    success = sum(1 for l in logs if 200 <= l["status"] < 300)
    client_err = sum(1 for l in logs if 400 <= l["status"] < 500)
    server_err = sum(1 for l in logs if l["status"] >= 500)
    durations = [l["duration_ms"] for l in logs]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0
    success_rate = round(success / total_calls * 100, 1) if total_calls else 0.0

    # 按模型分组（Top 10）
    model_counts: dict[str, dict] = {}
    for entry in logs:
        model = entry.get("model") or "unknown"
        if model not in model_counts:
            model_counts[model] = {
                "calls": 0,
                "success": 0,
                "errors": 0,
                "total_ms": 0.0,
            }
        model_counts[model]["calls"] += 1
        model_counts[model]["total_ms"] += entry.get("duration_ms", 0)
        if 200 <= entry["status"] < 300:
            model_counts[model]["success"] += 1
        elif entry["status"] >= 400:
            model_counts[model]["errors"] += 1

    top_models = sorted(
        model_counts.items(), key=lambda x: x[1]["calls"], reverse=True
    )[:10]
    model_stats = [
        {
            "model": name,
            "calls": v["calls"],
            "success": v["success"],
            "errors": v["errors"],
            "avg_duration_ms": round(v["total_ms"] / v["calls"], 1)
            if v["calls"]
            else 0.0,
        }
        for name, v in top_models
    ]

    call_info = {
        "total": total_calls,
        "success": success,
        "client_errors": client_err,
        "server_errors": server_err,
        "success_rate": success_rate,
        "avg_duration_ms": avg_duration,
        "log_capacity": 500,
        "by_model": model_stats,
    }

    return {
        "system": system_info,
        "resources": resource_info,
        "tokens": token_info,
        "calls": call_info,
    }
