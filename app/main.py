from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.audit.log import record_human_decision
from app.db import get_db, init_db
from app.evidence_trail import build_case_queue, build_evidence_trail, pretty_label
from app.models import HumanDecision

app = FastAPI(title="Tessel")
templates = Jinja2Templates(directory="app/templates")

_BADGE_CLASSES = {
    "RESOLVED": "badge-green",
    "SUPPORTS": "badge-green",
    "APPROVE": "badge-green",
    "UNRESOLVED": "badge-gray",
    "CONTRADICTS": "badge-red",
    "FLAG": "badge-red",
    "NEEDS_REVIEW": "badge-amber",
    "UNCLEAR": "badge-amber",
    "ESCALATE_TO_HUMAN": "badge-amber",
    "REQUEST_MORE_EVIDENCE": "badge-amber",
}
templates.env.filters["badge_class"] = lambda status: _BADGE_CLASSES.get(status, "badge-gray")
templates.env.filters["pretty"] = pretty_label


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def case_queue(request: Request, db: Session = Depends(get_db)):
    rows = build_case_queue(db)
    return templates.TemplateResponse(request, "case_queue.html", {"rows": rows})


@app.get("/applicants/{applicant_id}/evidence-trail", response_class=HTMLResponse)
def evidence_trail(request: Request, applicant_id: int, db: Session = Depends(get_db)):
    trail = build_evidence_trail(db, applicant_id)
    if trail is None:
        raise HTTPException(status_code=404, detail=f"No applicant with id {applicant_id}")
    return templates.TemplateResponse(request, "evidence_trail.html", trail)


@app.post("/applicants/{applicant_id}/decision")
def submit_decision(
    applicant_id: int,
    decision: str = Form(...),
    reviewer: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    trail = build_evidence_trail(db, applicant_id)
    if trail is None:
        raise HTTPException(status_code=404, detail=f"No applicant with id {applicant_id}")
    try:
        decision_enum = HumanDecision(decision)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid decision: {decision}")

    record_human_decision(
        db, applicant_id, trail["latest_run_id"], decision_enum, reviewer.strip(), notes.strip() or None
    )
    return RedirectResponse(url=f"/applicants/{applicant_id}/evidence-trail", status_code=303)
