from app.domain import normalize_session, split_subject


def test_split_subject():
    assert split_subject("Mathematics — Integration") == ("Mathematics", "Integration")
    assert split_subject("CS - Trees") == ("CS", "Trees")
    assert split_subject("Physics") == ("Physics", None)
    assert split_subject("") == ("General", None)


def test_legacy_pomodoro_derives_start_and_is_unlabelled():
    s = normalize_session({"id": "a", "subject": "X", "duration": 25, "type": "pomodoro",
                           "date": "2026-11-20T10:30:00Z"}, "Asia/Kolkata")
    assert not s.labelled and s.completed
    assert s.start_utc.isoformat() == "2026-11-20T10:05:00+00:00"
    assert s.hour == 15 and s.local_start.minute == 35   # 10:05Z = 15:35 IST


def test_legacy_manual_has_no_start_time():
    s = normalize_session({"subject": "X", "duration": 40, "type": "manual",
                           "date": "2026-11-20T10:30:00Z"}, "Asia/Kolkata")
    assert s.local_start is None and s.hour is None


def test_unknown_timezone_means_no_hour():
    s = normalize_session({"subject": "X", "duration": 25, "type": "pomodoro",
                           "date": "2026-11-20T10:30:00Z"}, None)
    assert s.hour is None


def test_new_style_row_uses_its_own_fields():
    s = normalize_session({"subject": "X", "duration": 25, "plannedDuration": 25,
                           "actualDuration": 9, "status": "abandoned", "type": "pomodoro",
                           "startedAt": "2026-11-21T09:00:00Z", "endedAt": "2026-11-21T09:09:00Z",
                           "tz": "Asia/Kolkata", "date": "2026-11-21T09:09:00Z"})
    assert s.labelled and s.status == "abandoned"
    assert s.planned_min == 25 and s.actual_min == 9 and s.hour == 14


def test_garbage_is_rejected():
    assert normalize_session({"subject": "X", "date": "nope"}) is None
