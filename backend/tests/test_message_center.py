from datetime import datetime, timedelta, timezone

from orbit.application.data_update_scheduler import DataUpdateScheduler
from orbit.application.message_center import MessageCenter


class Notifier:
    def __init__(self): self.sent = []
    def send(self, payload): self.sent.append(payload); return {"ok": True}


def test_messages_are_append_only_and_read_state_is_separate(tmp_path):
    center = MessageCenter(tmp_path)
    first = center.append(level="info", kind="signal", title="新信号", summary="已记录")
    center.append(level="important", kind="configuration", title="设置已变更", summary="可回查")
    assert center.list()["unread_count"] == 2
    center.mark_read(first["id"])
    assert center.list()["unread_count"] == 1
    assert len((tmp_path / "messages.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    center.mark_all_read()
    assert center.list()["unread_count"] == 0


def test_push_rules_keep_errors_outside_signal_quota(tmp_path):
    notifier = Notifier()
    center = MessageCenter(tmp_path, notifier=notifier, push_important=False)
    center.append(level="info", kind="signal", title="信号", summary="仅站内")
    center.append(level="important", kind="system", title="重要", summary="按设置不推")
    center.append(level="error", kind="risk", title="资金风险", summary="自动推送")
    assert [item["title"] for item in notifier.sent] == ["资金风险"]


def test_daily_update_retries_hourly_and_alerts_after_two_failed_days(tmp_path):
    center = MessageCenter(tmp_path)
    calls = []
    def fail(): calls.append(1); raise RuntimeError("archive unavailable")
    scheduler = DataUpdateScheduler(fail, center)
    start = datetime(2026, 8, 15, 1, tzinfo=timezone.utc)
    for day in range(2):
        for attempt in range(3):
            scheduler.run_due(start + timedelta(days=day, hours=attempt))
    assert len(calls) == 6
    assert scheduler.state["consecutive_failed_days"] == 2
    alerts = center.list(kind="data")["items"]
    assert alerts[0]["level"] == "error"


def test_daily_update_success_resets_failure_streak(tmp_path):
    center = MessageCenter(tmp_path)
    scheduler = DataUpdateScheduler(lambda: {"status": "queued"}, center)
    now = datetime(2026, 8, 15, 1, tzinfo=timezone.utc)
    assert scheduler.run_due(now) is True
    assert scheduler.due(now + timedelta(minutes=10)) is False
    assert scheduler.state["last_success_at"]
