# Ingestion-side classification of incoming (credit) transactions. This is a
# deterministic keyword rule over the raw bank feed, same spirit as the RAG
# layer's contradiction-keyword check — a blunt but certain signal, not an
# ML inference. Debits (amount > 0) are always ignored; they're irrelevant
# to the two MVP rules, which only reason about incoming money.
INCOME_KEYWORDS = ["payroll", "salary", "direct dep"]
TRANSFER_KEYWORDS = ["zelle", "wire", "transfer", "remit", "intl"]
