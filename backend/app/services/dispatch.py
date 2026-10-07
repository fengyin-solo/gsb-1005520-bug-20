"""调度指令业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.store import store

MODULE = "dispatch"
REQUIRED_FIELDS = ["指令编号", "下发单位", "指令类型"]
OPTIONAL_FIELDS = ["下发时间", "执行时限", "执行人"]
STATUS_ORDER = ["待执行", "执行中", "已执行"]
LEGACY_STATUS_ALIASES = {"已完成": "已执行"}
ARCHIVED_STATUSES = {"已执行", "已驳回"}
DEFAULT_RESULT_BY_STATUS = {
    "待执行": "待执行",
    "执行中": "已确认，执行中",
    "已执行": "按期执行完成",
    "已驳回": "指令被驳回",
}
# 动作 -> (允许发起的当前状态, 目标状态)：指令沿 待执行→执行中→已执行 依次流转
ACTION_RULES = {
    "确认执行": (("待执行",), "执行中"),
    "完成回复": (("执行中",), "已执行"),
    "驳回指令": (("待执行", "执行中"), "已驳回"),
}
NEGATIVE_ACTIONS = {"驳回指令"}
DEFAULT_DEADLINE_DAYS = 2
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_status(status: Any) -> str:
    """老指令可能还挂着历史状态名（已完成），统一映射到现行状态序列。"""
    text = str(status or "").strip()
    return LEGACY_STATUS_ALIASES.get(text, text)


class DispatchService:
    def __init__(self) -> None:
        self._backfill_rows()

    def _backfill_rows(self) -> None:
        """存量数据兼容：老指令缺执行时限、执行结果的按既有记录补齐，状态名统一。"""
        for row in store.rows(MODULE):
            status = _normalize_status(row.get("status"))
            row["status"] = status
            row["指令状态"] = status
            if not _parse_date(row.get("执行时限")):
                issued = _parse_date(row.get("下发时间"))
                row["执行时限"] = (
                    (issued + timedelta(days=DEFAULT_DEADLINE_DAYS)).isoformat() if issued else ""
                )
            if not str(row.get("执行结果") or "").strip():
                row["执行结果"] = DEFAULT_RESULT_BY_STATUS.get(status, "待执行")
            row["pending"] = status in STATUS_ORDER[:2]
            row["abnormal"] = status == "已驳回"

    def _serialize(self, row: dict[str, Any]) -> dict[str, Any]:
        """列表与单条详情共用同一份输出，执行结果两处不会打架。"""
        data = dict(row)
        status = _normalize_status(data.get("status"))
        data["status"] = status
        data["指令状态"] = status
        if not str(data.get("执行结果") or "").strip():
            data["执行结果"] = DEFAULT_RESULT_BY_STATUS.get(status, "待执行")
        data["已归档"] = status in ARCHIVED_STATUSES
        return data

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        unit: str | None = None,
        executor: str | None = None,
        deadline: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword.strip() in str(row.get("指令编号", ""))]
        if status:
            wanted = _normalize_status(status)
            rows = [row for row in rows if _normalize_status(row.get("status")) == wanted]
        if unit:
            rows = [row for row in rows if unit.strip() in str(row.get("下发单位", ""))]
        if executor:
            rows = [row for row in rows if executor.strip() in str(row.get("执行人", ""))]
        if deadline:
            rows = [row for row in rows if self._match_deadline(row.get("执行时限"), deadline)]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._serialize(row) for row in rows[start:start + size]], total

    @staticmethod
    def _match_deadline(value: Any, query: str) -> bool:
        """执行时限按日期精确比对；已归档的指令同样参与匹配，不会被漏掉。"""
        text = str(value or "").strip()
        query = query.strip()
        if not query:
            return True
        wanted = _parse_date(query)
        current = _parse_date(text)
        if wanted and current:
            return current == wanted
        return query in text

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._serialize(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        rows = store.rows(MODULE)
        code = str(values.get("指令编号") or "").strip()
        if any(str(row.get("指令编号", "")).strip() == code for row in rows):
            return None, f"指令编号 {code} 已存在，重复提交原样拒收"
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            entry[field] = str(values.get(field) or "").strip()
        if not entry["下发时间"]:
            entry["下发时间"] = date.today().isoformat()
        if not _parse_date(entry["执行时限"]):
            issued = _parse_date(entry["下发时间"])
            entry["执行时限"] = (
                (issued + timedelta(days=DEFAULT_DEADLINE_DAYS)).isoformat() if issued else ""
            )
        entry["status"] = STATUS_ORDER[0]
        entry["指令状态"] = STATUS_ORDER[0]
        entry["执行结果"] = DEFAULT_RESULT_BY_STATUS[STATUS_ORDER[0]]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._serialize(entry), ""

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"调度指令单 {entry_id} 不存在"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于调度指令可执行范围"
        operator_unit = str(values.get("操作单位") or "").strip()
        owner_unit = str(entry.get("下发单位") or "").strip()
        if operator_unit and owner_unit and operator_unit != owner_unit:
            return None, f"该指令由{owner_unit}下发，跨单位仅可查看，不能改动"
        allowed, target = ACTION_RULES[action]
        current = _normalize_status(entry.get("status"))
        if current not in allowed:
            flow = "→".join(STATUS_ORDER)
            return None, f"指令当前状态为「{current}」，{action}被退回：指令需沿「{flow}」依次流转"
        entry["status"] = target
        entry["指令状态"] = target
        result_text = str(values.get("执行结果") or "").strip()
        entry["执行结果"] = result_text or DEFAULT_RESULT_BY_STATUS.get(target, "")
        entry["pending"] = target in STATUS_ORDER[:2]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self._serialize(entry), f"调度指令单已{action}"

    def stats(self) -> dict[str, int]:
        counts = {status: 0 for status in [*STATUS_ORDER, "已驳回"]}
        for row in store.rows(MODULE):
            status = _normalize_status(row.get("status"))
            if status in counts:
                counts[status] += 1
        return counts
