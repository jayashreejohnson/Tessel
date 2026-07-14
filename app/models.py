import enum
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base


class EventCategory(str, enum.Enum):
    # An in-progress, authorized reason income may lawfully pause — the
    # generic concept the rule engine reasons about. EAD_PENDING is the one
    # populated instance today; a future scenario (parental leave, a
    # severance/notice period) is a new EventType in this same category, not
    # a new category or a rule-engine change — see interruption_gap_rule.py.
    AUTHORIZED_INTERRUPTION = "AUTHORIZED_INTERRUPTION"
    # Background case-lifecycle milestones that aren't themselves an active
    # interruption (the baseline status before one starts, or the terminal
    # outcome after one ends). Narrative context, not something any rule
    # currently queries.
    CASE_STATUS = "CASE_STATUS"
    INCOME = "INCOME"
    TRANSFER = "TRANSFER"


class EventType(str, enum.Enum):
    # CASE_STATUS instances (see EventCategory.CASE_STATUS above)
    F1_ACTIVE = "F1_ACTIVE"
    EAD_APPROVED = "EAD_APPROVED"
    EAD_DENIED = "EAD_DENIED"
    # AUTHORIZED_INTERRUPTION instance — F-1/OPT is the first scenario this
    # is populated for, not an assumption baked into the category itself
    EAD_PENDING = "EAD_PENDING"
    INCOME_RECEIVED = "INCOME_RECEIVED"
    INCOME_GAP = "INCOME_GAP"
    INTL_TRANSFER_RECEIVED = "INTL_TRANSFER_RECEIVED"


class EventSource(str, enum.Enum):
    USER_REPORTED = "USER_REPORTED"
    DOCUMENT_EXTRACTED = "DOCUMENT_EXTRACTED"
    BANK_FEED = "BANK_FEED"
    SYSTEM_DERIVED = "SYSTEM_DERIVED"


class DocType(str, enum.Enum):
    EAD_NOTICE = "EAD_NOTICE"
    OTHER = "OTHER"


class MatchType(str, enum.Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    UNCLEAR = "UNCLEAR"


class AuditEventType(str, enum.Enum):
    RULE_CHECK = "RULE_CHECK"
    RETRIEVAL_MATCH = "RETRIEVAL_MATCH"
    LLM_CALL = "LLM_CALL"


class Applicant(Base):
    __tablename__ = "applicants"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    timeline_events: Mapped[list["TimelineEvent"]] = relationship(
        back_populates="applicant", cascade="all, delete-orphan"
    )
    evidence_documents: Mapped[list["EvidenceDocument"]] = relationship(
        back_populates="applicant", cascade="all, delete-orphan"
    )
    rule_runs: Mapped[list["RuleRun"]] = relationship(
        back_populates="applicant", cascade="all, delete-orphan"
    )


class TimelineEvent(Base):
    """
    A single dated fact or span on an applicant's timeline. Deliberately one
    wide table rather than per-category tables (interruption/income/transfer)
    — the rule checks reason across categories (e.g. does an INCOME_GAP span
    overlap an AUTHORIZED_INTERRUPTION span), so they need to be
    queryable/sortable together on shared start/end dates rather than joined
    across separate tables.
    """

    __tablename__ = "timeline_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id"), index=True)

    category: Mapped[EventCategory] = mapped_column(Enum(EventCategory))
    event_type: Mapped[EventType] = mapped_column(Enum(EventType))

    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    counterparty: Mapped[str | None] = mapped_column(String, nullable=True)

    source: Mapped[EventSource] = mapped_column(Enum(EventSource))
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    applicant: Mapped["Applicant"] = relationship(back_populates="timeline_events")
    evidence_links: Mapped[list["EventEvidenceLink"]] = relationship(
        back_populates="timeline_event", cascade="all, delete-orphan"
    )


class EvidenceDocument(Base):
    __tablename__ = "evidence_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id"), index=True)

    doc_type: Mapped[DocType] = mapped_column(Enum(DocType))
    file_path: Mapped[str] = mapped_column(String)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[bytes | None] = mapped_column(nullable=True)

    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    applicant: Mapped["Applicant"] = relationship(back_populates="evidence_documents")
    evidence_links: Mapped[list["EventEvidenceLink"]] = relationship(
        back_populates="evidence_document", cascade="all, delete-orphan"
    )


class EventEvidenceLink(Base):
    """
    Join table between timeline_events and evidence_documents. A document can
    support/contradict more than one event (an EAD notice touches both an
    EAD_PENDING status event and, later, the income-gap check that relies on
    it), and match_type/similarity_score are per-pair, not per-document.
    """

    __tablename__ = "event_evidence_links"
    __table_args__ = (
        UniqueConstraint("timeline_event_id", "evidence_document_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    timeline_event_id: Mapped[int] = mapped_column(
        ForeignKey("timeline_events.id"), index=True
    )
    evidence_document_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_documents.id"), index=True
    )

    match_type: Mapped[MatchType] = mapped_column(Enum(MatchType))
    similarity_score: Mapped[float | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    timeline_event: Mapped["TimelineEvent"] = relationship(
        back_populates="evidence_links"
    )
    evidence_document: Mapped["EvidenceDocument"] = relationship(
        back_populates="evidence_links"
    )


class RuleRun(Base):
    """
    One invocation of the rule engine for an applicant — the "batch" that
    groups whatever AuditLogEntry rows it produced, so you can answer "what
    did the system conclude as of the March review" rather than only ever
    seeing an undifferentiated pile of findings.
    """

    __tablename__ = "rule_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id"), index=True)

    as_of_date: Mapped[date] = mapped_column(Date)
    triggered_by: Mapped[str] = mapped_column(String, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    applicant: Mapped["Applicant"] = relationship(back_populates="rule_runs")
    audit_entries: Mapped[list["AuditLogEntry"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AuditLogEntry(Base):
    """
    Append-only ledger, never updated after insert. event_type discriminates
    what produced it — only RULE_CHECK is populated today, but RETRIEVAL_MATCH
    (RAG layer) and LLM_CALL (escalation layer) reuse this same table rather
    than getting their own, since "what was evaluated and why, with a
    timestamp" is the same shape regardless of which layer produced it.
    """

    __tablename__ = "audit_log_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("rule_runs.id"), nullable=True, index=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id"), index=True)

    event_type: Mapped[AuditEventType] = mapped_column(Enum(AuditEventType), index=True)
    actor: Mapped[str] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str] = mapped_column(Text)

    subject_event_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    supporting_evidence_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON)

    source_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("audit_log_entries.id"), nullable=True, index=True
    )
    """The RULE_CHECK entry this entry escalates or otherwise builds on, if any."""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    run: Mapped["RuleRun | None"] = relationship(back_populates="audit_entries")
    applicant: Mapped["Applicant"] = relationship()
    source_entry: Mapped["AuditLogEntry | None"] = relationship(remote_side=[id])
