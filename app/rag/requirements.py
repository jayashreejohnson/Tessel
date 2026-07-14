from app.models import DocType, EventType

# What a document of a given type must plausibly say to support a given
# milestone event. Scoped to EAD_NOTICE -> EAD_PENDING for now; adding a new
# document type later is adding an entry here, not restructuring the matcher.
MILESTONE_REQUIREMENTS: dict[DocType, dict[EventType, str]] = {
    DocType.EAD_NOTICE: {
        EventType.EAD_PENDING: (
            "USCIS Form I-765 receipt notice confirming that an Application "
            "for Employment Authorization Document has been filed and is "
            "currently pending adjudication."
        ),
    },
}


def get_requirement_text(doc_type: DocType, event_type: EventType) -> str:
    try:
        return MILESTONE_REQUIREMENTS[doc_type][event_type]
    except KeyError:
        raise NotImplementedError(
            f"No milestone requirement text defined for doc_type={doc_type.value} "
            f"against event_type={event_type.value}"
        )
