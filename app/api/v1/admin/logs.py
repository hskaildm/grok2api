"""Admin API call logs endpoint."""

from fastapi import APIRouter, Depends, Query

from app.core.auth import verify_app_key
from app.core.response_middleware import get_call_logs, clear_call_logs

router = APIRouter()


@router.get("/logs", dependencies=[Depends(verify_app_key)])
async def get_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """获取 API 调用日志（分页）。"""
    logs = get_call_logs()
    total = len(logs)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 1,
        "data": logs[start:end],
    }


@router.post("/logs/clear", dependencies=[Depends(verify_app_key)])
async def post_clear_logs():
    """清空调用日志。"""
    count = clear_call_logs()
    return {"status": "success", "cleared": count}
