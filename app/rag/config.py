EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Below this cosine similarity to the reference requirement text, a document
# doesn't clearly match — UNCLEAR, not CONTRADICTS (low similarity is a weaker
# claim than an active contradiction; see CONTRADICTION_KEYWORDS for that).
SUPPORT_SIMILARITY_THRESHOLD = 0.5

# Deterministic, not ML: presence of any of these terms is a certain fact
# about the document's content, so it's checked before falling back to
# similarity scoring at all. Calibration showed both denial and approval
# notices score highly similar to the "pending" reference text (same topical
# domain, different stage) — similarity alone can't tell them apart, so both
# stages are caught here rather than by threshold.
CONTRADICTION_KEYWORDS = [
    "denied", "denial", "rejected", "revoked", "terminated",
    "approved", "approval",
]
