from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text, create_engine, func, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class RollRecord(Base):
    __tablename__ = "rolls"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    total_m: Mapped[float] = mapped_column(Float, default=0.0)
    good_m: Mapped[float] = mapped_column(Float, default=0.0)
    bad_m: Mapped[float] = mapped_column(Float, default=0.0)
    stop_reason: Mapped[str | None] = mapped_column(String(255))


class DefectRecord(Base):
    __tablename__ = "defects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    annotation_id: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    roll_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    lane_id: Mapped[int] = mapped_column(Integer, nullable=False)
    position_m: Mapped[float] = mapped_column(Float, nullable=False)
    end_position_m: Mapped[float] = mapped_column(Float, nullable=False)
    defect_type: Mapped[str] = mapped_column(String, nullable=False)
    defect_name: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    area_mm2: Mapped[float | None] = mapped_column(Float)
    length_mm: Mapped[float | None] = mapped_column(Float)
    bbox_json: Mapped[str] = mapped_column(Text, nullable=False)
    image_path: Mapped[str | None] = mapped_column(Text)


class AlarmRecord(Base):
    __tablename__ = "alarms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    roll_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    lane_id: Mapped[int | None] = mapped_column(Integer)
    position_m: Mapped[float] = mapped_column(Float, nullable=False)


def _utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class Database:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "inspection.db"
        self.engine = create_engine(
            f"sqlite:///{self.path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql("PRAGMA synchronous=NORMAL")

    def interrupt_open_rolls(self, now: datetime) -> None:
        with Session(self.engine) as session:
            session.execute(
                update(RollRecord)
                .where(RollRecord.status.in_(["IDLE", "RUNNING", "STOPPED", "PLC_STOP"]))
                .values(status="INTERRUPTED", ended_at=now, stop_reason="Backend restarted")
            )
            session.commit()

    def create_roll(self, roll_id: str, status: str, now: datetime) -> None:
        with Session(self.engine) as session:
            session.add(
                RollRecord(
                    id=roll_id,
                    created_at=now,
                    started_at=now if status == "RUNNING" else None,
                    status=status,
                    total_m=0.0,
                    good_m=0.0,
                    bad_m=0.0,
                )
            )
            session.commit()

    def update_roll(
        self,
        roll_id: str,
        *,
        status: str,
        total_m: float,
        good_m: float,
        bad_m: float,
        now: datetime,
        final: bool = False,
        stop_reason: str | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": status,
            "total_m": total_m,
            "good_m": good_m,
            "bad_m": bad_m,
            "stop_reason": stop_reason,
        }
        if status == "RUNNING":
            values["started_at"] = func.coalesce(RollRecord.started_at, now)
        if final:
            values["ended_at"] = now
        with Session(self.engine) as session:
            session.execute(update(RollRecord).where(RollRecord.id == roll_id).values(**values))
            session.commit()

    def add_defect(self, data: dict[str, Any], image_path: str | None) -> None:
        with Session(self.engine) as session:
            session.add(
                DefectRecord(
                    id=data["id"],
                    annotation_id=data["annotation_id"],
                    timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")),
                    roll_id=data["roll_id"],
                    lane_id=data["lane_id"],
                    position_m=data["position_m"],
                    end_position_m=data["end_position_m"],
                    defect_type=data["defect_type"],
                    defect_name=data["defect_name"],
                    confidence=data["confidence"],
                    severity=data["severity"],
                    area_mm2=data.get("area_mm2"),
                    length_mm=data.get("length_mm"),
                    bbox_json=json.dumps(data["bbox"]),
                    image_path=image_path,
                )
            )
            session.commit()

    def add_alarm(self, data: dict[str, Any]) -> None:
        with Session(self.engine) as session:
            session.add(
                AlarmRecord(
                    timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")),
                    roll_id=data["roll_id"],
                    level=data["level"],
                    code=data["code"],
                    message=data["message"],
                    lane_id=data.get("lane_id"),
                    position_m=data["position_m"],
                )
            )
            session.commit()

    def list_rolls(self, limit: int, offset: int) -> dict[str, Any]:
        with Session(self.engine) as session:
            total = session.scalar(select(func.count()).select_from(RollRecord)) or 0
            rows = session.scalars(
                select(RollRecord).order_by(RollRecord.created_at.desc()).limit(limit).offset(offset)
            ).all()
            return {
                "items": [self._roll_dict(row) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def list_defects(self, roll_id: str | None, limit: int, offset: int) -> dict[str, Any]:
        query = select(DefectRecord)
        count_query = select(func.count()).select_from(DefectRecord)
        if roll_id:
            query = query.where(DefectRecord.roll_id == roll_id)
            count_query = count_query.where(DefectRecord.roll_id == roll_id)
        with Session(self.engine) as session:
            total = session.scalar(count_query) or 0
            rows = session.scalars(
                query.order_by(DefectRecord.timestamp.desc()).limit(limit).offset(offset)
            ).all()
            return {
                "items": [self._defect_dict(row) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def get_defect(self, defect_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(DefectRecord, defect_id)
            return self._defect_dict(row) if row else None

    def defect_image_path(self, defect_id: str) -> str | None:
        with Session(self.engine) as session:
            row = session.get(DefectRecord, defect_id)
            return row.image_path if row else None

    @staticmethod
    def _roll_dict(row: RollRecord) -> dict[str, Any]:
        ratio = row.bad_m / row.total_m * 100 if row.total_m else 0.0
        return {
            "roll_id": row.id,
            "created_at": _utc(row.created_at),
            "started_at": _utc(row.started_at),
            "ended_at": _utc(row.ended_at),
            "status": row.status,
            "total_m": round(row.total_m, 3),
            "good_m": round(row.good_m, 3),
            "bad_m": round(row.bad_m, 3),
            "bad_ratio": round(ratio, 3),
            "stop_reason": row.stop_reason,
        }

    @staticmethod
    def _defect_dict(row: DefectRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "annotation_id": row.annotation_id,
            "timestamp": _utc(row.timestamp),
            "roll_id": row.roll_id,
            "lane_id": row.lane_id,
            "position_m": round(row.position_m, 3),
            "end_position_m": round(row.end_position_m, 3),
            "defect_type": row.defect_type,
            "defect_name": row.defect_name,
            "confidence": row.confidence,
            "severity": row.severity,
            "area_mm2": row.area_mm2,
            "length_mm": row.length_mm,
            "bbox": json.loads(row.bbox_json),
            "image_url": f"/api/defects/{row.id}/thumbnail.jpg" if row.image_path else None,
        }

