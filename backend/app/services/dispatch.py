"""调度指令业务规则：组合检索口径、状态流转、执行结果落库与单位权限都收在这里。

列表、单条详情、导出三处共用同一套筛选（``_query``）与序列化（``_serialize``），
保证执行结果在任何入口读到的都一致；检索不按状态剔除，已执行（归档）指令同样可查。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "dispatch"
REQUIRED_FIELDS = ["指令编号", "下发单位", "指令类型", "执行时限", "执行人"]
# 状态只沿 待执行 → 执行中 → 已执行 依次流转
STATUS_ORDER = ["待执行", "执行中", "已执行"]
DONE_STATUS = STATUS_ORDER[-1]
# 老指令里可能留下的历史状态，统一并到新状态机
LEGACY_STATUS = {"已完成": "已执行", "已驳回": "待执行"}
# 组合检索口径：执行时限、下发单位、执行人
FILTER_FIELDS = ["执行时限", "下发单位", "执行人"]
DISPLAY_FIELDS = ["指令编号", "下发单位", "指令类型", "下发时间", "执行时限", "执行人", "执行结果", "指令状态"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class DispatchService:
    def __init__(self) -> None:
        self._migrate_legacy_rows()

    # ------------------------------------------------------------------
    # 存量兼容：老指令没有待办条目，按执行时限回填；历史状态并入新状态机
    # ------------------------------------------------------------------
    def _migrate_legacy_rows(self) -> None:
        if getattr(store, "_dispatch_migrated", False):
            return
        for row in store.rows(MODULE):
            status = LEGACY_STATUS.get(str(row.get("status") or ""), str(row.get("status") or ""))
            if status not in STATUS_ORDER:
                status = STATUS_ORDER[0]
            row["status"] = status
            row["指令状态"] = status
            row["pending"] = status != DONE_STATUS
            row["abnormal"] = False

            todo = row.get("待办") if isinstance(row.get("待办"), dict) else {}
            # 待办条目的执行时限按调度指令的执行时限回填
            todo.setdefault("执行时限", row.get("执行时限", ""))
            # 老指令既有的执行结果沿用，不丢历史记录
            todo.setdefault("执行结果", str(row.get("执行结果") or ""))
            todo.setdefault("提交人", row.get("提交人", ""))
            todo.setdefault("提交时间", row.get("提交时间", ""))
            row["待办"] = todo
            # 行内字段与待办条目保持同一份结果，避免两处读出不一样
            row["执行结果"] = todo.get("执行结果", "")
        store._dispatch_migrated = True  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # 统一取数：列表 / 导出共用筛选；单条详情共用序列化
    # ------------------------------------------------------------------
    def _query(
        self,
        *,
        deadline: str | None = None,
        unit: str | None = None,
        operator: str | None = None,
    ) -> list[dict[str, Any]]:
        # 不按状态剔除：已执行（归档）指令也必须能按执行时限等条件查出
        rows = list(store.rows(MODULE))
        needles = (("执行时限", deadline), ("下发单位", unit), ("执行人", operator))
        for field, needle in needles:
            keyword = str(needle or "").strip()
            if keyword:
                rows = [row for row in rows if keyword in str(row.get(field) or "")]
        return rows

    def _serialize(self, row: dict[str, Any]) -> dict[str, Any]:
        todo = row.get("待办") if isinstance(row.get("待办"), dict) else {}
        item: dict[str, Any] = {"id": row.get("id")}
        for field in ("指令编号", "下发单位", "指令类型", "下发时间", "执行时限", "执行人"):
            item[field] = row.get(field, "")
        # 执行结果只认待办条目这一份，列表与详情自然一致
        item["执行结果"] = todo.get("执行结果", "")
        item["指令状态"] = row.get("status")
        item["status"] = row.get("status")
        item["pending"] = row.get("pending", row.get("status") != DONE_STATUS)
        item["abnormal"] = row.get("abnormal", False)
        item["待办"] = {
            "执行时限": todo.get("执行时限", row.get("执行时限", "")),
            "执行结果": todo.get("执行结果", ""),
            "提交人": todo.get("提交人", ""),
            "提交时间": todo.get("提交时间", ""),
        }
        return item

    def list_entries(
        self,
        *,
        deadline: str | None = None,
        unit: str | None = None,
        operator: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._query(deadline=deadline, unit=unit, operator=operator)
        total = len(rows)
        page = max(page, 1)
        start = (page - 1) * size
        return [self._serialize(row) for row in rows[start:start + size]], total

    def export_entries(
        self,
        *,
        deadline: str | None = None,
        unit: str | None = None,
        operator: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._query(deadline=deadline, unit=unit, operator=operator)
        return [self._serialize(row) for row in rows], len(rows)

    def status_stats(self) -> dict[str, int]:
        counts = {status: 0 for status in STATUS_ORDER}
        for row in store.rows(MODULE):
            status = str(row.get("status") or "")
            if status in counts:
                counts[status] += 1
        return counts

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._serialize(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}"]
        rows = store.rows(MODULE)
        code = str(values.get("指令编号") or "").strip()
        if any(str(row.get("指令编号") or "") == code for row in rows):
            return None, [f"指令编号 {code} 已存在，重复登记已拒收"]
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ("指令编号", "下发单位", "指令类型", "下发时间", "执行时限", "执行人"):
            entry[field] = str(values.get(field) or "").strip()
        entry["执行结果"] = ""
        entry["status"] = STATUS_ORDER[0]
        entry["指令状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        # 新指令开立时就带上待办条目，执行时限取自指令本身
        entry["待办"] = {"执行时限": entry["执行时限"], "执行结果": "", "提交人": "", "提交时间": ""}
        rows.append(entry)
        return entry, []

    # ------------------------------------------------------------------
    # 权限：仅下发单位本单位的执行人可改动；跨单位只可查看
    # ------------------------------------------------------------------
    def _same_unit(self, entry: dict[str, Any], unit: str) -> bool:
        unit = str(unit or "").strip()
        return bool(unit) and unit == str(entry.get("下发单位") or "")

    def execute(self, entry_id: int, *, operator: str = "", unit: str = "") -> tuple[dict[str, Any] | None, str]:
        """点「执行」：待执行→执行中；已执行退回执行中（已落库结果保留，不允许覆盖）。

        执行中若无结果，需走结果提交；若是被退回、已留有结果的指令，再点执行即沿用
        已落库的那一条结果恢复为已执行，避免退回后流程走死。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"调度指令 {entry_id} 不存在或已归档"
        if not self._same_unit(entry, unit):
            return None, "跨单位调度指令仅可查看，不能执行或改动"
        status = str(entry.get("status") or "")
        todo = entry.setdefault("待办", {})
        if status == DONE_STATUS:
            entry["status"] = STATUS_ORDER[1]
            entry["指令状态"] = STATUS_ORDER[1]
            entry["pending"] = True
            return entry, "该调度指令已退回「执行中」，已落库执行结果保留，重复提交仍会被原样拒收"
        if status == STATUS_ORDER[0]:
            entry["status"] = STATUS_ORDER[1]
            entry["指令状态"] = STATUS_ORDER[1]
            return entry, "已确认执行，调度指令进入「执行中」，请提交执行结果"
        if status == STATUS_ORDER[1] and str(todo.get("执行结果") or "").strip():
            entry["status"] = DONE_STATUS
            entry["指令状态"] = DONE_STATUS
            entry["pending"] = False
            return entry, "已沿用已落库的执行结果，调度指令恢复为「已执行」"
        return None, "调度指令执行中，请提交执行结果后流转至「已执行」"

    def submit_result(
        self,
        entry_id: int,
        result: str,
        *,
        operator: str = "",
        unit: str = "",
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """提交执行结果：同一指令只收第一条，后来的原样拒收；结果落库到待办条目。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"调度指令 {entry_id} 不存在或已归档", False
        if not self._same_unit(entry, unit):
            return None, "跨单位调度指令仅可查看，不能提交执行结果", False
        result = str(result or "").strip()
        if not result:
            return None, "执行结果不能为空，请填写后再提交", False
        todo = entry.setdefault("待办", {})
        existing = str(todo.get("执行结果") or "").strip()
        if existing:
            # 已有结果即视为重复提交：原样退回，库中第一条结果保持不动
            return entry, f"该指令执行结果已由 {todo.get('提交人') or '前序执行人'} 提交，重复提交已原样拒收", False
        if str(entry.get("status") or "") != STATUS_ORDER[1]:
            return None, f"当前状态为「{entry.get('status')}」，请先确认执行再提交执行结果", False
        todo["执行结果"] = result
        todo["执行时限"] = todo.get("执行时限") or entry.get("执行时限", "")
        todo["提交人"] = str(operator or "").strip()
        todo["提交时间"] = _now()
        entry["执行结果"] = result
        entry["status"] = DONE_STATUS
        entry["指令状态"] = DONE_STATUS
        entry["pending"] = False
        return entry, "执行结果已落库，调度指令流转至「已执行」", True
