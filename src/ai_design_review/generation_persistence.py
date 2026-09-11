from __future__ import annotations

import copy
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from .review_persistence import Base, PersistenceError, ReviewPersistence


class SolidWorksTaskCancelledError(PersistenceError):
    """Raised when a SolidWorks callback reaches a user-cancelled task."""


SOLIDWORKS_STAGE_ERRORS: dict[str, tuple[str, str]] = {
    "generating_3d_error": ("solidworks_3d_generation_failed", "SolidWorks 三维模型生成失败。"),
    "generating_2d_error": ("solidworks_2d_generation_failed", "SolidWorks 二维图生成失败。"),
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


class GenerationTemplateRecord(Base):
    __tablename__ = "generation_templates"
    __table_args__ = (
        UniqueConstraint("template_code", "version", name="uq_generation_template_version"),
        Index("ix_generation_templates_enabled_type", "enabled", "drawing_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_code: Mapped[str] = mapped_column(String(192), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    drawing_type: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    required_fields: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    match_rules: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    parameter_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    worker_capability: Mapped[str] = mapped_column(String(192), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class GenerationJobRecord(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "owner_erp_user_id",
            "review_job_id",
            "idempotency_key",
            name="uq_generation_job_idempotency",
        ),
        Index("ix_generation_jobs_status_created", "status", "created_at"),
        Index("ix_generation_jobs_review_created", "review_job_id", "created_at"),
        Index("ix_generation_jobs_lease", "status", "lease_expires_at"),
        Index(
            "uq_generation_jobs_final_review",
            "review_job_id",
            unique=True,
            postgresql_where=text("is_final"),
            sqlite_where=text("is_final = 1"),
        ),
    )

    generation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_job_id: Mapped[str] = mapped_column(
        ForeignKey("drawing_reviews.job_id", ondelete="CASCADE"), nullable=False
    )
    review_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_generation_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_jobs.generation_id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_erp_user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    owner_username: Mapped[str | None] = mapped_column(String(256), nullable=True)
    owner_real_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    owner_org_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    owner_org_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    template_code: Mapped[str] = mapped_column(String(192), nullable=False)
    template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_capability: Mapped[str] = mapped_column(String(192), nullable=False)
    parameter_schema_version: Mapped[str] = mapped_column(String(96), nullable=False)
    parameter_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_package: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    readiness: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    requested_artifact_types: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    execution_options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    preview_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    preview_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    preview_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_by: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class GenerationArtifactRecord(Base):
    __tablename__ = "generation_artifacts"
    __table_args__ = (Index("ix_generation_artifacts_job", "generation_id", "created_at"),)

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    generation_id: Mapped[str] = mapped_column(
        ForeignKey("generation_jobs.generation_id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class GenerationEventRecord(Base):
    __tablename__ = "generation_events"
    __table_args__ = (
        UniqueConstraint("generation_id", "sequence", name="uq_generation_event_sequence"),
        Index("ix_generation_events_job", "generation_id", "sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generation_id: Mapped[str] = mapped_column(
        ForeignKey("generation_jobs.generation_id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class GenerationStore:
    """Generation persistence sharing the review repository's database sessions."""

    def __init__(self, repository: ReviewPersistence) -> None:
        self.repository = repository

    @property
    def configured(self) -> bool:
        return self.repository.configured

    def create_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_database()
        with self.repository._session() as session:
            try:
                record = GenerationTemplateRecord(**copy.deepcopy(payload))
                session.add(record)
                session.commit()
                return self._template(record)
            except IntegrityError as exc:
                session.rollback()
                raise PersistenceError("Generation template version already exists.") from exc
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to create generation template: {exc}") from exc

    def ensure_mock_template(self, *, enabled: bool) -> dict[str, Any]:
        for legacy_version in ("v1", "v2", "v3"):
            legacy = self.get_template("mock/compression-spring", legacy_version, include_disabled=True)
            if legacy and legacy["enabled"]:
                self.set_template_status("mock/compression-spring", legacy_version, enabled=False)
        existing = self.get_template("mock/compression-spring", "v4", include_disabled=True)
        if existing:
            if existing["enabled"] != enabled:
                return self.set_template_status("mock/compression-spring", "v4", enabled=enabled)
            return existing
        return self.create_template(
            {
                "template_code": "mock/compression-spring",
                "version": "v4",
                "drawing_type": "compression_spring",
                "label": "模拟圆柱螺旋压缩弹簧（冻结协议 V2）",
                "priority": 1003,
                "enabled": enabled,
                "is_mock": True,
                "required_fields": [
                    "wire_diameter", "mean_diameter", "free_length", "total_coils",
                    "active_coils", "handedness", "end_grinding", "end_coils_closed",
                ],
                "match_rules": {},
                "parameter_mapping": {
                    "material": "SolidWorks material / 二维图材料标注",
                    "wire_diameter": "直径",
                    "mean_diameter": "中径",
                    "free_length": "自由高度",
                    "total_coils": "圈数",
                    "active_coils": "有效圈数",
                    "handedness": "api_control",
                    "end_grinding": "两端磨削",
                    "end_coils_closed": "端圈压并",
                },
                "worker_capability": "mock_solidworks_compression_v2",
            }
        )

    def ensure_solidworks_push_template(self, *, enabled: bool) -> dict[str, Any]:
        """Register the production template used by the HTTP push integration."""

        existing = self.get_template("solidworks/compression-spring", "v1", include_disabled=True)
        if existing:
            if existing["enabled"] != enabled:
                return self.set_template_status("solidworks/compression-spring", "v1", enabled=enabled)
            return existing
        return self.create_template(
            {
                "template_code": "solidworks/compression-spring",
                "version": "v1",
                "drawing_type": "compression_spring",
                "label": "SolidWorks 圆柱螺旋压缩弹簧（主动推送）",
                "priority": 2000,
                "enabled": enabled,
                "is_mock": False,
                "required_fields": [
                    "wire_diameter", "mean_diameter", "free_length", "total_coils",
                    "active_coils", "handedness", "end_grinding", "end_coils_closed",
                ],
                "match_rules": {},
                "parameter_mapping": {
                    "wire_diameter": "线径",
                    "mean_diameter": "中径",
                    "free_length": "自由高度",
                    "total_coils": "圈数",
                    "solid_height": "压并高度Hb",
                    "load_points.F1": "工作高度H1 / F1",
                    "load_points.F2": "工作高度H2 / F2",
                },
                "worker_capability": "solidworks_compression_v2",
            }
        )

    def disable_mock_templates(self) -> int:
        """Disable previously registered mock templates without creating new ones."""
        self._require_database()
        with self.repository._session() as session:
            try:
                records = session.execute(
                    select(GenerationTemplateRecord)
                    .where(
                        GenerationTemplateRecord.is_mock.is_(True),
                        GenerationTemplateRecord.enabled.is_(True),
                    )
                    .with_for_update()
                ).scalars().all()
                for record in records:
                    record.enabled = False
                    record.updated_at = _utcnow()
                session.commit()
                return len(records)
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to disable mock generation templates: {exc}") from exc

    def list_templates(
        self,
        *,
        include_disabled: bool = False,
        template_code: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        try:
            with self.repository._session() as session:
                query = select(GenerationTemplateRecord)
                if not include_disabled:
                    query = query.where(GenerationTemplateRecord.enabled.is_(True))
                if template_code:
                    query = query.where(GenerationTemplateRecord.template_code == template_code)
                rows = session.execute(
                    query.order_by(
                        GenerationTemplateRecord.priority.desc(),
                        GenerationTemplateRecord.template_code.asc(),
                        GenerationTemplateRecord.created_at.desc(),
                    )
                ).scalars()
                return [self._template(row) for row in rows]
        except SQLAlchemyError as exc:
            raise PersistenceError(f"Unable to list generation templates: {exc}") from exc

    def get_template(self, code: str, version: str, *, include_disabled: bool = False) -> dict[str, Any] | None:
        rows = self.list_templates(include_disabled=include_disabled, template_code=code)
        return next((item for item in rows if item["version"] == version), None)

    def set_template_status(self, code: str, version: str, *, enabled: bool) -> dict[str, Any]:
        self._require_database()
        with self.repository._session() as session:
            try:
                record = session.execute(
                    select(GenerationTemplateRecord)
                    .where(
                        GenerationTemplateRecord.template_code == code,
                        GenerationTemplateRecord.version == version,
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if record is None:
                    raise PersistenceError("Generation template not found.")
                record.enabled = enabled
                record.updated_at = _utcnow()
                session.commit()
                return self._template(record)
            except PersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to update generation template: {exc}") from exc

    def create_job(self, payload: dict[str, Any], *, owner: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        self._require_database()
        with self.repository._session() as session:
            try:
                existing = session.execute(
                    select(GenerationJobRecord).where(
                        GenerationJobRecord.owner_erp_user_id == owner["user_id"],
                        GenerationJobRecord.review_job_id == payload["review_job_id"],
                        GenerationJobRecord.idempotency_key == payload["idempotency_key"],
                    )
                ).scalar_one_or_none()
                if existing:
                    if existing.request_fingerprint != payload["request_fingerprint"]:
                        raise PersistenceError("Idempotency key was reused with a different request.")
                    return self._job(session, existing), False
                record = GenerationJobRecord(
                    **copy.deepcopy(payload),
                    owner_erp_user_id=owner["user_id"],
                    owner_username=owner.get("username"),
                    owner_real_name=owner.get("real_name"),
                    owner_org_id=owner.get("org_id"),
                    owner_org_name=owner.get("org_name"),
                )
                session.add(record)
                session.flush()
                self._event(session, record, "generation_queued", "user", {"review_revision": record.review_revision})
                session.commit()
                return self._job(session, record), True
            except PersistenceError:
                session.rollback()
                raise
            except IntegrityError as exc:
                session.rollback()
                raise PersistenceError("Unable to create generation job because the request conflicts with existing data.") from exc
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to create generation job: {exc}") from exc

    def find_idempotent_job(
        self,
        *,
        review_job_id: str,
        owner_user_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> dict[str, Any] | None:
        """Return an existing equivalent request before allocating a new TaskId."""

        self._require_database()
        try:
            with self.repository._session() as session:
                existing = session.execute(
                    select(GenerationJobRecord).where(
                        GenerationJobRecord.owner_erp_user_id == owner_user_id,
                        GenerationJobRecord.review_job_id == review_job_id,
                        GenerationJobRecord.idempotency_key == idempotency_key,
                    )
                ).scalar_one_or_none()
                if existing is None:
                    return None
                if existing.request_fingerprint != request_fingerprint:
                    raise PersistenceError("Idempotency key was reused with a different request.")
                return self._job(session, existing)
        except PersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise PersistenceError(f"Unable to read idempotent generation job: {exc}") from exc

    def next_generation_id(self) -> str:
        """Return a unique ten-digit task identifier without changing the string PK schema."""

        self._require_database()
        try:
            with self.repository._session() as session:
                dialect = str(getattr(session.bind.dialect, "name", "") or "")
                if dialect == "postgresql":
                    value = session.execute(text("SELECT nextval('solidworks_task_id_seq')")).scalar_one()
                    return str(value)
                for _ in range(20):
                    value = secrets.randbelow(9_000_000_000) + 1_000_000_000
                    existing = session.get(GenerationJobRecord, str(value))
                    if existing is None:
                        return str(value)
        except SQLAlchemyError as exc:
            raise PersistenceError(f"Unable to allocate SolidWorks TaskId: {exc}") from exc
        raise PersistenceError("Unable to allocate a unique ten-digit SolidWorks TaskId.")

    def mark_solidworks_submitted(self, generation_id: str, *, message: str | None = None) -> dict[str, Any] | None:
        """Record that a push task was accepted by SolidWorks without using a worker lease."""

        self._require_database()
        now = _utcnow()
        with self.repository._session() as session:
            try:
                record = session.execute(
                    select(GenerationJobRecord)
                    .where(GenerationJobRecord.generation_id == generation_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if record is None:
                    return None
                if record.status == "queued":
                    record.status = "claimed"
                    record.stage = "submitted_to_solidworks"
                    record.progress = max(record.progress, 1)
                    record.worker_id = "solidworks-push"
                    record.attempt_count += 1
                    record.started_at = record.started_at or now
                    record.updated_at = now
                    self._set_solidworks_message(record, message)
                    self._event(session, record, "solidworks_command_accepted", "system", {"message": message or ""})
                session.commit()
                return self._job(session, record)
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to mark SolidWorks submission: {exc}") from exc

    def fail_solidworks_submission(self, generation_id: str, *, error_message: str) -> dict[str, Any] | None:
        self._require_database()
        now = _utcnow()
        with self.repository._session() as session:
            try:
                record = session.execute(
                    select(GenerationJobRecord)
                    .where(GenerationJobRecord.generation_id == generation_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if record is None or record.status in {"completed", "cancelled"}:
                    return None
                record.status = "failed"
                record.stage = "failed"
                record.error_code = "solidworks_submit_failed"
                record.error_message = error_message[:4000]
                record.completed_at = now
                record.lease_expires_at = None
                record.updated_at = now
                self._event(session, record, "solidworks_command_failed", "system", {"reason": record.error_message})
                session.commit()
                return self._job(session, record)
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to record SolidWorks submission failure: {exc}") from exc

    def get_job(self, generation_id: str, *, owner_user_id: str | None = None) -> dict[str, Any] | None:
        if not self.configured:
            return None
        try:
            with self.repository._session() as session:
                record = session.get(GenerationJobRecord, generation_id)
                if record is None or (owner_user_id and record.owner_erp_user_id != owner_user_id):
                    return None
                return self._job(session, record)
        except SQLAlchemyError as exc:
            raise PersistenceError(f"Unable to read generation job: {exc}") from exc

    def is_solidworks_task_cancelled(self, generation_id: str) -> bool:
        """Return whether a trusted SolidWorks callback should stop this task.

        This lightweight preflight avoids decoding or storing a completed
        callback's PDF after a user has already cancelled the task. The
        authoritative check still happens under a row lock during persistence.
        """

        self._require_database()
        try:
            with self.repository._session() as session:
                record = session.get(GenerationJobRecord, generation_id)
                if record is None:
                    return False
                integration = str((record.execution_options or {}).get("integration") or "")
                return integration == "solidworks_push" and record.status == "cancelled"
        except SQLAlchemyError as exc:
            raise PersistenceError(f"Unable to read SolidWorks callback state: {exc}") from exc

    def list_jobs(self, review_job_id: str, *, owner_user_id: str) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        try:
            with self.repository._session() as session:
                rows = session.execute(
                    select(GenerationJobRecord)
                    .where(
                        GenerationJobRecord.review_job_id == review_job_id,
                        GenerationJobRecord.owner_erp_user_id == owner_user_id,
                    )
                    .order_by(GenerationJobRecord.created_at.desc())
                ).scalars()
                return [self._job(session, row) for row in rows]
        except SQLAlchemyError as exc:
            raise PersistenceError(f"Unable to list generation jobs: {exc}") from exc

    def claim_job(self, worker_id: str, capabilities: list[str], *, lease_seconds: int) -> dict[str, Any] | None:
        self._require_database()
        now = _utcnow()
        with self.repository._session() as session:
            try:
                expired = session.execute(
                    select(GenerationJobRecord)
                    .where(
                        GenerationJobRecord.status.in_(["claimed", "generating_3d", "generating_2d", "uploading"]),
                        GenerationJobRecord.lease_expires_at.is_not(None),
                        GenerationJobRecord.lease_expires_at < now,
                    )
                    .with_for_update(skip_locked=True)
                ).scalars()
                for row in expired:
                    row.status = "queued"
                    row.stage = "queued"
                    row.progress = 0
                    row.worker_id = None
                    row.lease_expires_at = None
                    row.updated_at = now
                    self._event(session, row, "generation_lease_expired", "system", {})

                capability_set = {str(item) for item in capabilities if str(item)}
                record = session.execute(
                    select(GenerationJobRecord)
                    .where(
                        GenerationJobRecord.status == "queued",
                        GenerationJobRecord.worker_capability.in_(capability_set),
                    )
                    .order_by(GenerationJobRecord.created_at.asc())
                    .with_for_update(skip_locked=True)
                    .limit(1)
                ).scalar_one_or_none()
                if record is None:
                    session.commit()
                    return None
                record.status = "claimed"
                record.stage = "claimed"
                record.progress = max(record.progress, 1)
                record.worker_id = worker_id[:128]
                record.attempt_count += 1
                record.started_at = record.started_at or now
                record.lease_expires_at = now + timedelta(seconds=max(lease_seconds, 30))
                record.updated_at = now
                self._event(session, record, "generation_claimed", "worker", {"worker_id": worker_id})
                session.commit()
                return self._job(session, record, include_package=True)
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to claim generation job: {exc}") from exc

    def update_worker_job(
        self,
        generation_id: str,
        *,
        worker_id: str,
        status: str | None = None,
        stage: str | None = None,
        progress: int | None = None,
        lease_seconds: int,
    ) -> dict[str, Any] | None:
        self._require_database()
        now = _utcnow()
        with self.repository._session() as session:
            try:
                record = session.execute(
                    select(GenerationJobRecord)
                    .where(GenerationJobRecord.generation_id == generation_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if not self._worker_owns(record, worker_id, now):
                    return None
                if status is not None:
                    allowed = {
                        "claimed": {"generating_3d"},
                        "generating_3d": {"generating_2d"},
                        "generating_2d": {"uploading"},
                        "uploading": set(),
                    }
                    if status != record.status and status not in allowed.get(record.status, set()):
                        raise PersistenceError(f"Invalid generation state transition: {record.status} -> {status}")
                    record.status = status
                    record.stage = stage or status
                    self._event(session, record, "generation_status_updated", "worker", {"status": status})
                elif stage:
                    record.stage = stage[:64]
                if progress is not None:
                    record.progress = min(max(int(progress), 0), 99)
                record.lease_expires_at = now + timedelta(seconds=max(lease_seconds, 30))
                record.updated_at = now
                session.commit()
                return self._job(session, record)
            except PersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to update generation job: {exc}") from exc

    def add_artifact(
        self,
        payload: dict[str, Any],
        *,
        worker_id: str,
        event_source: str = "worker",
        event_payload: dict[str, Any] | None = None,
        preview_attempt_count: int = 0,
    ) -> dict[str, Any] | None:
        self._require_database()
        now = _utcnow()
        with self.repository._session() as session:
            try:
                job = session.execute(
                    select(GenerationJobRecord)
                    .where(GenerationJobRecord.generation_id == payload["generation_id"])
                    .with_for_update()
                ).scalar_one_or_none()
                if not self._worker_owns(job, worker_id, now) or job.status != "uploading":
                    return None
                artifact = GenerationArtifactRecord(**copy.deepcopy(payload))
                session.add(artifact)
                session.flush()
                self._event(
                    session,
                    job,
                    "generation_artifact_uploaded",
                    event_source,
                    {
                        "artifact_id": artifact.artifact_id,
                        "artifact_type": artifact.artifact_type,
                        **copy.deepcopy(event_payload or {}),
                    },
                )
                if artifact.artifact_type == "png":
                    job.preview_status = "ready"
                    job.preview_attempt_count += max(int(preview_attempt_count), 0)
                    job.preview_error_message = None
                    self._event(
                        session,
                        job,
                        "generation_preview_created",
                        "system",
                        {
                            "artifact_id": artifact.artifact_id,
                            "attempt_count": max(int(preview_attempt_count), 0),
                        },
                    )
                session.commit()
                return self._artifact(artifact)
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to save generation artifact: {exc}") from exc

    def apply_solidworks_status(
        self,
        generation_id: str,
        *,
        status: str,
        progress: int | None,
        message: str | None,
        error_code: str | None = None,
        artifact_payload: dict[str, Any] | None = None,
        preview_payload: dict[str, Any] | None = None,
        preview_attempt_count: int = 0,
        preview_error_message: str | None = None,
    ) -> dict[str, Any] | None:
        """Apply a trusted-network push callback and atomically register its PDF."""

        self._require_database()
        now = _utcnow()
        with self.repository._session() as session:
            try:
                record = session.execute(
                    select(GenerationJobRecord)
                    .where(GenerationJobRecord.generation_id == generation_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if record is None:
                    return None
                if str((record.execution_options or {}).get("integration") or "") != "solidworks_push":
                    raise PersistenceError("Generation job is not a SolidWorks push task.")

                if record.status == "cancelled":
                    raise SolidWorksTaskCancelledError(
                        f"SolidWorks task {generation_id} was cancelled by the user."
                    )

                existing_pdf = session.execute(
                    select(GenerationArtifactRecord)
                    .where(
                        GenerationArtifactRecord.generation_id == generation_id,
                        GenerationArtifactRecord.artifact_type == "pdf",
                    )
                    .order_by(GenerationArtifactRecord.created_at.asc())
                ).scalar_one_or_none()
                if record.status in {"completed", "failed"}:
                    if status == "completed" and record.status == "completed" and artifact_payload is not None:
                        if existing_pdf and existing_pdf.sha256 == artifact_payload["sha256"]:
                            return {"job": self._job(session, record), "artifact": None, "duplicate": True}
                        raise PersistenceError("SolidWorks callback PDF conflicts with the completed task.")
                    same_failed_callback = record.status == "failed" and (
                        (status == "failed" and record.stage == "failed")
                        or (status in SOLIDWORKS_STAGE_ERRORS and record.stage == status)
                    )
                    same_completed_callback = record.status == "completed" and status == "completed"
                    if same_completed_callback or same_failed_callback:
                        return {"job": self._job(session, record), "artifact": None, "duplicate": True}
                    raise PersistenceError("SolidWorks callback cannot move a terminal task to another state.")

                current_rank = {"queued": 0, "claimed": 0, "generating_3d": 1, "generating_2d": 2}.get(record.status, 0)
                incoming_rank = {"generating_3d": 1, "generating_2d": 2}.get(status, 3)
                if status in {"generating_3d", "generating_2d"} and status == record.status and int(progress) <= record.progress:
                    return {"job": self._job(session, record), "artifact": None, "duplicate": True}
                if status in {"generating_3d", "generating_2d"} and incoming_rank < current_rank:
                    return {"job": self._job(session, record), "artifact": None, "duplicate": True}

                artifact: GenerationArtifactRecord | None = None
                preview_artifact: GenerationArtifactRecord | None = None
                if status == "completed":
                    if artifact_payload is None:
                        raise PersistenceError("A completed SolidWorks callback requires a PDF artifact.")
                    if existing_pdf is not None:
                        if existing_pdf.sha256 == artifact_payload["sha256"]:
                            return {"job": self._job(session, record), "artifact": None, "duplicate": True}
                        raise PersistenceError("SolidWorks callback PDF conflicts with an existing task artifact.")
                    artifact = GenerationArtifactRecord(**copy.deepcopy(artifact_payload))
                    session.add(artifact)
                    session.flush()
                    self._event(
                        session,
                        record,
                        "solidworks_pdf_received",
                        "solidworks",
                        {"artifact_id": artifact.artifact_id, "sha256": artifact.sha256},
                    )
                    if preview_payload is not None:
                        preview_artifact = GenerationArtifactRecord(**copy.deepcopy(preview_payload))
                        session.add(preview_artifact)
                        session.flush()
                        record.preview_status = "ready"
                        record.preview_error_message = None
                        self._event(
                            session,
                            record,
                            "generation_preview_created",
                            "system",
                            {
                                "artifact_id": preview_artifact.artifact_id,
                                "source_artifact_id": artifact.artifact_id,
                                "attempt_count": max(int(preview_attempt_count), 0),
                            },
                        )
                    else:
                        record.preview_status = "failed"
                        record.preview_error_message = str(
                            preview_error_message or "PDF 对比预览生成失败。"
                        )[:2000]
                        self._event(
                            session,
                            record,
                            "generation_preview_failed",
                            "system",
                            {
                                "source_artifact_id": artifact.artifact_id,
                                "attempt_count": max(int(preview_attempt_count), 0),
                                "reason": record.preview_error_message,
                            },
                        )
                    record.preview_attempt_count = max(int(preview_attempt_count), 0)
                    record.status = "completed"
                    record.stage = "completed"
                    record.progress = 100
                    record.completed_at = now
                    record.lease_expires_at = None
                    record.error_code = None
                    record.error_message = None
                    self._event(session, record, "generation_completed", "solidworks", {})
                elif status == "failed":
                    record.status = "failed"
                    record.stage = "failed"
                    record.progress = min(max(int(progress if progress is not None else record.progress), 0), 100)
                    record.error_code = str(error_code or "solidworks_generation_failed")[:96]
                    record.error_message = str(message or "SolidWorks 生图失败。")[:4000]
                    record.completed_at = now
                    record.lease_expires_at = None
                    self._event(session, record, "generation_failed", "solidworks", {"error_code": record.error_code})
                elif status in SOLIDWORKS_STAGE_ERRORS:
                    stage_error_code, default_message = SOLIDWORKS_STAGE_ERRORS[status]
                    record.status = "failed"
                    record.stage = status
                    record.error_code = stage_error_code
                    record.error_message = str(message or default_message)[:4000]
                    record.completed_at = now
                    record.lease_expires_at = None
                    self._event(
                        session,
                        record,
                        "generation_failed",
                        "solidworks",
                        {"error_code": record.error_code, "stage": status},
                    )
                else:
                    record.status = status
                    record.stage = status
                    record.progress = min(max(int(progress if progress is not None else 0), 0), 99)
                    self._event(session, record, "generation_status_updated", "solidworks", {"status": status})

                self._set_solidworks_message(record, message)
                record.worker_id = "solidworks-push"
                record.updated_at = now
                session.commit()
                return {
                    "job": self._job(session, record),
                    "artifact": self._artifact(artifact) if artifact is not None else None,
                    "preview_artifact": self._artifact(preview_artifact) if preview_artifact is not None else None,
                    "duplicate": False,
                }
            except PersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to apply SolidWorks callback: {exc}") from exc

    def add_system_artifact(
        self,
        payload: dict[str, Any],
        *,
        event_type: str,
        event_payload: dict[str, Any] | None = None,
        preview_attempt_count: int = 0,
    ) -> dict[str, Any] | None:
        """Save a server-derived artifact such as a PNG rendered from a callback PDF."""

        self._require_database()
        with self.repository._session() as session:
            try:
                job = session.execute(
                    select(GenerationJobRecord)
                    .where(GenerationJobRecord.generation_id == payload["generation_id"])
                    .with_for_update()
                ).scalar_one_or_none()
                if job is None:
                    return None
                existing = session.get(GenerationArtifactRecord, payload["artifact_id"])
                if existing is not None:
                    return self._artifact(existing)
                artifact = GenerationArtifactRecord(**copy.deepcopy(payload))
                session.add(artifact)
                session.flush()
                self._event(
                    session,
                    job,
                    event_type,
                    "system",
                    {"artifact_id": artifact.artifact_id, "artifact_type": artifact.artifact_type, **copy.deepcopy(event_payload or {})},
                )
                if artifact.artifact_type == "png":
                    job.preview_status = "ready"
                    job.preview_attempt_count += max(int(preview_attempt_count), 0)
                    job.preview_error_message = None
                session.commit()
                return self._artifact(artifact)
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to save system generation artifact: {exc}") from exc

    def record_preview_failure(
        self,
        generation_id: str,
        *,
        attempt_count: int,
        error_message: str,
        source_artifact_id: str,
    ) -> bool:
        self._require_database()
        with self.repository._session() as session:
            try:
                job = session.execute(
                    select(GenerationJobRecord)
                    .where(GenerationJobRecord.generation_id == generation_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if job is None:
                    return False
                existing_preview = session.execute(
                    select(GenerationArtifactRecord.artifact_id)
                    .where(
                        GenerationArtifactRecord.generation_id == generation_id,
                        GenerationArtifactRecord.artifact_type == "png",
                    )
                    .limit(1)
                ).scalar_one_or_none()
                if existing_preview is not None:
                    job.preview_status = "ready"
                    job.preview_error_message = None
                    session.commit()
                    return False
                attempts = max(int(attempt_count), 0)
                job.preview_status = "failed"
                job.preview_attempt_count += attempts
                job.preview_error_message = str(error_message or "PDF 对比预览生成失败。")[:2000]
                self._event(
                    session,
                    job,
                    "generation_preview_failed",
                    "system",
                    {
                        "source_artifact_id": source_artifact_id,
                        "attempt_count": attempts,
                        "reason": job.preview_error_message,
                    },
                )
                session.commit()
                return True
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to save generation preview failure: {exc}") from exc

    def retry_preview(
        self,
        generation_id: str,
        *,
        owner_user_id: str,
        preview_payload: dict[str, Any] | None,
        attempt_count: int,
        error_message: str | None,
    ) -> dict[str, Any] | None:
        """Apply one user-requested preview regeneration without changing job completion."""

        self._require_database()
        with self.repository._session() as session:
            try:
                job = session.execute(
                    select(GenerationJobRecord)
                    .where(GenerationJobRecord.generation_id == generation_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if job is None or job.owner_erp_user_id != owner_user_id:
                    return None
                artifacts = session.execute(
                    select(GenerationArtifactRecord)
                    .where(GenerationArtifactRecord.generation_id == generation_id)
                    .order_by(GenerationArtifactRecord.created_at.asc())
                ).scalars().all()
                if any(item.artifact_type == "png" for item in artifacts):
                    return self._job(session, job)
                if job.status != "completed" or not any(item.artifact_type == "pdf" for item in artifacts):
                    raise PersistenceError("Only a completed generation with a PDF can retry its preview.")

                attempts = max(int(attempt_count), 0)
                job.preview_attempt_count += attempts
                self._event(
                    session,
                    job,
                    "generation_preview_retried",
                    "user",
                    {"attempt_count": attempts},
                )
                if preview_payload is not None:
                    artifact = GenerationArtifactRecord(**copy.deepcopy(preview_payload))
                    session.add(artifact)
                    session.flush()
                    job.preview_status = "ready"
                    job.preview_error_message = None
                    self._event(
                        session,
                        job,
                        "generation_preview_created",
                        "system",
                        {"artifact_id": artifact.artifact_id, "attempt_count": attempts, "retry": True},
                    )
                else:
                    job.preview_status = "failed"
                    job.preview_error_message = str(error_message or "PDF 对比预览生成失败。")[:2000]
                    self._event(
                        session,
                        job,
                        "generation_preview_failed",
                        "user",
                        {"attempt_count": attempts, "reason": job.preview_error_message, "retry": True},
                    )
                job.updated_at = _utcnow()
                session.commit()
                return self._job(session, job)
            except PersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to retry generation preview: {exc}") from exc

    def record_event(
        self,
        generation_id: str,
        event_type: str,
        *,
        source: str,
        payload: dict[str, Any],
    ) -> bool:
        self._require_database()
        with self.repository._session() as session:
            try:
                job = session.execute(
                    select(GenerationJobRecord)
                    .where(GenerationJobRecord.generation_id == generation_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if job is None:
                    return False
                self._event(session, job, event_type, source, payload)
                session.commit()
                return True
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to save generation event: {exc}") from exc

    def complete_job(self, generation_id: str, *, worker_id: str) -> dict[str, Any] | None:
        self._require_database()
        now = _utcnow()
        with self.repository._session() as session:
            try:
                record = session.execute(select(GenerationJobRecord).where(GenerationJobRecord.generation_id == generation_id).with_for_update()).scalar_one_or_none()
                if not self._worker_owns(record, worker_id, now) or record.status != "uploading":
                    return None
                types = set(session.execute(select(GenerationArtifactRecord.artifact_type).where(GenerationArtifactRecord.generation_id == generation_id)).scalars())
                if not types.intersection({"pdf", "png"}):
                    raise PersistenceError("A PDF or PNG preview is required before completion.")
                if "png" in types:
                    record.preview_status = "ready"
                    record.preview_error_message = None
                elif record.preview_status == "pending":
                    record.preview_status = "failed"
                    record.preview_error_message = "PDF 已生成，但对比预览尚未成功生成。"
                record.status = "completed"
                record.stage = "completed"
                record.progress = 100
                record.completed_at = now
                record.lease_expires_at = None
                record.updated_at = now
                self._event(session, record, "generation_completed", "worker", {})
                session.commit()
                return self._job(session, record)
            except PersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to complete generation job: {exc}") from exc

    def fail_job(self, generation_id: str, *, worker_id: str, error_code: str, error_message: str) -> dict[str, Any] | None:
        self._require_database()
        now = _utcnow()
        with self.repository._session() as session:
            try:
                record = session.execute(select(GenerationJobRecord).where(GenerationJobRecord.generation_id == generation_id).with_for_update()).scalar_one_or_none()
                if record is None or record.worker_id != worker_id or record.status in {"completed", "cancelled"}:
                    return None
                record.status = "failed"
                record.stage = "failed"
                record.error_code = error_code[:96]
                record.error_message = error_message[:4000]
                record.completed_at = now
                record.lease_expires_at = None
                record.updated_at = now
                self._event(session, record, "generation_failed", "worker", {"error_code": record.error_code})
                session.commit()
                return self._job(session, record)
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to fail generation job: {exc}") from exc

    def cancel_job(self, generation_id: str, *, owner_user_id: str) -> dict[str, Any] | None:
        return self._set_user_status(generation_id, owner_user_id=owner_user_id, action="cancel")

    def retry_job(self, generation_id: str, *, owner_user_id: str) -> dict[str, Any] | None:
        return self._set_user_status(generation_id, owner_user_id=owner_user_id, action="retry")

    def approve_job(self, generation_id: str, *, owner: dict[str, Any], current_revision: int) -> dict[str, Any] | None:
        self._require_database()
        now = _utcnow()
        with self.repository._session() as session:
            try:
                record = session.execute(select(GenerationJobRecord).where(GenerationJobRecord.generation_id == generation_id).with_for_update()).scalar_one_or_none()
                if record is None or record.owner_erp_user_id != owner["user_id"]:
                    return None
                if record.status != "completed" or record.review_revision != current_revision:
                    raise PersistenceError("Only a completed generation for the current review revision can be approved.")
                siblings = session.execute(select(GenerationJobRecord).where(GenerationJobRecord.review_job_id == record.review_job_id, GenerationJobRecord.is_final.is_(True)).with_for_update()).scalars()
                for sibling in siblings:
                    sibling.is_final = False
                    sibling.approved_by = None
                    sibling.approved_at = None
                session.flush()
                record.is_final = True
                record.approved_by = copy.deepcopy(owner)
                record.approved_at = now
                record.updated_at = now
                self._event(session, record, "generation_approved", "user", {"review_revision": current_revision})
                session.commit()
                return self._job(session, record)
            except PersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to approve generation job: {exc}") from exc

    def list_artifacts(self, generation_id: str, *, owner_user_id: str | None = None) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        try:
            with self.repository._session() as session:
                job = session.get(GenerationJobRecord, generation_id)
                if job is None or (owner_user_id and job.owner_erp_user_id != owner_user_id):
                    return []
                rows = session.execute(select(GenerationArtifactRecord).where(GenerationArtifactRecord.generation_id == generation_id).order_by(GenerationArtifactRecord.created_at.asc())).scalars()
                return [self._artifact(row) for row in rows]
        except SQLAlchemyError as exc:
            raise PersistenceError(f"Unable to list generation artifacts: {exc}") from exc

    def get_artifact(self, generation_id: str, artifact_id: str, *, owner_user_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list_artifacts(generation_id, owner_user_id=owner_user_id) if item["artifact_id"] == artifact_id), None)

    def _set_user_status(self, generation_id: str, *, owner_user_id: str, action: str) -> dict[str, Any] | None:
        self._require_database()
        now = _utcnow()
        discarded_artifact_paths: list[str] = []
        with self.repository._session() as session:
            try:
                record = session.execute(select(GenerationJobRecord).where(GenerationJobRecord.generation_id == generation_id).with_for_update()).scalar_one_or_none()
                if record is None or record.owner_erp_user_id != owner_user_id:
                    return None
                if action == "cancel":
                    if record.status in {"completed", "failed", "cancelled"}:
                        raise PersistenceError("Completed, failed, or cancelled generation jobs cannot be cancelled.")
                    record.status = "cancelled"
                    record.stage = "cancelled"
                    record.lease_expires_at = None
                    record.completed_at = now
                    event = "generation_cancelled"
                else:
                    if record.status != "failed":
                        raise PersistenceError("Only failed generation jobs can be retried.")
                    artifacts = session.execute(
                        select(GenerationArtifactRecord).where(
                            GenerationArtifactRecord.generation_id == generation_id
                        )
                    ).scalars()
                    for artifact in artifacts:
                        discarded_artifact_paths.append(artifact.relative_path)
                        session.delete(artifact)
                    record.status = "queued"
                    record.stage = "queued"
                    record.progress = 0
                    record.error_code = None
                    record.error_message = None
                    record.worker_id = None
                    record.lease_expires_at = None
                    record.completed_at = None
                    record.preview_status = "pending"
                    record.preview_attempt_count = 0
                    record.preview_error_message = None
                    event = "generation_retried"
                record.updated_at = now
                self._event(session, record, event, "user", {})
                session.commit()
                result = self._job(session, record)
                if discarded_artifact_paths:
                    result["_discarded_artifact_paths"] = discarded_artifact_paths
                return result
            except PersistenceError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:
                session.rollback()
                raise PersistenceError(f"Unable to update generation job: {exc}") from exc

    @staticmethod
    def _worker_owns(record: GenerationJobRecord | None, worker_id: str, now: datetime) -> bool:
        lease_expires_at = record.lease_expires_at if record is not None else None
        if lease_expires_at is not None and lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        return bool(
            record
            and record.worker_id == worker_id
            and record.status not in {"completed", "failed", "cancelled"}
            and lease_expires_at
            and lease_expires_at >= now
        )

    @staticmethod
    def _set_solidworks_message(record: GenerationJobRecord, message: str | None) -> None:
        if message is None:
            return
        options = copy.deepcopy(record.execution_options or {})
        options["solidworks_status_message"] = str(message)[:1000]
        record.execution_options = options

    @staticmethod
    def _event(session: Any, job: GenerationJobRecord, event_type: str, source: str, payload: dict[str, Any]) -> None:
        sequence = session.execute(select(GenerationEventRecord.sequence).where(GenerationEventRecord.generation_id == job.generation_id).order_by(GenerationEventRecord.sequence.desc()).limit(1)).scalar_one_or_none()
        session.add(GenerationEventRecord(generation_id=job.generation_id, sequence=(sequence or 0) + 1, event_type=event_type, source=source, payload=copy.deepcopy(payload)))

    def _job(self, session: Any, record: GenerationJobRecord, *, include_package: bool = False) -> dict[str, Any]:
        artifacts = session.execute(select(GenerationArtifactRecord).where(GenerationArtifactRecord.generation_id == record.generation_id).order_by(GenerationArtifactRecord.created_at.asc())).scalars()
        result = {
            "generation_id": record.generation_id,
            "review_id": record.review_job_id,
            "review_revision": record.review_revision,
            "parent_generation_id": record.parent_generation_id,
            "template_code": record.template_code,
            "template_version": record.template_version,
            "worker_capability": record.worker_capability,
            "parameter_schema_version": record.parameter_schema_version,
            "parameter_hash": record.parameter_hash,
            "readiness": copy.deepcopy(record.readiness),
            "requested_artifact_types": copy.deepcopy(record.requested_artifact_types),
            "execution_options": copy.deepcopy(record.execution_options),
            "preview_status": record.preview_status,
            "preview_attempt_count": record.preview_attempt_count,
            "preview_error_message": record.preview_error_message,
            "status": record.status,
            "stage": record.stage,
            "progress": record.progress,
            "status_message": str((record.execution_options or {}).get("solidworks_status_message") or "") or None,
            "error_code": record.error_code,
            "error_message": record.error_message,
            "attempt_count": record.attempt_count,
            "worker_id": record.worker_id,
            "lease_expires_at": record.lease_expires_at.isoformat() if record.lease_expires_at else None,
            "is_final": record.is_final,
            "approved_by": copy.deepcopy(record.approved_by),
            "approved_at": record.approved_at.isoformat() if record.approved_at else None,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
            "artifacts": [self._artifact(item) for item in artifacts],
        }
        if include_package:
            result["parameter_package"] = copy.deepcopy(record.parameter_package)
        return result

    @staticmethod
    def _artifact(record: GenerationArtifactRecord) -> dict[str, Any]:
        return {
            "artifact_id": record.artifact_id,
            "generation_id": record.generation_id,
            "artifact_type": record.artifact_type,
            "filename": record.filename,
            "relative_path": record.relative_path,
            "mime_type": record.mime_type,
            "size_bytes": record.size_bytes,
            "sha256": record.sha256,
            "is_mock": record.is_mock,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    @staticmethod
    def _template(record: GenerationTemplateRecord) -> dict[str, Any]:
        return {
            "template_code": record.template_code,
            "version": record.version,
            "drawing_type": record.drawing_type,
            "label": record.label,
            "priority": record.priority,
            "enabled": record.enabled,
            "is_mock": record.is_mock,
            "required_fields": copy.deepcopy(record.required_fields),
            "match_rules": copy.deepcopy(record.match_rules),
            "parameter_mapping": copy.deepcopy(record.parameter_mapping),
            "worker_capability": record.worker_capability,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    def _require_database(self) -> None:
        if not self.configured:
            raise PersistenceError("PostgreSQL is required for generation jobs.")
