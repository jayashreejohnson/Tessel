from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db, init_db
from app.evidence_trail import build_evidence_trail

app = FastAPI(title="Tessel")
templates = Jinja2Templates(directory="app/templates")

_BADGE_CLASSES = {
    "RESOLVED": "badge-green",
    "SUPPORTS": "badge-green",
    "UNRESOLVED": "badge-gray",
    "CONTRADICTS": "badge-red",
    "NEEDS_REVIEW": "badge-amber",
    "UNCLEAR": "badge-amber",
    "ESCALATE_TO_HUMAN": "badge-amber",
}
templates.env.filters["badge_class"] = lambda status: _BADGE_CLASSES.get(status, "badge-gray")

_ACRONYMS = {"EAD", "INTL", "RAG"}


def _pretty(value: str) -> str:
    return " ".join(w if w.upper() in _ACRONYMS else w.capitalize() for w in value.split("_"))


templates.env.filters["pretty"] = _pretty


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/applicants/{applicant_id}/evidence-trail", response_class=HTMLResponse)
def evidence_trail(request: Request, applicant_id: int, db: Session = Depends(get_db)):
    trail = build_evidence_trail(db, applicant_id)
    if trail is None:
        raise HTTPException(status_code=404, detail=f"No applicant with id {applicant_id}")
    return templates.TemplateResponse(request, "evidence_trail.html", trail)
