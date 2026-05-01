# BOH Visualization Test Project — Fabricated Seed Corpus

This project is fully synthetic. It contains no real clinical, business, personal, or operational data.

Purpose: provide a controlled BOH project for testing visualization rendering.

## Included test coverage

- Web relationship graph
- Variable overlay
- Constraint / viability geometry
- Constitutional / custodian lane topology
- Daenary q/c/d/m rendering
- Conflict, quarantine/archive, raw import, review, approved, and canonical states
- Suggested vs approved cross-project edges
- Expired `valid_until` states
- High-cost ambiguous nodes

## Use

Run the app from this folder using the normal launcher. The included `boh.db` is pre-seeded.

If you rebuild or delete the database, run:

```bash
python seed_visualization_demo.py
```

Then open the Atlas / visualization route and switch modes.

## Expected visual behavior

- Web mode should show four project clusters.
- Variable mode should spread epistemic nodes by confidence and quality.
- Constraint mode should place high-cost ambiguous nodes in containment / low-quality zones.
- Constitutional mode should populate raw_imported, expired, canceled, contained, under_review, approved, canonical, and archived lanes.

The corpus is intentionally exaggerated so broken visual behavior is easier to detect.
