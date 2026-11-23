"""Completed PDF snapshots; independent from the SolidWorks task queue."""
from __future__ import annotations
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref
from .review_persistence import Base, PersistenceError, ReviewPersistence, ReviewRecord


class TemplatePdfRecord(Base):
    __tablename__ = "template_pdf_drawings"
    __table_args__ = (
        UniqueConstraint("owner_erp_user_id", "review_job_id", "idempotency_key", name="uq_template_pdf_request"),
        Index("ix_template_pdf_review_created", "review_job_id", "created_at"),
    )
    pdf_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_job_id: Mapped[str] = mapped_column(ForeignKey("drawing_reviews.job_id", ondelete="CASCADE"), nullable=False)
    owner_erp_user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    review_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    technical_requirements_text: Mapped[str] = mapped_column(Text, nullable=False)
    template_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    review = relationship(ReviewRecord, backref=backref("template_pdf_records", cascade="all, delete-orphan"))


def serialize(record):
    return {key: deepcopy(getattr(record, key)) for key in (
        "pdf_id", "review_job_id", "owner_erp_user_id", "review_revision", "idempotency_key", "request_fingerprint", "template_version",
        "parameter_snapshot", "technical_requirements_text", "template_data", "relative_path", "filename"
    )} | {"created_at": (record.created_at if record.created_at.tzinfo else record.created_at.replace(tzinfo=UTC)).isoformat()}


class TemplatePdfStore:
    def __init__(self, repository: ReviewPersistence):
        self.repository = repository

    def available(self) -> bool:
        try:
            with self.repository._session() as session:
                session.execute(select(TemplatePdfRecord.pdf_id).limit(0))
            return True
        except (SQLAlchemyError, PersistenceError):
            return False

    def find_request(self, review_id, owner, key):
        with self.repository._session() as session:
            record = session.scalar(select(TemplatePdfRecord).where(
                TemplatePdfRecord.review_job_id == review_id, TemplatePdfRecord.owner_erp_user_id == owner,
                TemplatePdfRecord.idempotency_key == key))
            return serialize(record) if record else None

    def get(self, pdf_id, owner):
        with self.repository._session() as session:
            record = session.scalar(select(TemplatePdfRecord).where(TemplatePdfRecord.pdf_id == pdf_id, TemplatePdfRecord.owner_erp_user_id == owner))
            return serialize(record) if record else None

    def list(self, review_id, owner):
        with self.repository._session() as session:
            records = session.scalars(select(TemplatePdfRecord).where(TemplatePdfRecord.review_job_id == review_id,
                TemplatePdfRecord.owner_erp_user_id == owner).order_by(TemplatePdfRecord.created_at.desc(), TemplatePdfRecord.pdf_id.desc()))
            return [serialize(record) for record in records]

    def create(self, values):
        with self.repository._session() as session:
            try:
                review = session.get(ReviewRecord, values["review_job_id"])
                if review is None or review.owner_erp_user_id != values["owner_erp_user_id"]:
                    raise PersistenceError("审图记录不存在或无权访问。")
                record = TemplatePdfRecord(**values)
                session.add(record)
                session.commit()
                return serialize(record), True
            except IntegrityError:
                session.rollback()
                existing = self.find_request(values["review_job_id"], values["owner_erp_user_id"], values["idempotency_key"])
                if existing and existing["request_fingerprint"] == values["request_fingerprint"]:
                    return existing, False
                raise PersistenceError("PDF 请求冲突，请刷新后重新出图。")
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError("无法保存模板 PDF 历史，请重试。") from exc
