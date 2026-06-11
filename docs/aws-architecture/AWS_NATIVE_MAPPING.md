# Budget-Buddy → AWS Native Architecture
## 1,000-Foot Component Mapping

> Target deployment: **AWS-native serverless** | Auth: **Cognito** | Database: **Aurora Serverless v2 PostgreSQL** | Frontend: **S3 + CloudFront + HTMX**
> AI Layer (future): **Amazon Bedrock + Bedrock Agents**

---

## Layer 1: Frontend & Delivery

### CloudFront — CDN & HTTPS

```
┌─────────────────────────────────────────────────────────────────────────┐
│ CloudFront Distribution                                                 │
│                                                                         │
│  budget-buddy.example.com                                              │
│  ├── /*                    → S3 (static assets: index.html, JS, CSS)   │
│  ├── /api/*                → API Gateway (proxied, not cached)         │
│  ├── /uploads/*            → S3 (receipts, with signed URL validation) │
│  └── /exports/*            → S3 (generated reports)                    │
│                                                                         │
│  Behaviors:                                                             │
│  - Default TTL: 1 day on static, 0 on API                              │
│  - OAI (Origin Access Identity) for S3 origin                          │
│  - Custom error pages (404 → index.html for SPA routing)               │
│  - WAF association (rate limiting, IP blocks)                          │
└─────────────────────────────────────────────────────────────────────────┘
```

| CloudFront Concept | Budget-Buddy Mapping |
|-------------------|---------------------|
| **Distribution** | One distribution for the entire app |
| **Origin 1: S3** | Static assets bucket |
| **Origin 2: API Gateway** | Regional REST API endpoint |
| **Origin 3: S3 (protected)** | Receipts/exports with signed URLs |
| **Cache Policy** | Static assets cached at edge (1 day), API is 0 TTL |
| **OAI** | S3 bucket policy restricts to CloudFront only |
| **Custom Domain** | Route53 alias → CloudFront (e.g., budget.example.com) |
| **WAF ACL** | Rate-based rule, common bot block list |

---

### S3 — Object Storage (3 Buckets)

```
┌──────────┬────────────────────────────────┬─────────────────────────┐
│ Bucket   │ Purpose                        │ Access Pattern          │
├──────────┼────────────────────────────────┼─────────────────────────┤
│ static   │ index.html, sidebar.js,        │ CloudFront OAI (public) │
│          │ HTMX 1.9.2 (vendored), CSS     │ GET only                │
├──────────┼────────────────────────────────┼─────────────────────────┤
│ receipts │ Uploaded receipt images        │ Lambda writes,          │
│          │                                │ CloudFront signed URLs  │
├──────────┼────────────────────────────────┼─────────────────────────┤
│ exports  │ Generated reports (HTML/PDF    │ Lambda writes,          │
│          │ questionnaire exports)         │ CloudFront signed URLs  │
└──────────┴────────────────────────────────┴─────────────────────────┘
```

| S3 Concept | Budget-Buddy Mapping |
|-----------|---------------------|
| **Bucket: static** | Replaces `./static/` directory on disk |
| **Bucket: receipts** | Replaces `./uploaded_receipts/` on disk |
| **Bucket: exports** | Replaces `./localdb/exports/` on disk |
| **Lifecycle Policy** | Auto-delete receipts > 90 days (optional) |
| **Encryption** | SSE-S3 (default), KMS for compliance |
| **Bucket Policy** | OAI only for static; Lambda + pre-signed URLs for data buckets |
| **CORS** | Allow CloudFront origin only |

---

### Cognito — Authentication

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Cognito User Pool                                                      │
│                                                                         │
│  Pool name: budget-buddy-users                                          │
│  ┌──────────────────────────────────┐                                  │
│  │ App Client: budget-buddy-spa     │──→ Login via Hosted UI           │
│  │                                  │    (cloudfront domain → /login)  │
│  │  OAuth 2.0: authorization_code   │                                  │
│  │  Scopes: openid, email, profile  │                                  │
│  │  Callback: https://budget.../     │                                  │
│  │  Logout:   https://budget.../     │                                  │
│  └──────────────────────────────────┘                                  │
│                                                                         │
│  Users:                                                                 │
│    - Richard (you)   → Pre-created admin user                          │
│    - Future: partner, family members with limited scope                 │
│                                                                         │
│  Lambda Triggers:                                                       │
│    - Pre Token Generation → Add custom claims (role: admin/user)        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

| Cognito Concept | Budget-Buddy Mapping |
|----------------|---------------------|
| **User Pool** | One pool for all budget-buddy users |
| **App Client** | SPA client with OAuth auth code flow |
| **Hosted UI** | Ready-made login page (no PIN form to build) |
| **JWT Tokens** | ID token for user identity, Access token for API auth |
| **Custom Claims** | `custom:role` = admin/viewer for authorization |
| **Domain** | `budget-buddy.auth.us-east-1.amazoncognito.com` |
| **Triggers** | Pre sign-up (auto-confirm if domain matches), Post auth (logging) |

**How it replaces current PIN auth:**
- `APP_ACCESS_PIN` env var → Gone
- `/login` Jinja2 template → Gone
- `hmac.compare_digest(pin, expected)` → Replaced by JWT validation in API Gateway
- Session cookies → Replaced by Cognito tokens stored in HTTP-only cookies (or localStorage)
- `_require_session_dep()` → Replaced by API Gateway Lambda authorizer checking the JWT

---

## Layer 2: API & Compute

### API Gateway — REST API Front Door

```
┌─────────────────────────────────────────────────────────────────────────┐
│ API Gateway (REST API)                                                  │
│                                                                         │
│  https://api-gw-id.execute-api.us-east-1.amazonaws.com/v1               │
│                                                                         │
│  Routes:                                                                │
│  ┌─────────────┬──────────────────────┬────────────────────────────┐   │
│  │ Method+Path │ Lambda Target        │ Auth                       │   │
│  ├─────────────┼──────────────────────┼────────────────────────────┤   │
│  │ GET  /overview     → overview-lambda  │ Cognito JWT Authorizer  │   │
│  │ GET  /digest       → overview-lambda  │ Cognito JWT Authorizer  │   │
│  │                 │                       │                          │   │
│  │ GET  /commitments         → commitments-lambda │ Cognito JWT      │   │
│  │ POST /commitments         → commitments-lambda │ Cognito JWT      │   │
│  │ PUT  /commitments/{id}    → commitments-lambda │ Cognito JWT      │   │
│  │ DEL  /commitments/{id}    → commitments-lambda │ Cognito JWT      │   │
│  │                 │                       │                          │   │
│  │ GET  /transactions         → tx-lambda │ Cognito JWT              │   │
│  │ POST /transactions         → tx-lambda │ Cognito JWT              │   │
│  │ DEL  /transactions/{id}    → tx-lambda │ Cognito JWT              │   │
│  │                 │                       │                          │   │
│  │ GET  /forecast?start=&end= → forecast-lambda  │ Cognito JWT       │   │
│  │                 │                       │                          │   │
│  │ GET  /categories          → cat-lambda  │ Cognito JWT             │   │
│  │ POST /categories          → cat-lambda  │ Cognito JWT             │   │
│  │                 │                       │                          │   │
│  │ GET  /budget-targets      → bt-lambda   │ Cognito JWT             │   │
│  │ POST /budget-targets      → bt-lambda   │ Cognito JWT             │   │
│  │                 │                       │                          │   │
│  │ POST /uploads             → upload-lambda│ Cognito JWT + 10MB     │   │
│  │ GET  /exports/{file}      → export-lambda│ Cognito JWT            │   │
│  │                 │                       │                          │   │
│  │ POST /chat (future)       → chat-lambda │ Cognito JWT + streaming │   │
│  └─────────────┴──────────────────────┴────────────────────────────┘   │
│                                                                         │
│  Common Settings:                                                       │
│  - Content-Type: application/json (API) / text/html (HTMX)              │
│  - Request validation on POST/PUT (JSON schema)                         │
│  - Throttling: 100 req/s per route (burst 200)                          │
│  - Custom domain: api.budget-buddy.example.com                          │
└─────────────────────────────────────────────────────────────────────────┘
```

| API Gateway Concept | Budget-Buddy Mapping |
|-------------------|---------------------|
| **REST API** | Standard REST, supports HTMX HTML responses |
| **Cognito Authorizer** | Validates JWT on every request, replaces PIN sessions |
| **Request Validation** | Models for POST/PUT bodies (amount_cents is int, date is ISO, etc.) |
| **Lambda Integration** | Proxy integration (Lambda receives the full request context) |
| **Binary Media Types** | `multipart/form-data` for receipt uploads |
| **Throttling** | 100 req/s (family use won't hit this, prevents abuse) |
| **Stage** | `v1` — single stage, prod. Can add `staging` later. |

---

### Lambda Functions — Business Logic Handlers

Each Lambda function maps to a domain in the current codebase.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Lambda Function Map (8 functions)                                       │
│                                                                         │
│  Each function:                                                         │
│  - Runtime: Python 3.12                                                 │
│  - Memory: 256 MB (128 for simple CRUD, 512 for forecast engine)        │
│  - Timeout: 29 seconds (15 sec for CRUD)                                │
│  - VPC: Connected to RDS security group                                 │
│  - Layers: shared-deps-layer (pydantic, httpx, jinja2, etc.)            │
│  - Environment: SSM parameter references for secrets                    │
│  - DLQ: SQS (for ingestion/snapshot failures)                           │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│ FUNCTION: overview-lambda                                               │
│  Source: api/overview.py + agents/budget_agent_real.py (digest parts)   │
│  Trigger: API Gateway → GET /overview, GET /digest                      │
│  Logic: 1. Load latest forecast_snapshot from RDS                       │
│         2. Compute digest (current_balance, safe_to_spend,              │
│            next_cliff, top_commitments_14d)                              │
│         3. Return JSON or HTML fragment                                  │
│  Key code to extract:                                                   │
│   - compute_latest_digest()                                             │
│   - compute_opening_balance_cents()                                     │
│   - _compute_digest_from_snapshot()                                     │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│ FUNCTION: commitments-lambda                                            │
│  Source: api/commitments.py + agents/budget_agent_real.py (commit tools)│
│  Trigger: API Gateway → CRUD /api/commitments                           │
│  Logic:                                                                 │
│   - GET:    List all commitments, optionally filtered by type           │
│   - POST:   INSERT into commitments table                               │
│   - PUT:    UPDATE commitment fields (amount, due_rule, next_due)       │
│   - DELETE: DELETE commitment by id                                     │
│  Key code to extract:                                                   │
│   - add_commitment() validation logic                                   │
│   - list_commitments() query                                            │
│   - detect_commitment_candidates() for auto-detection                   │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│ FUNCTION: tx-lambda (transactions)                                      │
│  Source: api/transactions.py                                            │
│  Trigger: API Gateway → CRUD /api/transactions                          │
│  Logic:                                                                 │
│   - GET:    List transactions with pagination, date filters             │
│   - POST:   INSERT transaction with idempotency_key                     │
│   - DELETE: DELETE by idempotency_key                                   │
│  Key code: api/transactions.py router (minus FastAPI decorators)        │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│ FUNCTION: cat-lambda (categories)                                       │
│  Source: api/categories.py                                              │
│  Trigger: API Gateway → CRUD /api/categories                           │
│  Logic: Category hierarchy tree, add/edit/archive operations            │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│ FUNCTION: forecast-lambda                                               │
│  Source: api/forecast.py + forecast/calendar.py                         │
│  Trigger: API Gateway → GET /api/forecast                               │
│           EventBridge Scheduler → Nightly snapshot                      │
│  Logic:                                                                 │
│   1. compute_opening_balance_cents(as_of=start)                         │
│   2. expand_calendar(start, end) across commitments, key events,        │
│      recurring_templates                                                │
│   3. compute_balances(opening, entries)                                 │
│   4. find min_balance_cents/date                                        │
│   5. Optionally run Monte Carlo (future)                                │
│  Key code: expand_calendar(), compute_balances(), forecast endpoint     │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│ FUNCTION: bt-lambda (budget-targets)                                    │
│  Source: api/budget_targets.py                                          │
│  Trigger: API Gateway → CRUD /api/budget-targets                        │
│  Logic: Monthly envelope targets, rollover tracking, progress           │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│ FUNCTION: upload-export-lambda (receipts + exports)                     │
│  Source: main.py upload endpoints + localdb/exports/                    │
│  Trigger: API Gateway → POST /api/uploads, GET /api/exports/{file}     │
│  Logic:                                                                 │
│   - Write uploaded file to S3 bucket (receipts/)                        │
│   - Read from S3 bucket (exports/) and return signed URL                │
│  Key code: upload_receipt(), export generation                          │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│ FUNCTION: ingestion-lambda (background worker)                          │
│  Source: jobs/daily_ingestion.py, jobs/nightly_snapshot.py              │
│         , jobs/recurring_templates.py                                   │
│  Trigger: EventBridge Scheduler (daily 07:00, nightly 02:00)            │
│  NOT: exposed via API Gateway                                           │
│  Logic:                                                                 │
│   - Detect recurring patterns from transactions                         │
│   - Detect subscriptions from spending patterns                         │
│   - Auto-create commitments from subscription detection                 │
│   - Run forecast calendar + snapshot                                    │
│   - Generate alerts for overspending (future)                           │
│  Key code: run_daily_ingestion(), run_nightly_snapshot_async()          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

| Lambda Concept | Budget-Buddy Mapping |
|--------------|---------------------|
| **Runtime** | Python 3.12 |
| **Lambda Layers** | `shared-deps` layer with: pydantic, pydantic-ai, httpx, jinja2, boto3 (built-in), psycopg2-binary |
| **VPC** | Private subnets in VPC, connected to RDS via security group |
| **IAM** | Each function has minimal permissions: `rds:*` on its SG, `ssm:GetParameter*` on its path, `s3:PutObject` on its bucket |
| **Reserved Concurrency** | 1 (per function) — enough for single-user, prevents runaway costs |
| **Provisioned Concurrency** | 0 (accept cold start latency) |
| **Environment** | `DB_SECRET_ARN`, `BUCKET_RECEIPTS`, `BUCKET_EXPORTS`, `STAGE` |
| **Lambda Function URL** | Alternative to API Gateway for simple functions (future optimization) |

---

## Layer 3: Data & Storage

### Aurora Serverless v2 — PostgreSQL Database

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Aurora Serverless v2 PostgreSQL 16.4                                    │
│                                                                         │
│  Cluster: budget-buddy-db                                               │
│  ├── Writer endpoint: budget-buddy-db.cluster-xxx.us-east-1.rds.amazonaws.com
│  └── (No reader — single user, single AZ for cost)                      │
│                                                                         │
│  Capacity:  0.5 ACU (min) → 2.0 ACU (max)                             │
│  Storage:   20 GB gp3 (auto-scaling to 64 TB if needed)                │
│  Pause:     After 5 minutes of no connections (PAUSE)                   │
│  Resume:    On first connection (~2-3 second cold start)               │
│  Backup:    7 day retention, automated backups                          │
│  Encryption: AWS KMS                                                     │
│                                                                         │
│  Schema migrations: Alembic (running in Lambda cold start or CDK hook)  │
│                                                                         │
│  ┌───────────────────────────────────────────────┐                     │
│  │ DATABASE: budget_buddy                        │                     │
│  │                                               │                     │
│  │ TABLES (from domain):                         │                     │
│  │   accounts        → Account management        │                     │
│  │   categories      → Category hierarchy        │                     │
│  │   category_map    → External ID mapping        │                     │
│  │   transactions    → All transaction history    │                     │
│  │   commitments     → Recurring obligations      │                     │
│  │   scheduled_inflows → Income schedules          │                     │
│  │   key_spend_events  → Known future spend events │                     │
│  │   forecast_snapshot → Cached forecast runs      │                     │
│  │   budget_targets    → Monthly envelope caps     │                     │
│  │   budget_rollovers  → Carry-over tracking       │                     │
│  │   recurring_templates→ Auto-create rules        │                     │
│  │   recurring_instances→ Dedup tracking           │                     │
│  │   transaction_splits→ Split transaction records  │                     │
│  │   alerts            → Event triggers             │                     │
│  │   account_anchors   → Per-account floor balances │                     │
│  │   payee_rules       → Pattern→category mapping  │                     │
│  │   source_cursor     → Incremental sync state    │                     │
│  │   ingest_audit      → Ingestion run log         │                     │
│  │   schema_migrations → Migration tracking        │                     │
│  │                                               │                     │
│  └───────────────────────────────────────────────┘                     │
│                                                                         │
│  Security:                                                              │
│  - Private subnets only (no public access)                              │
│  - Security group allows PostgreSQL (5432) from Lambda SG only          │
│  - Secrets Manager stores master password, Lambda retrieves at startup  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

| RDS/Aurora Concept | Budget-Buddy Mapping |
|-------------------|---------------------|
| **Aurora Serverless v2** | Best cost for low-usage: 0.5 ACU min, auto-pause |
| **PostgreSQL 16.4** | Direct migration from SQLite (similar SQL dialect) |
| **Private Subnet** | In VPC, not internet-accessible |
| **Secrets Manager** | DB credentials stored as secret, Lambda retrieves on start |
| **Auto-Pause** | 5 min inactivity → 0 cost until next request |
| **Alembic** | Migrations from SQLite schema to PostgreSQL (one-time) |

**Migration from SQLite to PostgreSQL:**

The current SQLite schema maps almost verbatim:
```sql
-- SQLite (current)                        PostgreSQL (target)
CREATE TABLE accounts (                     CREATE TABLE accounts (
  id INTEGER PRIMARY KEY,                     id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,                         name VARCHAR(255) NOT NULL,
  ...
```

Main differences:
- `INTEGER PRIMARY KEY` → `SERIAL PRIMARY KEY`
- `TEXT` → `VARCHAR(n)` or `TEXT`
- `datetime('now')` → `NOW()`
- No more SQLite-specific pragmas

---

### S3 — Object Storage (revisited for data layer)

| Data Type | Current Location | AWS Target | Lambda Access | User Access |
|-----------|-----------------|------------|---------------|-------------|
| Receipt uploads | `./uploaded_receipts/` | `s3://bb-receipts/{user_id}/{uuid}.jpg` | `s3:PutObject` via upload-lambda | Signed URL from CloudFront |
| Export files | `./localdb/exports/` | `s3://bb-exports/{user_id}/{timestamp}.html` | `s3:PutObject` via export-lambda | Signed URL from CloudFront |
| Chat history | `./chat_history.db` | RDS `chat_messages` table (future) | Direct DB write | Through API |

---

## Layer 4: Background Processing

### EventBridge Scheduler — Cron Jobs

```
┌─────────────────────────────────────────────────────────────────────────┐
│ EventBridge Scheduler Rules                                             │
│                                                                         │
│  Rule 1: daily-ingestion                                                │
│  ┌───────────────────────────────────────────────┐                     │
│  │ Schedule:   cron(0 7 * * ? *)                  │ ← 07:00 UTC daily  │
│  │ Target:     ingestion-lambda                    │                     │
│  │ Payload:    {"type": "daily_ingestion",        │                     │
│  │               "tz": "Europe/Dublin"}            │                     │
│  │ Retry:      3 attempts, 5 min apart             │                     │
│  │ DLQ:        ingestion-dlq (SQS)                 │                     │
│  └───────────────────────────────────────────────┘                     │
│                                                                         │
│  Rule 2: nightly-snapshot                                              │
│  ┌───────────────────────────────────────────────┐                     │
│  │ Schedule:   cron(0 2 * * ? *)                  │ ← 02:00 UTC daily  │
│  │ Target:     forecast-lambda                     │                     │
│  │ Payload:    {"type": "nightly_snapshot",       │                     │
│  │               "horizon_days": 90}               │                     │
│  │ Retry:      3 attempts, 5 min apart             │                     │
│  └───────────────────────────────────────────────┘                     │
│                                                                         │
│  Cost: $1/schedule/month = $2/mo total                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

| EventBridge Concept | Budget-Buddy Mapping |
|--------------------|---------------------|
| **Scheduler** | Replaces `scheduler_loop()` in-process `asyncio` task |
| **cron()** | Standard cron expression |
| **Flexible Time Window** | `@7am` with 30min window (avoids retry storms) |
| **DLQ (SQS)** | Failed ingestion goes to dead-letter queue for debugging |
| **Payload** | Static JSON sent to Lambda on each trigger |

---

## Layer 5: Security & Secrets

### SSM Parameter Store — Configuration

```
┌─────────────────────────────────────────────────────────────────────────┐
│ SSM Parameter Store (/budget-buddy/)                                    │
│                                                                         │
│  Path                          │ Type      │ Used By                     │
│ ───────────────────────────────┼───────────┼────────────────────────────│
│ /budget-buddy/env              │ String     │ All Lambdas (STAGING flag) │
│ /budget-buddy/openai-key       │ SecureString │ Chat Lambda (future)     │
│ /budget-buddy/ynab-token       │ SecureString │ Ingestion Lambda (future)│
│ /budget-buddy/budget-id        │ String     │ (future YNAB re-add)       │
│ /budget-buddy/buckets/receipts │ String     │ Upload Lambda              │
│ /budget-buddy/buckets/exports  │ String     │ Export Lambda              │
│ /budget-buddy/buckets/static   │ String     │ CDK deploy                 │
│ /budget-buddy/cognito/pool-id  │ String     │ API Gateway authorizer     │
│ /budget-buddy/cognito/client-id│ String     │ Frontend SPA config        │
│                                                                         │
│  Cost: $0.05 per param/month = ~$0.50/mo                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### Secrets Manager — Database Credentials

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Secrets Manager                                                         │
│                                                                         │
│  Secret: /budget-buddy/database                                        │
│  ┌────────────────────────────────────┐                                │
│  │ {                                   │                                │
│  │   "username": "bb_admin",          │                                │
│  │   "password": "<auto-generated>",  │                                │
│  │   "engine": "postgres",            │                                │
│  │   "host": "<cluster-endpoint>",    │                                │
│  │   "port": 5432,                    │                                │
│  │   "dbname": "budget_buddy",        │                                │
│  │   "dbClusterIdentifier": "bb-db"   │                                │
│  │ }                                   │                                │
│  └────────────────────────────────────┘                                │
│                                                                         │
│  Auto-generated on RDS cluster creation by CDK                          │
│  Lambda retrieves at cold start, caches for duration of invocation      │
│                                                                         │
│  Rotation: Disabled initially (single user, manual rotate if needed)    │
│  Cost: $0.40/secret/month                                               │
└─────────────────────────────────────────────────────────────────────────┘
```

### KMS — Encryption at Rest

```
┌─────────────────────────────────────────────────────────────────────────┐
│ KMS Keys                                                                │
│                                                                         │
│  Key 1: budget-buddy-db                                                │
│    - Alias: alias/budget-buddy/db                                      │
│    - Purpose: Encrypt Aurora cluster storage + backups                  │
│    - Grants: RDS service principal                                      │
│                                                                         │
│  Key 2: budget-buddy-s3                                                │
│    - Alias: alias/budget-buddy/s3                                      │
│    - Purpose: Encrypt S3 buckets (receipts + exports)                   │
│    - Grants: Lambda execution role, S3 service principal                │
│                                                                         │
│  Cost: $1/month/key = $2/mo                                             │
│  (Optional: can use SSE-S3 / AWS-managed for free until compliance      │
│   requirements demand customer-managed keys)                            │
└─────────────────────────────────────────────────────────────────────────┘
```

### WAF — Web Application Firewall

```
┌─────────────────────────────────────────────────────────────────────────┐
│ WAF Web ACL (associated with CloudFront)                                │
│                                                                         │
│  Rules:                                                                 │
│  1. AWS-AWSManagedRulesCommonRuleSet (Core rule set)                    │
│     - SQL injection, XSS, known bad inputs, LFI/RFI                    │
│                                                                         │
│  2. Rate-based rule: 500 requests per 5 minutes per IP                  │
│     - Blocks brute force login attempts                                 │
│     - Prevents accidental API abuse                                     │
│                                                                         │
│  3. IP allowlist rule (optional)                                        │
│     - If you want to restrict to Ireland/your home IP                   │
│                                                                         │
│  Cost: ~$5-6/mo basic (AWS WAF free tier covers first 10 ACLs,          │
│         but rule groups cost ~$1 each)                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Layer 6: Monitoring & Observability

### CloudWatch — Logs, Metrics, Alarms

```
┌─────────────────────────────────────────────────────────────────────────┐
│ CloudWatch                                                              │
│                                                                         │
│  Log Groups (auto-created per Lambda):                                 │
│   - /aws/lambda/budget-buddy-overview                                  │
│   - /aws/lambda/budget-buddy-commitments                               │
│   - /aws/lambda/budget-buddy-forecast                                  │
│   - /aws/lambda/budget-buddy-ingestion                                 │
│   - ... [one per Lambda function]                                       │
│   → Log retention: 14 days (cost optimization)                         │
│                                                                         │
│  Metrics (auto):                                                        │
│   - Invocations, Duration, Errors, Throttles (per function)             │
│   - API Gateway: 4XX/5XX count, latency                                │
│   - RDS: Connections, CPU, Freeable Memory                              │
│                                                                         │
│  Custom Metrics (published by Lambda):                                  │
│   - ForecastRunSuccess/Failure                                          │
│   - IngestionRowCount                                                   │
│   - CommitmentsDetected                                                 │
│                                                                         │
│  Alarms:                                                                │
│   - budget-buddy-errors: Any Lambda error > 0 in 5 min → SNS email     │
│   - budget-buddy-ingestion-failure: Ingestion lambda fails → SNS email  │
│   - budget-buddy-db-connections: RDS connections > 80% → SNS email     │
│                                                                         │
│  Cost: ~$0-2/mo (free tier covers 5GB logs, 10 metrics, 10 alarms)     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Layer 7: AI/Agentic Layer (Future — Bedrock)

When you re-add the AI assistant, this layer slots in naturally:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Bedrock (Future — Post-GenAI Pro Certification Study)                   │
│                                                                         │
│  Component               │ Purpose                                      │
│ ─────────────────────────┼─────────────────────────────────────────────│
│ Bedrock Runtime          │ Foundation model inference                   │
│  - Claude 3.5 Sonnet    │ Primary assistant (financial reasoning)       │
│  - Nova Pro              │ Alternative/backup model                     │
│                           │                                              │
│ Bedrock Agent            │ Tool orchestration (replaces pydantic-ai)    │
│  - Action Groups         │ Lambda functions as tools (commitments,      │
│                           │ forecast, transactions, etc.)               │
│  - Knowledge Base        │ RAG on historical financial data             │
│                           │  (S3 with embeddings in Aurora pgvector)    │
│                           │                                              │
│ chat-lambda              │ Streams responses back via API Gateway SSE   │
│  (new function)          │ Uses Bedrock InvokeAgentWithResponseStream   │
│                           │                                              │
│ Cost: ~$0.50-2.00/session (token-based, minimal for family use)        │
└─────────────────────────────────────────────────────────────────────────┘
```

The key insight is that your Lambda tool functions **are already built** — they're the same 6-8 Lambda functions above. Bedrock Agent just orchestrates them.

---

## Layer 8: Deployment & Infrastructure (CDK)

### CDK Application Structure

```
budget-buddy/
├── cdk/                                  # AWS CDK infrastructure as code
│   ├── bin/
│   │   └── budget-buddy.ts               # App entry point
│   ├── lib/
│   │   ├── budget-buddy-stack.ts          # Main stack composition
│   │   ├── networking-stack.ts            # VPC, subnets, security groups
│   │   ├── database-stack.ts              # Aurora Serverless v2 cluster
│   │   ├── auth-stack.ts                  # Cognito user pool
│   │   ├── storage-stack.ts               # S3 buckets
│   │   ├── api-stack.ts                   # API Gateway + Lambda functions
│   │   ├── frontend-stack.ts              # CloudFront + S3 static
│   │   └── background-stack.ts            # EventBridge Scheduler + SQS
│   ├── lambda/                            # Lambda function source code
│   │   ├── shared/                        # Lambda Layer code
│   │   │   └── requirements.txt          # pydantic, httpx, jinja2, psycopg2
│   │   ├── overview/
│   │   │   ├── index.py                   # Handler
│   │   │   └── handler.py                 # Business logic (extracted from main.py)
│   │   ├── commitments/
│   │   │   └── handler.py
│   │   ├── transactions/
│   │   │   └── handler.py
│   │   ├── categories/
│   │   │   └── handler.py
│   │   ├── forecast/
│   │   │   └── handler.py
│   │   ├── budget-targets/
│   │   │   └── handler.py
│   │   ├── upload/
│   │   │   └── handler.py
│   │   └── ingestion/
│   │       └── handler.py
│   └── test/                              # CDK unit tests
│       └── ...
│
├── frontend/                              # Static frontend assets
│   ├── index.html                         # Shell (HTMX-powered)
│   ├── js/
│   │   └── sidebar.js                     # Your existing sidebar.js
│   ├── css/
│   └── fragments/                         # HTMX fragment templates
│       ├── overview.html                  # Server by overview-lambda
│       ├── commitments.html
│       └── ...
│
├── docs/aws-architecture/                 # This document + design docs
│   └── AWS_NATIVE_MAPPING.md
│
└── config.ts                              # Shared config (env, account, region)
```

---

## Cost Summary — Full Serverless Build

| Service | Configuration | Monthly Cost (est.) |
|---------|--------------|---------------------|
| **CloudFront** | 1 distribution, ~1GB transfer | $0.09 |
| **S3** | 3 buckets, ~5GB total | $0.12 |
| **API Gateway** | REST API, ~5K requests | $1.00 |
| **Lambda** | 8 functions, ~100K invocations, 256MB | ~$0.50 (mostly free tier) |
| **Cognito** | 1-3 users | $0.00 (free tier) |
| **Aurora Serverless v2** | 0.5 ACU min, auto-pause | ~$5-15 |
| **EventBridge Scheduler** | 2 schedules | $2.00 |
| **SSM Parameter Store** | ~10 params | $0.50 |
| **Secrets Manager** | 1 DB secret | $0.40 |
| **KMS** | 2 customer keys | $0.00 (free tier, or $2) |
| **WAF** | 1 ACL + managed rules | ~$5-6 |
| **Route53** | 1 hosted zone | $0.50 |
| **CloudWatch** | Logs + alarms | ~$0.50 |
| **Total** | | **~$15-26/mo** |

**Optimization path:** Skip WAF (-$5), use SSE-S3 instead of KMS (-$2), static config instead of SSM (-$0.50) → ~**$8-18/mo**

Compare to Lightsail $5/mo — you're paying **~$3-13/mo** for the serverless native architecture.

---

## Architecture Diagram (ASCII)

```
                          ┌─────────────────────────────┐
                          │   CloudFront Distribution    │
                          │   budget-buddy.example.com  │
                          └──────────┬──────────────────┘
                                     │
            ┌────────────────────────┼────────────────────┐
            │                        │                     │
     ┌──────┴──────┐         ┌───────┴───────┐    ┌──────┴──────┐
     │   S3 Bucket │         │  API Gateway   │    │  S3 Buckets │
     │   [static]  │         │  REST /v1/*    │    │ [receipts,  │
     │   index.html│         │  Cognito Auth  │    │  exports]   │
     │   JS, CSS   │         └───────┬───────┘    └─────────────┘
     └─────────────┘                 │
                                     │
                 ┌───────────────────┼──────────────────────┐
                 │                   │                       │
          ┌──────┴──────┐    ┌───────┴──────┐      ┌───────┴──────┐
          │  Lambda     │    │  Lambda      │      │  Lambda      │  ... 6 more
          │  overview   │    │  commitments │      │  forecast    │  functions
          └──────┬──────┘    └───────┬──────┘      └───────┬──────┘
                 │                   │                       │
                 └───────────────────┼───────────────────────┘
                                     │
                            ┌────────┴────────┐
                            │  RDS Proxy     │
                            │  (optional)    │
                            └────────┬────────┘
                                     │
                            ┌────────┴────────┐
                            │  Aurora SV2     │
                            │  PostgreSQL     │
                            │  (private)      │
                            └─────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │  EventBridge Scheduler (x2)                                 │
    │   07:00 → ingestion-lambda → pattern detection & snapshot   │
    │   02:00 → forecast-lambda  → nightly forecast snapshot     │
    └─────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │  (Future) Bedrock Agent                                     │
    │   chat-lambda → Bedrock InvokeAgent → Claude/Nova           │
    │              → Tool calls to existing Lambda functions      │
    └─────────────────────────────────────────────────────────────┘
```

---

## Next Steps — Build Order

This is the recommended order if we build together in CDK:

| Phase | What | Stack(s) | CDK ~Lines |
|-------|------|---------|-----------|
| **1** | VPC + Networking | `networking-stack` | 40 |
| **2** | Aurora Serverless v2 | `database-stack` | 80 |
| **3** | S3 Buckets | `storage-stack` | 60 |
| **4** | Cognito | `auth-stack` | 70 |
| **5** | Lambda Layer + One Lambda (commitments) | `api-stack` (partial) | 100 |
| **6** | Rest of Lambda functions | `api-stack` (expansion) | 200 |
| **7** | API Gateway | `api-stack` (expansion) | 80 |
| **8** | CloudFront + S3 static | `frontend-stack` | 60 |
| **9** | EventBridge Scheduler | `background-stack` | 40 |
| **10** | WAF + CloudWatch Alarms | `frontend-stack` + add-ons | 60 |
| **11** | *(Future)* Bedrock Agent | `ai-stack` | 100 |

Total CDK: ~**800-900 lines** for a full serverless deployment.

---

Ready to write CDK? I suggest we start with **Phase 1 (Networking)** and **Phase 2 (Database)** since everything depends on the VPC and Aurora cluster. Fancy cracking open a CDK project?