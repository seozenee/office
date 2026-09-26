"""ORM models for the whole office. See docs/ARCHITECTURE.md §4."""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, enum.Enum):
    BACKLOG = "BACKLOG"
    PLANNED = "PLANNED"
    RESEARCHING = "RESEARCHING"
    ANALYZING = "ANALYZING"
    WRITING = "WRITING"
    REVIEWING = "REVIEWING"
    WAITING_USER = "WAITING_USER"
    DONE = "DONE"
    FAILED = "FAILED"


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ClaimKind(str, enum.Enum):
    FACT = "FACT"
    ANALYSIS = "ANALYSIS"
    ASSUMPTION = "ASSUMPTION"
    ESTIMATE = "ESTIMATE"
    OPINION = "OPINION"
    UNKNOWN = "UNKNOWN"


class VerificationStatus(str, enum.Enum):
    VERIFIED = "verified"
    PARTIAL = "partially_verified"
    UNVERIFIED = "unverified"
    CONTRADICTED = "contradicted"
    OUTDATED = "outdated"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    context: Mapped[str] = mapped_column(Text, default="")  # project-level context the agents read
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tasks: Mapped[list[Task]] = relationship(back_populates="project")


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    request: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.BACKLOG.value)
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1 highest .. 5 lowest
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner: Mapped[str] = mapped_column(String(100), default="CEO")
    dependencies: Mapped[list[int]] = mapped_column(JSON, default=list)
    agents: Mapped[list[str]] = mapped_column(JSON, default=list)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_step: Mapped[str] = mapped_column(String(200), default="")
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project: Mapped[Project | None] = relationship(back_populates="tasks")
    steps: Mapped[list[TaskStep]] = relationship(back_populates="task", order_by="TaskStep.id")


class TaskStep(Base):
    __tablename__ = "task_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    name: Mapped[str] = mapped_column(String(200))
    agent: Mapped[str] = mapped_column(String(100))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|done|failed|skipped
    detail: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    task: Mapped[Task] = relationship(back_populates="steps")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    worker: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KBDocument(Base):
    __tablename__ = "kb_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mime: Mapped[str] = mapped_column(String(100), default="text/plain")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(300), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(300), nullable=True)
    date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    citations: Mapped[list[str]] = mapped_column(JSON, default=list)  # references found in the document
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    is_ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    injection_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    chunks: Mapped[list[KBChunk]] = relationship(back_populates="document", cascade="all, delete-orphan")
    tables: Mapped[list[KBTable]] = relationship(back_populates="document", cascade="all, delete-orphan")


class KBChunk(Base):
    __tablename__ = "kb_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("kb_documents.id"))
    ord: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(500), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    document: Mapped[KBDocument] = relationship(back_populates="chunks")


class KBTable(Base):
    __tablename__ = "kb_tables"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("kb_documents.id"))
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caption: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rows: Mapped[list[list[str]]] = mapped_column(JSON, default=list)
    document: Mapped[KBDocument] = relationship(back_populates="tables")


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    kb_document_id: Mapped[int | None] = mapped_column(ForeignKey("kb_documents.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), default="other")
    tier: Mapped[int] = mapped_column(Integer, default=7)  # 1 = government … 7 = other
    publication_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    access_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    snippet: Mapped[str] = mapped_column(Text, default="")
    accessed: Mapped[bool] = mapped_column(Boolean, default=False)  # original content actually read
    access_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    query: Mapped[str | None] = mapped_column(Text, nullable=True)


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default=ClaimKind.FACT.value)
    topic: Mapped[str | None] = mapped_column(String(300), nullable=True)
    supporting_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    verification_status: Mapped[str] = mapped_column(String(30), default=VerificationStatus.UNVERIFIED.value)
    verification_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    corroborating_source_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[Source | None] = relationship()


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))  # document|presentation|spreadsheet|dataset|research|code|image|report
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(30), default="draft")  # draft|in_review|approved|final
    author_agent: Mapped[str] = mapped_column(String(100))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    source_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    versions: Mapped[list[ArtifactVersion]] = relationship(back_populates="artifact", order_by="ArtifactVersion.version")


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"))
    version: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(20))  # v1, v2, final
    file_path: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(10))
    change_note: Mapped[str] = mapped_column(Text, default="")
    checksum: Mapped[str] = mapped_column(String(64), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    artifact: Mapped[Artifact] = relationship(back_populates="versions")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    risk: Mapped[str] = mapped_column(String(10), default=RiskLevel.LOW.value)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Approval(Base):
    """결재. A request travels up an approval line (결재선) of stamps."""

    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    action: Mapped[str] = mapped_column(String(100))  # e.g. report_submission, send_email, final_delivery
    risk_level: Mapped[str] = mapped_column(String(10), default=RiskLevel.LOW.value)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    line: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # [{approver, employee_id|null(user), status, note, at}]
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected
    requires_user: Mapped[bool] = mapped_column(Boolean, default=False)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Memory(Base):
    __tablename__ = "memories"
    id: Mapped[int] = mapped_column(primary_key=True)
    layer: Mapped[str] = mapped_column(String(30))  # preference|project|company|person|document|decision|task|fact|temporary
    key: Mapped[str] = mapped_column(String(300))
    value: Mapped[str] = mapped_column(Text)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    origin: Mapped[str] = mapped_column(String(20), default="explicit")  # explicit|auto
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Template(Base):
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))  # report|business_plan|pitch_deck|research_deck|minutes|weekly
    description: Mapped[str] = mapped_column(Text, default="")
    structure: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {"sections": [...]} or {"slides": [...]}
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)  # optional .docx/.pptx base file
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    department: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(30))  # 직급
    role: Mapped[str] = mapped_column(String(100))
    agent_type: Mapped[str] = mapped_column(String(40))
    is_lead: Mapped[bool] = mapped_column(Boolean, default=False)
    persona: Mapped[str] = mapped_column(Text, default="")
    appearance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    desk: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {"x": .., "y": ..}
    status: Mapped[str] = mapped_column(String(20), default="idle")  # idle|working|meeting|away
    status_text: Mapped[str] = mapped_column(String(300), default="")
    current_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Channel(Base):
    __tablename__ = "channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # all|department|meeting|dm
    name: Mapped[str] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(30), nullable=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    sender_type: Mapped[str] = mapped_column(String(20))  # user|employee|system
    sender_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recipient_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="chat")  # chat|report|approval_request|approval_stamp|meeting|system|progress
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Meeting(Base):
    __tablename__ = "meetings"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    agenda: Mapped[list[str]] = mapped_column(JSON, default=list)
    participant_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled|in_progress|ended
    decisions: Mapped[list[str]] = mapped_column(JSON, default=list)
    minutes: Mapped[str] = mapped_column(Text, default="")
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    action_items: Mapped[list[ActionItem]] = relationship(back_populates="meeting")


class ActionItem(Base):
    __tablename__ = "action_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    decision: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(100))
    deadline: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    meeting: Mapped[Meeting | None] = relationship(back_populates="action_items")


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
