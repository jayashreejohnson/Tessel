from datetime import date

from sqlalchemy.orm import Session

from app.models import EventCategory, EventSource, EventType, TimelineEvent
from app.rules.config import MIN_GAP_DAYS


def detect_income_gaps(db: Session, applicant_id: int, as_of: date) -> list[TimelineEvent]:
    """
    Scans an applicant's INCOME_RECEIVED events for stretches longer than
    MIN_GAP_DAYS with no income, including a trailing gap up to `as_of` if the
    most recent income event is old enough. Persists any gap not already on
    file as a SYSTEM_DERIVED INCOME_GAP event and returns the full current set.
    """
    income_events = (
        db.query(TimelineEvent)
        .filter(
            TimelineEvent.applicant_id == applicant_id,
            TimelineEvent.event_type == EventType.INCOME_RECEIVED,
        )
        .order_by(TimelineEvent.start_date)
        .all()
    )

    spans: list[tuple[date, date | None]] = []
    for prev_event, next_event in zip(income_events, income_events[1:]):
        if (next_event.start_date - prev_event.start_date).days > MIN_GAP_DAYS:
            spans.append((prev_event.start_date, next_event.start_date))

    if income_events and (as_of - income_events[-1].start_date).days > MIN_GAP_DAYS:
        spans.append((income_events[-1].start_date, None))

    existing = {
        (e.start_date, e.end_date)
        for e in db.query(TimelineEvent).filter(
            TimelineEvent.applicant_id == applicant_id,
            TimelineEvent.event_type == EventType.INCOME_GAP,
        )
    }

    for start, end in spans:
        if (start, end) in existing:
            continue
        db.add(
            TimelineEvent(
                applicant_id=applicant_id,
                category=EventCategory.INCOME,
                event_type=EventType.INCOME_GAP,
                start_date=start,
                end_date=end,
                source=EventSource.SYSTEM_DERIVED,
            )
        )
    db.commit()

    return (
        db.query(TimelineEvent)
        .filter(
            TimelineEvent.applicant_id == applicant_id,
            TimelineEvent.event_type == EventType.INCOME_GAP,
        )
        .order_by(TimelineEvent.start_date)
        .all()
    )
