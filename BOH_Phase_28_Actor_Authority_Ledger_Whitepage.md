# BOH Phase 28 Whitepage Build Doc
## Actor, Authorship, Responsibility, and Authority Ledger

**Target repo:** Bag of Holding  
**Intended implementer:** Codex or another code-capable LLM  
**Status:** Build specification / initiation document  
**Depends on:** Phase 27 Boundary Integrity Hardening and Phase 27.1 Operator Dev Workflow + Clean Slate / Seed Harness  

---

## 1. Purpose

Bag of Holding is a governed knowledge system. Its core doctrine is:

```text
LLM proposes.
Human governs.
System audits.
```

Phase 27 hardened the filesystem, execution, and operator boundary. That work protects dangerous actions, but it does not yet create a durable model of **who or what did what, under what authority, inside which project, and with what responsibility**.

Phase 28 adds the missing governance substrate:

```text
Actor Registry + Authority Registry + Action Ledger + Attribution Layer
```

The goal is not generic user accounts. The goal is **governance-grade attribution**.

BOH must be able to answer:

- Who authored this content?
- Who imported it?
- Who modified it?
- Who reviewed it?
- Who approved or rejected it?
- Who resolved its governance state?
- Which LLM proposed a change?
- Which human/operator accepted responsibility?
- What authority allowed that action?
- Was the action allowed, denied, proposed, approved, rejected, reverted, or escalated?
- Is this authority global, project-scoped, document-scoped, plane-scoped, or temporary?

This patch should make agency, responsibility, authorship, and authority visible and auditable.

---

## 2. Problem Statement

Current BOH appears to have several partial mechanisms:

- document metadata and frontmatter
- governance metadata
- operator token authorization
- entity types such as human / LLM / system in some areas
- protected mutation routes
- lifecycle, authority, approval, and certificate routes
- append-only audit concepts

But these are not yet unified into a durable actor model.

The current operator token proves that a local operator has access. It does **not** prove which human, LLM, importer, reviewer, contact, external stakeholder, or system process performed a specific action.

This causes governance ambiguity:

```text
Protected action happened, but actor identity is unclear.
Content exists, but authorship is unclear.
Approval happened, but authority basis is unclear.
LLM proposed something, but proposal provenance is incomplete.
Project responsibility exists socially, but is not encoded structurally.
```

This is the same category of drift BOH exists to detect: reality, representation, responsibility, and decision authority have separated.

---

## 3. Design Principle

Do not build this as a SaaS login system.

Build this as a **local-first governance identity substrate**.

The minimum viable model should support:

```text
Human actors
LLM actors
System actors
Importer actors
External contacts
Project-local roles
Global roles
Temporary/delegated authority
Action ledger events
Document attribution
Project responsibility mapping
```

Actor identity and operator authorization must remain separate concepts:

```text
Operator token = permission to use protected local controls.
Actor identity = who/what is recorded as responsible for an action.
Authority basis = why that actor was allowed to perform the action.
```

A valid operator token may permit a mutation, but the action should still be logged as performed by a specific actor, even if the default actor is only `local_operator`.

---

## 4. Relationship to Project Atlas

> "Project Atlas" is an earlier private prototype by the same author, referenced here only as
> design lineage. (The same name also appears as a synthetic project label in BOH's demo
> fixtures; the two uses are unrelated.)

Project Atlas previously had a partial version of this idea through owner fields and governance screens.

Observed Atlas pattern:

```text
projects.owner
stages.owner
work_items.owner
Governance screen for stage/work ownership
```

That model is useful but too shallow for BOH. It records ownership text, but does not fully resolve:

- actor identity
- authority basis
- action provenance
- project-level responsibility
- LLM vs human proposal boundaries
- approval/resolution legitimacy
- audit history

Phase 28 should recover the useful Atlas idea — ownership/responsibility belongs directly in the system — but implement it at BOH’s governance depth.

---

## 5. Core Concepts

### 5.1 Actor

An actor is any entity that can originate, propose, import, review, approve, reject, resolve, modify, execute, or be assigned responsibility.

Actor types:

```text
human
llm
system
importer
external_contact
team
role
service
unknown
```

Examples:

```text
local_operator
local_user
ollama:llama3.2:3b
codex
boh_system
bulk_importer
external_contact:example_reviewer
team:example_team
role:project_steward
```

### 5.2 Authority

Authority is the right to perform a class of action within a scope.

Authority is not the same as authorship.

Authority may be:

```text
global
project-scoped
document-scoped
collection-scoped
plane-scoped
lifecycle-scoped
time-limited
delegated
advisory-only
```

### 5.3 Responsibility

Responsibility is the accountable relationship between an actor and a project, document, decision, review, proposal, or unresolved state.

Responsibility can exist without authority.

Example:

```text
An LLM may propose a change but cannot be responsible for final canonical promotion.
A human may own a project but lack authority to resolve a clinical/legal/canonical decision.
An external contact may be a source, stakeholder, or reviewer without being an operator.
```

### 5.4 Authorship

Authorship tracks content origin.

Authorship should support:

```text
original_author
imported_by
created_by
modified_by
reviewed_by
approved_by
resolved_by
source_actor
proposed_by
```

### 5.5 Action Ledger

Every meaningful state-changing action should write an append-only ledger event.

The ledger should record:

```text
who/what acted
what action occurred
what target was affected
what authority was claimed or used
whether the action was allowed or denied
before/after state where feasible
timestamp
project scope
document scope
request/source context
```

---

## 6. Required Data Model

Implement using the existing BOH database/migration pattern.

### 6.1 actors

```sql
actors (
  actor_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  source TEXT,
  external_ref TEXT,
  email TEXT,
  notes TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)
```

Notes:

- `actor_id` must be stable.
- Do not require email.
- Do not require external accounts.
- `external_ref` can later store contact import IDs, GitHub usernames, model IDs, etc.

### 6.2 actor_aliases

```sql
actor_aliases (
  alias_id TEXT PRIMARY KEY,
  actor_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  source TEXT,
  created_at TEXT NOT NULL
)
```

Purpose: merge references like `Local User`, `example_username`, `local_operator`, or imported contact names without losing provenance.

### 6.3 actor_roles

```sql
actor_roles (
  role_id TEXT PRIMARY KEY,
  actor_id TEXT NOT NULL,
  role_name TEXT NOT NULL,
  scope_type TEXT NOT NULL,
  scope_id TEXT,
  starts_at TEXT,
  ends_at TEXT,
  granted_by TEXT,
  authority_basis TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
)
```

Example roles:

```text
project_steward
operator
reviewer
resolver
source_contact
clinical_authority
llm_advisor
importer
observer
```

### 6.4 authority_grants

```sql
authority_grants (
  grant_id TEXT PRIMARY KEY,
  actor_id TEXT NOT NULL,
  action TEXT NOT NULL,
  scope_type TEXT NOT NULL,
  scope_id TEXT,
  authority_level TEXT NOT NULL,
  constraints_json TEXT,
  granted_by TEXT,
  starts_at TEXT,
  ends_at TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
)
```

Example actions:

```text
import_document
edit_document
review_proposal
approve_proposal
reject_proposal
resolve_governance_state
promote_canonical
rollback_lifecycle
mutate_policy
execute_code
reset_workspace
seed_fixtures
```

### 6.5 responsibility_assignments

```sql
responsibility_assignments (
  assignment_id TEXT PRIMARY KEY,
  actor_id TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  responsibility_type TEXT NOT NULL,
  scope_type TEXT,
  scope_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  assigned_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)
```

Examples:

```text
project_owner
document_author
content_source
review_owner
resolution_owner
steward
stakeholder
external_reviewer
```

### 6.6 action_ledger

```sql
action_ledger (
  event_id TEXT PRIMARY KEY,
  actor_id TEXT,
  actor_type TEXT,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT,
  project_id TEXT,
  authority_basis TEXT,
  authority_result TEXT NOT NULL,
  before_json TEXT,
  after_json TEXT,
  request_id TEXT,
  source_route TEXT,
  source_tool TEXT,
  ip_hint TEXT,
  user_agent_hint TEXT,
  created_at TEXT NOT NULL
)
```

Allowed `authority_result` values:

```text
allowed
denied
proposed
approved
rejected
reverted
escalated
quarantined
system_recorded
```

The ledger must be append-only except for explicit test reset paths.

### 6.7 document_attribution

```sql
document_attribution (
  attribution_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  actor_id TEXT,
  attribution_type TEXT NOT NULL,
  confidence REAL,
  source TEXT,
  evidence_json TEXT,
  created_at TEXT NOT NULL
)
```

Attribution types:

```text
original_author
imported_by
created_by
modified_by
reviewed_by
approved_by
rejected_by
resolved_by
proposed_by
source_contact
```

### 6.8 contact_imports_optional

Do not require contact import in the first implementation, but create a clean extension point.

Optional future table:

```sql
contact_imports (
  import_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  summary_json TEXT,
  warnings_json TEXT
)
```

If a contact import feature exists or is easy to add, it must:

- require operator authorization
- never auto-grant authority
- import contacts as `external_contact` actors only
- allow manual role/authority assignment later
- preserve source and import timestamp

---

## 7. Default Seed Actors

On migration or first startup, ensure these actors exist:

```text
boh_system              type=system
local_operator          type=human
bulk_importer           type=importer
unknown_actor           type=unknown
codex                   type=llm
ollama_local            type=llm
```

Do not assume the user’s personal name unless already configured.

Allow later editing of display names.

---

## 8. API Requirements

Add actor/authority routes under an appropriate namespace, for example:

```text
GET    /api/actors
POST   /api/actors
GET    /api/actors/{actor_id}
PATCH  /api/actors/{actor_id}
GET    /api/actors/{actor_id}/ledger
GET    /api/authority/grants
POST   /api/authority/grants
PATCH  /api/authority/grants/{grant_id}
GET    /api/responsibility/assignments
POST   /api/responsibility/assignments
GET    /api/ledger/recent
GET    /api/docs/{doc_id}/attribution
POST   /api/docs/{doc_id}/attribution
```

Mutation routes must require operator authorization.

Read routes may remain local-read unless existing BOH policy says otherwise.

No route may expose secrets.

---

## 9. Integration Requirements

Patch existing mutation flows so they write ledger events.

At minimum:

```text
import/upload document
bulk import
index server path
edit document
generate review
approve/reject LLM proposal
governance approve/reject/resolve
certificate promote
lifecycle transition / rollback / undo
authority promotion / resolution
workspace reset / clean
seed fixtures
execution route
policy mutation
system edge mutation
lineage mutation
duplicate decision
```

For each event, resolve actor in this order:

```text
1. Explicit actor_id supplied by protected UI/action, if valid.
2. Actor selected in current local UI session, if available.
3. local_operator for operator-authorized human action.
4. specific LLM actor for model/tool proposals.
5. boh_system for internal system actions.
6. unknown_actor only as fallback.
```

Denied actions should also be logged when feasible.

---

## 10. UI Requirements

Add a lightweight “Actors / Authority” view or panel.

Minimum UI:

```text
Actors list
Actor detail
Roles / authority grants
Responsibility assignments
Recent action ledger
Document attribution panel
Project responsibility panel if project model exists
```

Add actor selector to protected local UI session:

```text
Current actor: local_operator
Change actor
```

Changing actor must not bypass operator auth.

UI must clearly show:

```text
Operator token = permission boundary
Current actor = attribution identity
Authority grant = why action is legitimate
```

For documents, show:

```text
Author / source
Imported by
Last modified by
Reviewed by
Approved by
Resolved by
Recent ledger events
```

---

## 11. Authority Evaluation

Do not overbuild policy logic in the first patch.

Minimum viable behavior:

- Keep existing operator-token gate for dangerous actions.
- Add actor/authority lookup for audit and warnings.
- If authority grant exists, record it as `authority_basis`.
- If no specific grant exists but operator auth permits action, record `authority_basis=operator_token_fallback`.
- For explicitly restricted actions, reject if actor lacks grant.

Restricted actions should include at least:

```text
promote_canonical
resolve_governance_state
mutate_policy
execute_code
reset_workspace
import_contacts
```

The goal is to start moving from coarse operator permission toward scoped legitimacy without breaking the local dev workflow.

---

## 12. Contact / External Entity Import

This is optional for the first build, but the schema should support it.

If implemented now:

- Add import route for a simple CSV or JSON contact list.
- Require operator auth.
- Create actors with `actor_type=external_contact`.
- Do not auto-grant permissions.
- Allow contacts to be assigned as source, stakeholder, reviewer, or project contact.
- Log the import in `action_ledger`.

CSV minimum fields:

```text
name,email,organization,role,notes
```

Mapping:

```text
name -> actors.display_name
email -> actors.email
organization/role/notes -> notes or metadata JSON
```

---

## 13. Tests

Add tests that use temp DB/library only.

### test_phase28_actor_registry.py

Cover:

- seed default actors
- create actor
- update actor
- alias creation
- actor list/read
- no secret exposure

### test_phase28_authority_grants.py

Cover:

- create grant requires operator auth
- grant is scope-aware
- expired/inactive grant ignored
- restricted action without grant is denied where implemented
- operator fallback is logged when allowed

### test_phase28_action_ledger.py

Cover:

- import writes ledger event
- review/approval writes ledger event
- denied protected action logs denied event if feasible
- reset/seed writes ledger event
- ledger is append-only outside test reset

### test_phase28_document_attribution.py

Cover:

- imported document gets imported_by attribution
- edited document gets modified_by attribution
- approved proposal gets approved_by attribution
- document attribution endpoint returns expected actor data

### test_phase28_contact_import_optional.py

Only if contact import is implemented.

Cover:

- contact import requires auth
- contacts become external_contact actors
- imported contacts receive no authority grants by default
- import is logged

---

## 14. Acceptance Criteria

Phase 28 is successful when:

```text
Actors exist as first-class entities.
Operator auth and actor identity are separate.
Protected actions can be attributed to an actor.
LLM proposals are attributed to LLM actors.
Human/operator decisions are attributed to human actors.
Documents expose authorship/import/review/approval/resolution attribution.
Projects or project-like scopes can assign responsibility.
Action ledger records meaningful mutation history.
Authority basis is recorded for protected actions.
Restricted actions begin checking scoped grants where feasible.
Clean/seed/reset events are logged.
Tests prove the above without using real user files.
```

---

## 15. Non-Goals

Do not implement cloud login.

Do not implement multi-user SaaS accounts.

Do not replace Phase 27 operator token security.

Do not import contacts automatically.

Do not grant authority from contacts automatically.

Do not let LLM actors approve, resolve, execute, or promote canonical state.

Do not weaken filesystem boundary, clean workspace, seed fixtures, or operator-auth workflow.

---

## 16. Implementation Order

Recommended order:

```text
1. Add DB migrations for actors, roles, authority_grants, responsibility_assignments, action_ledger, document_attribution.
2. Seed default actors.
3. Add core actor/ledger service layer.
4. Add operator-aware actor resolution helper.
5. Add actor/authority API routes.
6. Patch import/edit/review/approval/reset/seed flows to write ledger events.
7. Patch document attribution on import/edit/review/approval.
8. Add UI actor selector and Actors / Authority panel.
9. Add document attribution display.
10. Add tests.
11. Run full test suite.
12. Report remaining routes not yet ledger-integrated.
```

---

## 17. Final Report Required

When complete, report:

```text
Files changed
Migrations added
Tables added
Default actors seeded
Routes added
Protected routes changed
Ledger events integrated
Attribution events integrated
Authority checks implemented
UI changes
Tests added
Exact test commands
Test results
Known gaps
Routes not yet logging actor/action events
Future contact-import work, if deferred
```

Do not claim complete governance if some mutation routes still do not write ledger events. List gaps explicitly.
