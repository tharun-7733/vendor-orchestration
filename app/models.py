from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CaseStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    clear = "clear"
    review = "review"
    failed = "failed"
    rejected = "rejected"


class ScreeningCase(Base):
    __tablename__ = "screening_cases"
    __table_args__ = (UniqueConstraint("owner_id", "external_reference", name="uq_screening_cases_owner_reference"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_reference: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    subject_name: Mapped[str] = mapped_column(String(200))
    date_of_birth: Mapped[str | None] = mapped_column(String(10), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    status: Mapped[CaseStatus] = mapped_column(Enum(CaseStatus, name="case_status"), default=CaseStatus.queued)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    results: Mapped[list[VendorResult]] = relationship(back_populates="case", cascade="all, delete-orphan")


class VendorResult(Base):
    __tablename__ = "vendor_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("screening_cases.id", ondelete="CASCADE"), index=True)
    vendor: Mapped[str] = mapped_column(String(40))
    outcome: Mapped[str] = mapped_column(String(20))
    matched: Mapped[bool] = mapped_column(default=False)
    confidence: Mapped[float | None]
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    case: Mapped[ScreeningCase] = relationship(back_populates="results")
