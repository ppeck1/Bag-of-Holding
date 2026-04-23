# Math Authority — Bag of Holding v2
**Authority source:** CANON Registry v3.7 + patch v2.19 (as specified in boh_codex_pack `docs/math_authority.md`)
**Purpose:** Single locked reference for every scoring formula, threshold, and mathematical constant in the system. No formula may be changed without a versioned, justified entry in the Change Log below.
**Status:** Authoritative. Implementation must match exactly.

---

## Preamble

This document defines the mathematical ontology of the Bag of Holding system. It covers:

1. **Canon Scoring** — How a document's canonicity is scored
2. **Ambiguity Threshold** — When canon collision is declared
3. **Search Composite Scoring** — How search results are ranked
4. **Planar Alignment Scoring** — How planar facts influence document alignment
5. **Planar Conflict Thresholds** — When a planar conflict is declared
6. **Semver Rank** — How version strings are converted to numeric rank
7. **Topic Boost** — Contextual multiplier for canon resolution queries

**Core constraint:** The system is deterministic. Given the same database state and the same input parameters, every formula must produce the same output every time. Stochastic or inference-based scoring is prohibited.

---

## 1. Canon Score

**Function:** `canon_score(doc: dict) → float`
**Module:** `app/core/canon.py`
**Locked since:** v0P patch v1.1

### Formula

```
canon_score(doc) =
    100  × [status == "canonical"]
  +  50  × [type == "canon"]
  +  30  × [source_type == "canon_folder" OR "/canon/" ∈ path]
  +  10  × semver_rank(version)
  +  0.000001 × updated_ts
  -  40  × [status == "archived"]
```

Where `[condition]` = 1 if true, 0 if false.

### Component Breakdown

| Component | Value | Condition | Notes |
|-----------|-------|-----------|-------|
| Canonical status bonus | +100 | `status == "canonical"` | Highest single discriminator |
| Canon type bonus | +50 | `type == "canon"` | Document declares itself canon |
| Canon folder bonus | +30 | `source_type == "canon_folder"` OR `"/canon/"` in `path` | Filesystem provenance |
| Version rank | +10 × rank | `version` parses successfully | Rewards newer semver |
| Recency tiebreaker | +0.000001 × `updated_ts` | Always applied | Unix epoch; sub-second tiebreaker |
| Archive penalty | -40 | `status == "archived"` | Can still win over un-scored docs |

### Properties

- **Minimum possible score:** −40 (archived, no other signals)
- **Maximum possible score:** ~180 + (10 × max_semver_rank) + recency tiebreaker
- **Normalization maximum for search:** 180.0 (hardcoded in search scoring — see §3)
- **No inference:** All inputs come directly from stored document fields. No text analysis.

### Invariants

- `status == "canonical"` AND `status == "archived"` cannot co-exist (Rubrix hard constraint prevents this at ingest)
- Score is stable: same doc row always produces same score
- Score is additive: components do not interact

---

## 2. Topic Boost (Canon Resolution Only)

**Function:** Applied inside `resolve_canon()`, not part of base `canon_score()`
**Module:** `app/core/canon.py`

### Formula

```
effective_score(doc, topic) = canon_score(doc) + topic_boost(doc, topic)

topic_boost(doc, topic) =
    20  × [normalize_topic_token(topic) ∈ doc.topics_tokens.split()]
```

### Notes

- Topic boost is **only applied when `topic` parameter is present** in a `resolve_canon()` call
- It is not part of the base `canon_score()` used elsewhere (e.g., in search normalization)
- `normalize_topic_token()` — lowercase + strip + collapse internal whitespace — must be applied to both the query topic and each stored token before comparison
- The comparison is membership in the space-delimited `topics_tokens` string: `normalized_topic in topics_tokens.split()`

---

## 3. Canon Ambiguity Threshold

**Constant:** `AMBIGUITY_THRESHOLD = 0.05` (5%)
**Module:** `app/core/canon.py`

### Formula

```
collision_declared = (
    len(candidates) >= 2
    AND top_score > 0
    AND abs(top_score - second_score) / top_score <= 0.05
)
```

### Behavior

- When collision is declared: a `canon_collision` conflict is created in the `conflicts` table
- The winner is still returned (highest score); collision is advisory
- **No auto-resolution.** User must explicitly adjudicate.

---

## 4. Search Composite Score

**Function:** `search(query, ...) → List[scored_result]`
**Module:** `app/core/search.py`
**Formula locked since:** v0P

### Formula

```
final_score =
    0.6 × text_score
  + 0.2 × canon_score_normalized
  + 0.2 × planar_alignment_score
  + conflict_penalty
```

### Component Definitions

#### 4a. Text Score
```
bm25_scores = [bm25(doc) for doc in fts_results]  # SQLite BM25: lower = better
min_bm25 = min(bm25_scores)
max_bm25 = max(bm25_scores)
bm25_range = max_bm25 - min_bm25  if max_bm25 != min_bm25  else 1

text_score(doc) = clamp(1.0 - (bm25(doc) - min_bm25) / bm25_range, 0.0, 1.0)
```

#### 4b. Canon Score Normalized
```
CANON_NORM_MAX = 180.0

canon_score_normalized(doc) = clamp(canon_score(doc) / CANON_NORM_MAX, 0.0, 1.0)
```

**Note:** `CANON_NORM_MAX = 180.0` is the practical ceiling for `canon_score()` (100 + 50 + 30 = 180 before semver/recency). If future canon score components push past 180, `CANON_NORM_MAX` must be updated here and in implementation simultaneously.

#### 4c. Planar Alignment Score
See §5 below.

#### 4d. Conflict Penalty
```
CONFLICT_PENALTY = -0.1

conflict_penalty(doc) = CONFLICT_PENALTY  if doc.doc_id ∈ any_conflict.doc_ids  else 0.0
```

### Weights Summary

| Component | Weight | Range after weight |
|-----------|--------|-------------------|
| `text_score` | 0.6 | [0.0, 0.6] |
| `canon_score_normalized` | 0.2 | [0.0, 0.2] |
| `planar_alignment_score` | 0.2 | [0.0, 0.2] |
| `conflict_penalty` | fixed | {0.0, −0.1} |

**Theoretical range of `final_score`:** [−0.1, 1.0]

### Invariants

- Weights sum to 1.0 (excluding conflict penalty, which is a fixed additive term)
- All three main components are normalized to [0, 1] before weighting
- `score_breakdown` dict must be returned with every result (explainability requirement)

---

## 5. Planar Alignment Score

**Function:** `planar_alignment_score(plane_scopes, query_plane) → float`
**Module:** `app/core/planar.py`

### Formula

```
active_facts = [f for f in plane_facts
                if f.plane_path ∈ (plane_scopes ∪ {query_plane})
                AND (f.valid_until IS NULL OR f.valid_until > now)]

if not active_facts:
    return 0.5  # neutral default

weight(f)    = f.q × f.c
direction(f) = (f.d + 1) / 2.0   # maps: -1→0.0, 0→0.5, +1→1.0

weighted_score = Σ weight(f) × direction(f)
total_weight   = Σ weight(f)

planar_alignment_score = min(1.0, weighted_score / total_weight)
```

### Constants and Ranges

| Symbol | Meaning | Range |
|--------|---------|-------|
| `q` | Qualification — how well-qualified the fact source is | [0, 1] |
| `c` | Confidence — confidence in the fact's accuracy | [0, 1] |
| `d` | Direction — alignment direction | {−1, 0, +1} |
| `weight(f)` | Combined credibility weight | [0, 1] |
| `direction(f)` | Normalized direction | {0.0, 0.5, 1.0} |
| Score (no facts) | Neutral | 0.5 |
| Score range | | [0.0, 1.0] |

### Notes

- Empty `plane_scopes` → return `0.0` immediately (doc has no planar context)
- If `query_plane` is given and not already in `plane_scopes`, it is appended to the lookup set
- Only non-expired facts considered

---

## 6. Planar Conflict Thresholds

**Module:** `app/core/conflicts.py`
**Patch:** v1.1 C1

### Conditions for Planar Conflict

```
window_cutoff = now - 86400  # 24 hours in seconds

conflict_triggered =
    (COUNT(DISTINCT d) > 1 for facts in [window_cutoff, now])
    AND (∃ fact with (q + c) > 0.7)
```

### Constants

| Constant | Value | Meaning |
|----------|-------|---------|
| Window duration | 86400 seconds | 24 hours |
| High-confidence threshold | 0.7 | `q + c` must exceed this for conflict to matter |

### Note

The `(q + c) > 0.7` check applies across all facts in the group — at least one fact must exceed the threshold. It is not required that the *conflicting* facts individually exceed it; the group triggers if any member does.

---

## 7. Semver Rank

**Function:** `parse_semver(version: str | None) → int`
**Module:** `app/services/parser.py`

### Formula

```
parse_semver(version) =
    if version is None or unparseable: return 0
    parts = version.lstrip("v").split(".")
    major, minor, patch = parts padded to length 3 with "0"
    return major × 1_000_000 + minor × 1_000 + patch
```

### Examples

| Input | Output |
|-------|--------|
| `"1.0.0"` | 1,000,000 |
| `"v2.3.1"` | 2,003,001 |
| `"0.1.0"` | 1,000 |
| `None` | 0 |
| `"invalid"` | 0 |

---

## 8. Definition Conflict Logic

**Module:** `app/core/conflicts.py`

### Condition

```
definition_conflict =
    GROUP BY (term, plane_scope_json)
    HAVING COUNT(DISTINCT block_hash) > 1
```

No threshold or math — purely structural. Same term, same scope, different content hash = conflict.

---

## 9. Canon Collision Logic (B2)

**Module:** `app/core/conflicts.py`

### Condition

```
canon_collision(doc_a, doc_b) =
    doc_a.status == "canonical"
    AND doc_b.status == "canonical"
    AND shared_topic_tokens(doc_a, doc_b) ≠ ∅
    AND (
        (scope(doc_a) = ∅ AND scope(doc_b) = ∅)   # both global
        OR scope(doc_a) ∩ scope(doc_b) ≠ ∅         # overlapping scopes
    )
```

Where `shared_topic_tokens` = intersection of normalized, space-split `topics_tokens` sets.

---

## 10. Ontology Separation Requirement

**From codex:** `docs/math_authority.md` — "Do not collapse old and new math into one unmarked ontology."

The following math ontologies are **distinct and must remain labeled separately**:

| Ontology | Current Label | Location | Notes |
|----------|-------------|----------|-------|
| Canon Registry v3.7 | `BOH_CANON_v3.7` | `app/core/canon.py` docstring | All scoring formulas in §1–§3 above |
| Patch v2.19 | `BOH_PATCH_v2.19` | `app/core/conflicts.py` docstring | B2 canon collision fix, C1 planar window fix |
| Rubrix Lifecycle | `RUBRIX_LIFECYCLE_v1` | `app/core/rubrix.py` docstring | State machine in §3 of behavior inventory |

If future math versions are introduced (e.g., a new scoring model for v3), they must be introduced as a **new labeled ontology**, not silently merged with existing formulas. The change log below must be updated.

---

## Change Log

| Version | Date | Change | Justification | Impact |
|---------|------|--------|---------------|--------|
| v0P initial | — | Canon score formula established | Base scoring | §1 |
| Patch v1.1 A1.4 | 2026-02 | Topic boost (+20) added to `resolve_canon()` | Improve topic-query relevance | §2 |
| Patch v1.1 B2 | 2026-02 | Canon collision requires shared topic tokens AND scope overlap | Prevent false-positive collisions | §9 |
| Patch v1.1 C1 | 2026-02 | Planar conflict window fixed to 24h (was unbounded) | Only recent facts should conflict | §6 |
| **v2 migration** | 2026-04 | No formula changes — structural restructure only | UX refactor | None |

---

## Implementation Verification

Every formula in this document must be verifiable by the test suite. The following test assertions are required:

| Formula | Test | Assertion |
|---------|------|-----------|
| `canon_score()` | `test_canon_selection.py` | Known doc row produces known score |
| Topic boost | `test_canon_selection.py` | With topic: score + 20 vs without |
| Ambiguity threshold | `test_canon_selection.py` | Two docs at 4% diff → collision; 6% diff → no collision |
| `final_score` weights | `test_search.py` | Mocked components produce `0.6a + 0.2b + 0.2c + penalty` |
| `planar_alignment_score` | `test_planar.py` | d=+1, q=1, c=1 → score 1.0; d=-1 → 0.0; no facts → 0.5 |
| Planar conflict window | `test_conflict_detection.py` | Old facts (>24h) → no conflict; recent → conflict |
| `parse_semver()` | `test_integration.py` | Table of inputs → expected outputs |
