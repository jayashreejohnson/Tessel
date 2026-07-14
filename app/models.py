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
    IMMIGRATION_STATUS = "IMMIGRATION_STATUS"
    INCOME = "INCOME"
    TRANSFER = "TRANSFER"


class EventType(str, enum.Enum):
    F1_ACTIVE = "F1_ACTIVE"
    EAD_PENDING = "EAD_PENDING"
    EAD_APPROVED = "EAD_APPROVED"
    EAD_DENIED = "EAD_DENIED"
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


class TimelineEvent(Base):
    """
    A single dated fact or span on an applicant's timeline. Deliberately one
    wide table rather than per-category tables (visa/income/transfer) — the
    MVP's rule checks reason across categories (e.g. does an INCOME_GAP span
    overlap an EAD_PENDING span), so they need to be queryable/sortable together
    on shared start/end dates rather than joined across separate tables.
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
