from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RoleEnum(str, enum.Enum):
    user = "user"
    admin = "admin"


class VisibilityEnum(str, enum.Enum):
    global_ = "global"
    user = "user"


class DocumentStatusEnum(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    ready = "ready"
    error = "error"


def enum_values(enum_class: type[enum.Enum]) -> list[str]:
    return [item.value for item in enum_class]


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    role: Mapped[RoleEnum] = mapped_column(
        Enum(RoleEnum, name="role_enum", values_callable=enum_values),
        default=RoleEnum.user,
    )
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(back_populates="user")
    user_files: Mapped[list["UserFile"]] = relationship(back_populates="user")
    events: Mapped[list["UserEvent"]] = relationship(back_populates="user")


class AllowedUser(Base):
    __tablename__ = "allowed_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username_normalized: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_allowed_users_telegram_id", "telegram_id"),
        Index("ix_allowed_users_username_normalized", "username_normalized"),
        Index("ix_allowed_users_is_active", "is_active"),
    )


class DirectorAssignment(Base):
    __tablename__ = "director_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    director_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    employee_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "director_telegram_id",
            "employee_telegram_id",
            name="uq_director_assignment_pair",
        ),
        Index("ix_director_assignments_active_director", "is_active", "director_telegram_id"),
    )


class DirectorReminderLog(Base):
    __tablename__ = "director_reminder_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    director_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    employee_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    employee_name: Mapped[str] = mapped_column(String(512))
    template_key: Mapped[str] = mapped_column(String(100), default="director_attention_reminder")
    reminder_text: Mapped[str] = mapped_column(Text)
    reminder_hash: Mapped[str] = mapped_column(String(64))
    delivery_mode: Mapped[str] = mapped_column(String(50), default="admin_test")
    status: Mapped[str] = mapped_column(String(50), default="sent")
    sent_recipient_ids: Mapped[list[int]] = mapped_column(JSONB().with_variant(JSON, "sqlite"), default=list)
    failed_recipient_ids: Mapped[list[int]] = mapped_column(JSONB().with_variant(JSON, "sqlite"), default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_director_reminder_logs_director_created", "director_telegram_id", "created_at"),
        Index("ix_director_reminder_logs_employee_created", "director_telegram_id", "employee_name", "created_at"),
        Index(
            "ix_director_reminder_logs_hash_created",
            "director_telegram_id",
            "employee_name",
            "reminder_hash",
            "created_at",
        ),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(500))
    stored_path: Mapped[str] = mapped_column(String(1000))
    file_type: Mapped[str] = mapped_column(String(20))
    visibility: Mapped[VisibilityEnum] = mapped_column(
        Enum(VisibilityEnum, name="visibility_enum", values_callable=enum_values)
    )
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    module_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    module_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lesson_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lesson_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    material_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSONB().with_variant(JSON, "sqlite"), default=list)
    status: Mapped[DocumentStatusEnum] = mapped_column(
        Enum(DocumentStatusEnum, name="document_status_enum", values_callable=enum_values),
        default=DocumentStatusEnum.uploaded,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_documents_visibility_owner", "visibility", "owner_user_id"),
        Index("ix_documents_module_number", "module_number"),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536))
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB().with_variant(JSON, "sqlite"),
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_chunk_index"),
        Index("ix_chunks_document_chunk_index", "document_id", "chunk_index"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(100), default="general")
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB().with_variant(JSON, "sqlite"), default=list)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_messages_user_created_at", "user_id", "created_at"),)


class MessageFeedback(Base):
    __tablename__ = "message_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    value: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_message_feedback_message_user"),)


class BotFeedbackResponse(Base):
    __tablename__ = "bot_feedback_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source: Mapped[str] = mapped_column(String(100), default="deep_link")
    status: Mapped[str] = mapped_column(String(50), default="in_progress", index=True)
    usefulness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    useful_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    improvement_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    missing_feature_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_bot_feedback_user_created", "user_id", "created_at"),
        Index("ix_bot_feedback_status_created", "status", "created_at"),
    )


class UserEvent(Base):
    __tablename__ = "user_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    event_name: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"),
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_user_events_type_created", "event_type", "created_at"),
        Index("ix_user_events_name_created", "event_name", "created_at"),
        Index("ix_user_events_telegram_created", "telegram_id", "created_at"),
    )


class UserNotificationSetting(Base):
    __tablename__ = "user_notification_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    notification_time: Mapped[str] = mapped_column(String(5))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    notification_key: Mapped[str] = mapped_column(String(100))
    delivery_date: Mapped[date] = mapped_column(Date)
    scheduled_time: Mapped[str] = mapped_column(String(5))
    status: Mapped[str] = mapped_column(String(20), default="sent")
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "notification_key",
            "delivery_date",
            "scheduled_time",
            name="uq_notification_delivery_user_key_date_time",
        ),
    )


class FeedbackCampaign(Base):
    __tablename__ = "feedback_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("program_lessons.id", ondelete="CASCADE"), index=True)
    lesson_key: Mapped[str] = mapped_column(String(100), index=True)
    lesson_title: Mapped[str] = mapped_column(String(500))
    lesson_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    experts: Mapped[str | None] = mapped_column(String(500), nullable=True)
    initial_text_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    reminder_text_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    usefulness_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    experts_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    valuable_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    improvement_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", server_default="draft", index=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    launch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    responses: Mapped[list["FeedbackResponse"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_feedback_campaigns_lesson_status", "lesson_key", "status"),
    )


class FeedbackResponse(Base):
    __tablename__ = "feedback_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("feedback_campaigns.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending", index=True)
    current_step: Mapped[str] = mapped_column(
        String(30),
        default="invitation",
        server_default="invitation",
    )
    usefulness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experts_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valuable_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    valuable_input_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    valuable_voice_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    valuable_transcription_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    improvement_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    improvement_input_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    improvement_voice_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    improvement_transcription_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    initial_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    campaign: Mapped["FeedbackCampaign"] = relationship(back_populates="responses")
    user: Mapped["User"] = relationship()
    deliveries: Mapped[list["FeedbackDelivery"]] = relationship(
        back_populates="response",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("campaign_id", "user_id", name="uq_feedback_response_campaign_user"),
        Index("ix_feedback_responses_due", "status", "next_reminder_at"),
    )


class FeedbackDelivery(Base):
    __tablename__ = "feedback_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("feedback_campaigns.id", ondelete="CASCADE"),
        index=True,
    )
    response_id: Mapped[int] = mapped_column(
        ForeignKey("feedback_responses.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    delivery_type: Mapped[str] = mapped_column(String(30))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    response: Mapped["FeedbackResponse"] = relationship(back_populates="deliveries")

    __table_args__ = (
        UniqueConstraint("response_id", "delivery_type", name="uq_feedback_delivery_response_type"),
        Index("ix_feedback_deliveries_status_scheduled", "status", "scheduled_at"),
    )


class BotText(Base):
    __tablename__ = "bot_texts"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProgramLesson(Base):
    __tablename__ = "program_lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season_key: Mapped[str] = mapped_column(String(100), index=True)
    season_title: Mapped[str] = mapped_column(String(255))
    block_key: Mapped[str] = mapped_column(String(100), index=True)
    block_title: Mapped[str] = mapped_column(String(255))
    block_order: Mapped[int] = mapped_column(Integer)
    lesson_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    lesson_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lesson_title: Mapped[str] = mapped_column(String(500))
    date_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    speaker: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    material_format: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hr_moderator_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_program_lessons_season_block", "season_key", "block_order"),
        Index("ix_program_lessons_dates", "date_start", "date_end"),
        Index("ix_program_lessons_active_sort", "is_active", "sort_order"),
    )


class Homework(Base):
    __tablename__ = "homeworks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    moodle_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    module_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    module_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lesson_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lesson_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", server_default="active")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_homeworks_lesson_key", "lesson_key"),
        Index("ix_homeworks_lesson_date", "lesson_date"),
        Index("ix_homeworks_deadline_date", "deadline_date"),
        Index("ix_homeworks_status", "status"),
        Index("ix_homeworks_document_id", "document_id"),
    )


class ProgramMedia(Base):
    __tablename__ = "program_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(String(50), index=True)
    telegram_file_id: Mapped[str] = mapped_column(String(512))
    telegram_file_unique_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    telegram_kind: Mapped[str] = mapped_column(String(50))
    stored_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    module_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    module_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lesson_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lesson_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSONB().with_variant(JSON, "sqlite"), default=list)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_program_media_type_created_at", "media_type", "created_at"),
        Index("ix_program_media_module_number", "module_number"),
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserFile(Base):
    __tablename__ = "user_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_file_id: Mapped[str] = mapped_column(String(512), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="user_files")


class ErrorLog(Base):
    __tablename__ = "errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    context: Mapped[str] = mapped_column(String(255))
    error_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
