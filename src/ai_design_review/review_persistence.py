from __future__ import annotations

import copy
import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


def database_url_from_env() -> str | None:
    value = str(os.getenv("DATABASE_URL") or "").strip()
    return value or None


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PersistenceError(RuntimeError):
    pass


class RevisionConflictError(PersistenceError):
    def __init__(self, current_revision: int) -> None:
        super().__init__("Review revision is out of date.")
        self.current_revision = current_revision


class Base(DeclarativeBase):
    pass


class ReviewRecord(Base):
    __tablename__ = "drawing_reviews"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    drawing_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    drawing_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    spring_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_info: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    review_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    change_events: Mapped[list["ReviewChangeEvent"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
    )


class ReviewChangeEvent(Base):
    __tablename__ = "review_change_events"
    __table_args__ = (UniqueConstraint("review_job_id", "sequence", name="uq_review_change_event_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_job_id: Mapped[str] = mapped_column(ForeignKey("drawing_reviews.job_id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_before: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_after: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False)
    target_field: Mapped[str | None] = mapped_column(String(192), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    actor: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    review: Mapped[ReviewRecord] = relationship(back_populates="change_events")


class ReviewPersistence:
    """PostgreSQL persistence with an explicit no-database mode for local JSON workflows."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url if database_url is not None else database_url_from_env()
        self._engine = None
        self._session_factory: sessionmaker[Session] | None = None
        if self.database_url:
            pool_size = max(int(os.getenv("DATABASE_POOL_SIZE", "5")), 1)
            max_overflow = max(int(os.getenv("DATABASE_MAX_OVERFLOW", "5")), 0)
            try:
                self._engine = create_engine(
                    self.database_url,
                    pool_pre_ping=True,
                    pool_size=pool_size,
                    max_overflow=max_overflow,
                )
                self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
            except SQLAlchemyError as exc:
                raise PersistenceError(f"Unable to create database engine: {exc}") from exc

    @property
    def configured(self) -> bool:
        return self._session_factory is not None

    def health(self, *, check_connection: bool = False) -> dict[str, Any]:
        if not self.configured:
            return {"status": "not_configured", "mode": "json_fallback"}
        if not check_connection:
            return {"status": "configured", "mode": "postgresql"}
        try:
            assert self._engine is not None
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return {"status": "available", "mode": "postgresql"}
        except SQLAlchemyError as exc:
            return {"status": "unavailable", "mode": "postgresql", "reason": _safe_error(exc)}

    def create_schema_for_testing(self) -> None:
        if not self._engine:
            raise PersistenceError("DATABASE_URL is not configured.")
        Base.metadata.create_all(self._engine)

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()

    def create_review(
        self,
        job_id: str,
        review: dict[str, Any],
        *,
        file_info: dict[str, Any] | None = None,
        artifact_dir: str | None = None,
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            return {"mode": "json_fallback", "revision": None, "events": []}
        with self._session() as session:
            try:
                existing = session.get(ReviewRecord, job_id)
                if existing is not None:
                    return {"mode": "postgresql", "revision": existing.revision, "events": []}
                record = self._new_record(job_id, review, file_info=file_info, artifact_dir=artifact_dir)
                session.add(record)
                event = self._make_event(
                    record,
                    revision_before=0,
                    revision_after=record.revision,
                    payload={
                        "event_type": "review_created",
                        "source": "recognition",
                        "actor": actor,
                        "reason": "图纸识别结果已创建",
                    },
                )
                session.add(event)
                session.commit()
                return {"mode": "postgresql", "revision": record.revision, "events": [self._serialize_event(event)]}
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to create review: {_safe_error(exc)}") from exc

    def get_review(self, job_id: str) -> dict[str, Any] | None:
        if not self.configured:
            return None
        try:
            with self._session() as session:
                record = session.get(ReviewRecord, job_id)
                if record is None:
                    return None
                return {
                    "review": copy.deepcopy(record.review_snapshot),
                    "revision": record.revision,
                    "file_info": copy.deepcopy(record.file_info),
                }
        except SQLAlchemyError as exc:
            raise PersistenceError(f"Unable to read review: {_safe_error(exc)}") from exc

    def save_review(
        self,
        job_id: str,
        review: dict[str, Any],
        *,
        expected_revision: int | None = None,
        events: list[dict[str, Any]] | None = None,
        file_info: dict[str, Any] | None = None,
        artifact_dir: str | None = None,
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            return {"mode": "json_fallback", "revision": None, "events": []}
        with self._session() as session:
            try:
                record = session.execute(
                    select(ReviewRecord).where(ReviewRecord.job_id == job_id).with_for_update()
                ).scalar_one_or_none()
                if record is None:
                    record = self._new_record(job_id, review, file_info=file_info, artifact_dir=artifact_dir)
                    session.add(record)
                    revision_before = 0
                else:
                    if expected_revision is not None and expected_revision != record.revision:
                        raise RevisionConflictError(record.revision)
                    revision_before = record.revision
                    record.review_snapshot = copy.deepcopy(review)
                    if file_info is not None:
                        record.file_info = copy.deepcopy(file_info)
                    if artifact_dir is not None:
                        record.artifact_dir = artifact_dir
                    _apply_summary(record, review)
                    record.revision += 1
                    record.updated_at = _utcnow()

                revision_after = record.revision
                created_events: list[ReviewChangeEvent] = []
                for payload in events or []:
                    event = self._make_event(
                        record,
                        revision_before=revision_before,
                        revision_after=revision_after,
                        payload={**payload, "actor": payload.get("actor") or actor},
                    )
                    session.add(event)
                    created_events.append(event)
                session.commit()
                return {
                    "mode": "postgresql",
                    "revision": record.revision,
                    "events": [self._serialize_event(event) for event in created_events],
                }
            except RevisionConflictError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to save review: {_safe_error(exc)}") from exc

    def list_change_events(self, job_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        bounded_limit = min(max(limit, 1), 500)
        try:
            with self._session() as session:
                rows = session.execute(
                    select(ReviewChangeEvent)
                    .where(ReviewChangeEvent.review_job_id == job_id)
                    .order_by(ReviewChangeEvent.sequence.desc())
                    .limit(bounded_limit)
                ).scalars()
                return [self._serialize_event(item) for item in rows]
        except SQLAlchemyError as exc:
            raise PersistenceError(f"Unable to read audit events: {_safe_error(exc)}") from exc

    def list_reviews(self, *, limit: int = 30) -> list[dict[str, Any]]:
        """Return lightweight review metadata for the resume list, newest first."""
        if not self.configured:
            return []
        bounded_limit = min(max(limit, 1), 100)
        try:
            with self._session() as session:
                rows = session.execute(
                    select(ReviewRecord)
                    .order_by(ReviewRecord.updated_at.desc())
                    .limit(bounded_limit)
                ).scalars()
                return [self._serialize_review_list_item(item) for item in rows]
        except SQLAlchemyError as exc:
            raise PersistenceError(f"Unable to list reviews: {_safe_error(exc)}") from exc

    def delete_review(self, job_id: str) -> bool:
        """Delete a review and its cascade-owned audit events."""
        if not self.configured:
            return False
        with self._session() as session:
            try:
                record = session.get(ReviewRecord, job_id)
                if record is None:
                    return False
                session.delete(record)
                session.commit()
                return True
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to delete review: {_safe_error(exc)}") from exc

    def _session(self) -> Session:
        if not self._session_factory:
            raise PersistenceError("DATABASE_URL is not configured.")
        return self._session_factory()

    @staticmethod
    def _new_record(
        job_id: str,
        review: dict[str, Any],
        *,
        file_info: dict[str, Any] | None,
        artifact_dir: str | None,
    ) -> ReviewRecord:
        summary = review.get("drawing_summary") if isinstance(review.get("drawing_summary"), dict) else {}
        return ReviewRecord(
            job_id=job_id,
            drawing_no=_optional_text(summary.get("drawing_no")),
            drawing_name=_optional_text(summary.get("drawing_name")),
            spring_type=_optional_text(summary.get("spring_type")),
            artifact_dir=artifact_dir,
            file_info=copy.deepcopy(file_info),
            review_snapshot=copy.deepcopy(review),
            revision=1,
            event_sequence=0,
        )

    @staticmethod
    def _make_event(
        record: ReviewRecord,
        *,
        revision_before: int,
        revision_after: int,
        payload: dict[str, Any],
    ) -> ReviewChangeEvent:
        record.event_sequence += 1
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None
        return ReviewChangeEvent(
            review_job_id=record.job_id,
            sequence=record.event_sequence,
            revision_before=revision_before,
            revision_after=revision_after,
            event_type=str(payload.get("event_type") or "review_updated")[:96],
            target_field=_optional_text(payload.get("target_field"), 192),
            source=str(payload.get("source") or "system")[:64],
            actor=copy.deepcopy(payload.get("actor")) if isinstance(payload.get("actor"), dict) else None,
            reason=_optional_text(payload.get("reason"), 2000),
            before_state=copy.deepcopy(payload.get("before_state")) if isinstance(payload.get("before_state"), dict) else None,
            after_state=copy.deepcopy(payload.get("after_state")) if isinstance(payload.get("after_state"), dict) else None,
            event_metadata=copy.deepcopy(metadata),
        )

    @staticmethod
    def _serialize_event(event: ReviewChangeEvent) -> dict[str, Any]:
        metadata = copy.deepcopy(event.event_metadata) if isinstance(event.event_metadata, dict) else {}
        return {
            "id": event.id,
            "client_event_id": metadata.get("client_event_id"),
            "sequence": event.sequence,
            "revision_before": event.revision_before,
            "revision_after": event.revision_after,
            "event_type": event.event_type,
            "target_field": event.target_field,
            "source": event.source,
            "actor": copy.deepcopy(event.actor),
            "reason": event.reason,
            "before_state": copy.deepcopy(event.before_state),
            "after_state": copy.deepcopy(event.after_state),
            "metadata": metadata,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }

    @staticmethod
    def _serialize_review_list_item(record: ReviewRecord) -> dict[str, Any]:
        snapshot = record.review_snapshot if isinstance(record.review_snapshot, dict) else {}
        summary = snapshot.get("drawing_summary") if isinstance(snapshot.get("drawing_summary"), dict) else {}
        return {
            "job_id": record.job_id,
            "drawing_no": record.drawing_no,
            "drawing_name": record.drawing_name,
            "spring_type": record.spring_type,
            "overall_status": _optional_text(summary.get("overall_status")),
            "revision": record.revision,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }


def _apply_summary(record: ReviewRecord, review: dict[str, Any]) -> None:
    summary = review.get("drawing_summary") if isinstance(review.get("drawing_summary"), dict) else {}
    record.drawing_no = _optional_text(summary.get("drawing_no"))
    record.drawing_name = _optional_text(summary.get("drawing_name"))
    record.spring_type = _optional_text(summary.get("spring_type"))


def _optional_text(value: Any, limit: int | None = None) -> str | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    return text_value[:limit] if limit else text_value


def _safe_error(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:500]
