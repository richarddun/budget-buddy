Title: Security – Review and Hardening

Context
- Read-only ingestion tokens; server-side auth for writes; CSRF; rate limit admin.

Objective
- Audit security posture and implement controls per spec.

Deliverables
- Ensure:
  - YNAB tokens never exposed; stored via env and not logged.
  - CSRF on write endpoints.
  - Session/auth checks on POST/DELETE.
  - Rate limits for admin routes.
- Document findings and changes.

Dependencies
- After core APIs (Tasks 08, 13, 17, 19–21).

Implementation Notes
- Consider FastAPI dependencies for auth, CSRF tokens, and simple rate limiting.
- Sanitize logs; mask PII in exports by default.

Acceptance Criteria
- Manual checks confirm protections; automated tests cover common cases.

Test Guidance
- Unit tests for auth/CSRF paths; attempt unauthenticated writes and expect 401/403.

Affected/Added Files
- Touch: API modules, middleware, and docs.

