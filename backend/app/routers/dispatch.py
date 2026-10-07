"""调度指令接口：组合检索、状态流转、执行结果落库与跨单位只读控制。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.dispatch import DispatchService

router = APIRouter(prefix="/api/dispatch", tags=["调度指令"])

service = DispatchService()


def _scope(values: dict[str, Any]) -> tuple[str, str]:
    """从请求体取提交人及其所属单位（演示期由前端透传当前值班身份）。"""
    return str(values.get("operator") or "").strip(), str(values.get("unit") or "").strip()


@router.get("", response_model=PageResult[dict])
def list_entries(
    deadline: str | None = Query(default=None, description="按执行时限检索，含已执行（归档）指令"),
    unit: str | None = Query(default=None, description="按下发单位检索"),
    operator: str | None = Query(default=None, description="按执行人检索"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1),
) -> PageResult[dict]:
    """执行时限、下发单位、执行人组合查询；查不到返回空页，不报错也不回旧数据。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        deadline=deadline, unit=unit, operator=operator, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def status_stats() -> dict[str, int]:
    """按状态汇总，用于页面统计卡。"""
    return service.status_stats()


@router.get("/export")
def export_entries(
    deadline: str | None = None,
    unit: str | None = None,
    operator: str | None = None,
) -> dict[str, Any]:
    """导出清单：与列表同一套筛选口径和取数逻辑，条数与列表总数一致。"""
    items, total = service.export_entries(deadline=deadline, unit=unit, operator=operator)
    return {"module": "dispatch", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条明细；跨单位也可查看。不存在时给出可读说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"调度指令 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条调度指令，缺字段或重复编号时说明原因而不是静默丢弃。"""
    entry, errors = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="调度指令已登记", entry=entry)


@router.post("/{entry_id}/execute", response_model=ActionResult)
def execute_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """确认执行（待执行→执行中）；已执行再点则退回执行中，已落库结果保留。跨单位只读。"""
    operator, unit = _scope(payload.values)
    entry, message = service.execute(entry_id, operator=operator, unit=unit)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/result", response_model=ActionResult)
def submit_result(entry_id: int, payload: EntryPayload) -> ActionResult:
    """提交执行结果并落库到待办条目；同一指令重复提交原样拒收，只保留第一条。"""
    operator, unit = _scope(payload.values)
    result = str(payload.values.get("result") or "")
    entry, message, accepted = service.submit_result(entry_id, result, operator=operator, unit=unit)
    if not accepted:
        return ActionResult(ok=False, message=message, entry=entry)
    return ActionResult(ok=True, message=message, entry=entry)
