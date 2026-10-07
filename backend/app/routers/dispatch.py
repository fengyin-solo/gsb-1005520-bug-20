"""调度指令接口：维护调度指令单，覆盖确认执行、完成回复、驳回指令等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.dispatch import DispatchService

router = APIRouter(prefix="/api/dispatch", tags=["调度指令"])

service = DispatchService()

LIST_FIELDS = ["指令编号", "下发单位", "指令类型", "下发时间", "执行时限", "执行人", "执行结果", "指令状态"]
STATUSES = ["待执行", "执行中", "已执行", "已驳回"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按指令编号检索"),
    status: str | None = Query(default=None, description="待执行、执行中、已执行、已驳回"),
    unit: str | None = Query(default=None, description="按下发单位检索"),
    executor: str | None = Query(default=None, description="按执行人检索"),
    deadline: str | None = Query(default=None, description="按执行时限检索，已归档指令同样可查"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按指令编号、状态、下发单位、执行人、执行时限组合过滤；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, unit=unit, executor=executor, deadline=deadline,
        page=page, size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def stats() -> dict[str, int]:
    """按状态汇总调度指令数量，给页头统计卡片用。"""
    return service.stats()


@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None, description="按指令编号检索"),
    status: str | None = Query(default=None, description="待执行、执行中、已执行、已驳回"),
    unit: str | None = Query(default=None, description="按下发单位检索"),
    executor: str | None = Query(default=None, description="按执行人检索"),
    deadline: str | None = Query(default=None, description="按执行时限检索"),
) -> dict[str, Any]:
    """导出调度指令清单：与列表同一套过滤口径，条数和列表总数对齐。"""
    items, total = service.list_entries(
        keyword=keyword, status=status, unit=unit, executor=executor, deadline=deadline,
        page=1, size=10000,
    )
    return {"module": "dispatch", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条调度指令单明细；与列表同源输出，执行结果两处一致。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"调度指令单 {entry_id} 不存在")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条调度指令单；缺字段或重复提交时说明原因，不静默丢弃。"""
    entry, error = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=error)
    return ActionResult(ok=True, message="调度指令单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条调度指令单执行确认执行、完成回复、驳回指令；越权或越序的动作会被退回并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
