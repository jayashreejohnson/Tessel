from sqlalchemy.orm import Session

from app.models import EventEvidenceLink, EvidenceDocument, MatchType, TimelineEvent
from app.rag.config import CONTRADICTION_KEYWORDS, SUPPORT_SIMILARITY_THRESHOLD
from app.rag.embeddings import cosine_similarity, embed
from app.rag.requirements import get_requirement_text


def _find_contradiction_keyword(text: str) -> str | None:
    lowered = text.lower()
    return next((kw for kw in CONTRADICTION_KEYWORDS if kw in lowered), None)


def match_document_to_event(
    db: Session, document: EvidenceDocument, event: TimelineEvent
) -> tuple[EventEvidenceLink, dict]:
    """
    Checks whether `document`'s content matches what `event` requires as
    evidence. Keyword check runs first (deterministic, certain); embedding
    similarity is the fallback for the genuinely fuzzy "does this plausibly
    match" question. Persists the result as an EventEvidenceLink and returns
    it alongside a detail dict for audit logging.
    """
    requirement_text = get_requirement_text(document.doc_type, event.event_type)
    text = document.raw_text or ""

    keyword_hit = _find_contradiction_keyword(text)
    similarity = cosine_similarity(embed(text), embed(requirement_text))

    if keyword_hit:
        match_type = MatchType.CONTRADICTS
    elif similarity >= SUPPORT_SIMILARITY_THRESHOLD:
        match_type = MatchType.SUPPORTS
    else:
        match_type = MatchType.UNCLEAR

    link = EventEvidenceLink(
        timeline_event_id=event.id,
        evidence_document_id=document.id,
        match_type=match_type,
        similarity_score=similarity,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    detail = {
        "requirement_text": requirement_text,
        "similarity_score": similarity,
        "similarity_threshold": SUPPORT_SIMILARITY_THRESHOLD,
        "contradiction_keyword_hit": keyword_hit,
    }
    return link, detail
