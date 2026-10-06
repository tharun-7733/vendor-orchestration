# Vendor Orchestration

An asynchronous screening service that accepts cases, dispatches KYC and sanctions checks to mock vendors, normalizes their different response shapes, and stores the case and vendor evidence in Postgres.

## Run locally

```sh
docker compose up --build
```

Open the screening dashboard at <http://localhost:8001>. Create an account or sign in to continue. The dashboard is India-only and includes synthetic examples for cleared, possible-match, and failed-identity decisions. API docs are at <http://localhost:8001/docs>; health endpoint: `GET /health`.

After signing in, select **New screening** in the dashboard. Authenticated API clients must keep the session cookies and send the CSRF token from `GET /auth/csrf` in the `X-CSRF-Token` header for state-changing requests.

The response contains a case ID. Poll `GET /v1/cases/{case_id}` for the completed result. `GET /v1/cases?limit=100` returns the latest cases for the signed-in user. Reusing an `external_reference` with the same subject returns the existing case; using it for different subject data returns `409`. The dashboard example buttons demonstrate `CLEARED`, `NEEDS_REVIEW`, and `REJECTED`. Names containing `unverified` fail identity verification; names containing `sanction` produce a possible mock-list match.

## Design

- FastAPI validates requests and exposes account registration, login, case intake, and retrieval. Passwords are PBKDF2-hashed; sessions use signed, HTTP-only, same-site cookies with CSRF tokens. Cases are private to the account that created them.
- Celery and Redis provide a durable background queue, late acknowledgements, and exponential retries.
- The KYC and sanctions adapters return intentionally different mock payloads. Normalizers map them to common `vendor`, `outcome`, `matched`, `confidence`, `payload`, and `error` fields.
- Postgres stores case lifecycle state and immutable vendor result records. `sql/schema.sql` documents the equivalent relational schema; the demo creates tables on API startup.
- Decisions are normalized as `CLEARED`, `NEEDS_REVIEW`, `REJECTED`, or `PENDING`. A possible sanctions match always needs human review and is never represented as confirmed. Missing results, provider errors, or queued work remain pending.
- The demo accepts India (`IN`) only. Mock providers do not query Indian or UN lists and do not perform real identity verification.
- The browser console is served by the API at the same origin. It uses a restrictive content security policy, safe text rendering, request timeouts, bounded case listing, and clear network/API error states. The Compose API port binds to localhost.

The mock providers are deterministic local stand-ins and make no real identity or sanctions checks. Use only synthetic information; do not submit real personal data. This Compose setup is for local demonstrations and uses development database credentials. Do not expose it to a network. With no `SESSION_SECRET` configured, the app generates a private signing key at startup, so restarting the API signs users out. Before any real deployment, set a strong persistent `SESSION_SECRET`, enable secure cookies behind HTTPS, add email verification and account recovery, rate limits, managed credentials, audited Alembic migrations, an outbox for atomic database-to-queue delivery, vendor request signing and timeouts, encryption and retention controls for personal data, and security monitoring. Existing unowned demo cases remain unassigned after the account migration and are not visible to new accounts. No system can promise zero vulnerabilities or failures.
