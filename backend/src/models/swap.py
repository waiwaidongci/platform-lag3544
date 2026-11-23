from datetime import datetime
from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
from src.constants.enums import SwapState
from src.utils.time import now

class CalibrationBatch(Base):
    __tablename__ = 'calibration_batches'
    __table_args__ = (UniqueConstraint('name', 'checksum'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    station: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(120))
    filename: Mapped[str] = mapped_column(String(160))
    checksum: Mapped[str] = mapped_column(String(64))
    rows: Mapped[list] = mapped_column(JSON)
    row_count: Mapped[int]
    channels: Mapped[list] = mapped_column(JSON)
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)

class TonePeriod(Base):
    __tablename__ = 'tone_periods'
    __table_args__ = (UniqueConstraint('station', 'point', 'start', 'end'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    station: Mapped[str] = mapped_column(String(120), index=True)
    point: Mapped[str] = mapped_column(String(120))
    start: Mapped[str] = mapped_column(String(19))
    end: Mapped[str] = mapped_column(String(19))
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)

class SwapDetermination(Base):
    __tablename__ = 'swap_determinations'
    __table_args__ = (UniqueConstraint('station', 'version'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    station: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int]
    batch_id: Mapped[int] = mapped_column(ForeignKey('calibration_batches.id'))
    tone_fingerprint: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default=SwapState.COMPUTED, index=True)
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)
    published_at: Mapped[datetime | None]

class SwapPublication(Base):
    __tablename__ = 'swap_publications'

    id: Mapped[int] = mapped_column(primary_key=True)
    determination_id: Mapped[int] = mapped_column(ForeignKey('swap_determinations.id'), unique=True)
    station: Mapped[str] = mapped_column(String(120), index=True)
    export_file: Mapped[str | None] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(String(500))
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)
