Title: Questionnaire – Packs Assembly (Loan Application Basics, Affordability Snapshot)

Context
- Packs aggregate deterministic queries into a report bundle with drilldowns.

Objective
- Implement pack assembly server-side using query endpoints; expose a summary endpoint.

Deliverables
- Endpoint `GET /api/q/packs/{pack}?period=...` returning a structured JSON with sections and items.
- Supported packs: Loan Application Basics, Affordability Snapshot.

Dependencies
- Task 19.

Implementation Notes
- Implement in `q/packs.py` and `api/q.py`.
- Include for each item: value_cents, window, method, and a reference to `evidence_ids` retrievable via supporting-transactions endpoint.

Acceptance Criteria
- Pack responses are deterministic and sections map 1:1 with spec.

Test Guidance
- Unit test assembling packs with mocked query layer.

Affected/Added Files
- New: `q/packs.py` (and extend `api/q.py`).

