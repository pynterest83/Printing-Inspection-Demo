from datetime import datetime, timezone

import pytest

from app.database import Database


def test_roll_history_survives_new_roll(tmp_path):
    database = Database(tmp_path)
    now = datetime.now(timezone.utc)
    database.create_roll("ROLL-1", "IDLE", now)
    database.update_roll(
        "ROLL-1",
        status="RESET",
        total_m=42.0,
        good_m=40.0,
        bad_m=2.0,
        now=now,
        final=True,
        stop_reason="Operator reset",
    )
    database.create_roll("ROLL-2", "IDLE", now)

    page = database.list_rolls(10, 0)
    assert page["total"] == 2
    archived = next(item for item in page["items"] if item["roll_id"] == "ROLL-1")
    assert archived["status"] == "RESET"
    assert archived["bad_ratio"] == pytest.approx(4.762, abs=0.001)
