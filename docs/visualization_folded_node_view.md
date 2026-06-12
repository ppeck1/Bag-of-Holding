# Folded Node Visualization Direction

Status: first read-only packet endpoint and reader-pane UI prototype implemented.

The current Atlas views are useful for topology, but they feel flat because each document is reduced to a node plus color, size, and a side reader. BOH now has more internal state than a flat graph can honestly carry: lifecycle, authority, provenance, conflicts, PlaneCards, chunks, retrieval gate posture, and audit events.

## Proposal

Treat a graph node as a folded information packet.

Collapsed node:
- title
- highest-risk state
- lifecycle state
- authority state
- conflict/review indicator
- compact facet stripe

Expanded node:
- source facet: relative path, source hash, imported/generated status
- lifecycle facet: observe/vessel/constraint/integrate/release state and history count
- authority facet: actor, grants, certificate requirement, canonical/trusted status
- provenance facet: lineage, supersession, source references
- conflict facet: open conflict count and required route
- retrieval facet: chunk count, top matching chunks, `do_not_treat_as_canonical`
- PlaneCard facet: plane, card type, b/d/m, validity, source ref
- Planar Gate facet: posture, withheld refs, required route, warning/blocking reasons
- audit facet: latest mutation or storage event

## Interaction

- Single click: select node and open the existing reader.
- Shift-click or explicit Expand: unfold the node packet in place.
- Double-click: expand graph neighborhood.
- Collapse: return to the topology-only view.
- Pin: keep an unfolded packet visible while navigating.

## Why This Is Better

The canvas should answer: what is connected?

The fold should answer: what is inside this knowledge object?

The reader should answer: what does the source say?

Keeping those roles separate avoids turning the whole graph into a dense label field while still making BOH's governance state visible where the user is already looking.

## Data Needed

Most fields already exist, but they are spread across endpoints:
- `/api/graph`
- `/api/projection`
- `/api/docs/{id}/content`
- `/api/planes/cards`
- `/api/retrieve`
- activity/audit/status endpoints

Implemented compact endpoint:

```text
GET /api/docs/{doc_id}/fold
```

It returns a single folded-node packet:

```json
{
  "doc_id": "...",
  "title": "...",
  "summary": {},
  "facets": {
    "source": {},
    "lifecycle": {},
    "authority": {},
    "provenance": {},
    "conflicts": {},
    "retrieval": {},
    "plane_card": {},
    "planar_gate": {},
    "audit": {}
  }
}
```

## Non-Goals

- Do not make the graph more decorative without improving interpretability.
- Do not hide authority or conflict state behind animation.
- Do not let expanded visual state imply canonical approval.
- Do not require LLM output to render the fold.

## Current Prototype Limits

- The fold renders above the document reader after node selection.
- It is not yet an in-canvas expanding node.
- It is read-only and should not create PlaneCards, audit events, or storage events.
- The demo seed creates one anchor node with meaningful facets so the prototype can be inspected immediately.
