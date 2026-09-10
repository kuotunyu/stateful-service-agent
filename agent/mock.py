"""Explicitly a small, deterministic demo parser, not an LLM capability result."""

import re
from datetime import datetime, timedelta

from agent.service import TAIPEI


def parse(text, previous, bookings, now):
    text = text.strip()
    if any(word in text for word in ("先不要", "算了", "不用了", "取消這次操作", "放棄")):
        return {"kind": "abandon"}
    if any(word in text for word in ("查詢", "查看", "有哪些", "目前預約")):
        return {"kind": "query"}
    if re.search(r"下[週周]|[週周]末|星期|禮拜|下個月", text):
        return {
            "kind": "help",
            "text": "免費示範尚不支援這種日期說法。請用今天、明天、後天或 YYYY-MM-DD，或用表單選時間。目前尚未修改預約。",
        }
    active = [b for b in bookings if b["status"] == "active"]
    pending = previous and previous["status"] in ("draft", "waiting_confirmation", "executing")
    payload = dict(previous["payload"]) if pending else {}
    if "取消" in text:
        payload = {"action": "cancel"}
    elif any(word in text for word in ("改期", "改成", "改到")):
        if not pending or payload.get("action") not in ("create", "reschedule"):
            payload = {"action": "reschedule"}
    elif "預約" in text:
        if payload.get("action") not in (None, "create"):
            payload = {"action": "create"}
        else:
            payload.setdefault("action", "create")
    if not payload:
        return {"kind": "help"}
    if "冷氣" in text:
        payload["service"] = "冷氣維修"
    elif "洗衣機" in text:
        payload["service"] = "洗衣機維修"
    if payload["action"] != "create":
        mentioned = [b for b in active if b["id"] in text]
        if len(mentioned) == 1:
            payload["booking_id"] = mentioned[0]["id"]
        elif len(active) == 1:
            payload.setdefault("booking_id", active[0]["id"])
    today = datetime.fromtimestamp(now, TAIPEI).date()
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    day = date_match.group(1) if date_match else None
    if not day:
        if "後天" in text:
            day = (today + timedelta(days=2)).isoformat()
        elif "明天" in text:
            day = (today + timedelta(days=1)).isoformat()
        elif "今天" in text:
            day = today.isoformat()
    clock_match = re.search(r"(?<!\d)(\d{1,2}):([0-5]\d)(?!\d)", text)
    hour_match = re.search(r"(上午|下午)?\s*(十|兩|二|四|\d{1,2})點", text)
    hour = minute = None
    if clock_match:
        hour, minute = int(clock_match[1]), int(clock_match[2])
    elif hour_match:
        digits = {"十": 10, "兩": 2, "二": 2, "四": 4}
        hour = digits.get(hour_match[2], int(hour_match[2]) if hour_match[2].isdigit() else 0)
        if hour_match[1] == "下午" and hour < 12:
            hour += 12
        minute = 0
    if day:
        payload["date"] = day
    if hour is not None:
        payload["time"] = f"{hour:02d}:{minute:02d}"
    day = day or payload.get("date")
    if hour is None and payload.get("time"):
        hour, minute = map(int, payload["time"].split(":"))
    old_slot = payload.get("slot")
    if day and hour is None and old_slot:
        hour, minute = datetime.fromisoformat(old_slot).hour, 0
    if hour is not None and not day and old_slot:
        day = old_slot[:10]
    if day and hour is not None:
        payload["slot"] = f"{day}T{hour:02d}:{minute:02d}:00+08:00"
    return {"kind": "proposal", "proposal": payload}


def describe(op):
    if op["status"] == "waiting_confirmation":
        return "已整理好操作內容。請查看確認單；確認後才會修改預約。"
    missing = []
    payload = op["payload"]
    if op["action"] != "create" and not payload.get("booking_id"):
        missing.append("要操作的預約（可使用預約卡上的按鈕）")
    if op["action"] == "create" and not payload.get("service"):
        missing.append("維修項目：冷氣或洗衣機")
    if op["action"] != "cancel" and not payload.get("slot"):
        missing.append("日期與時段，例如：明天 14:00")
    return "請補上" + "、".join(missing) + "。目前尚未修改預約。"
