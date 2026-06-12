# Explore Rubrix lifecycle as declarative governance primitive

BOH currently implements Rubrix imperatively as document lifecycle logic:

observe -> vessel -> constraint -> integrate -> release

This issue explores whether Rubrix should be represented as a declarative lifecycle grammar, either internally or as an interop bridge with DSL-oriented systems such as Agicore.

Goal:
Make lifecycle transitions explicit, testable, auditable, and portable.

Non-goals:
- Do not replace current BOH governance.
- Do not introduce Agicore as a dependency.
- Do not claim compiler-level guarantees until implemented.

Acceptance criteria:
- Rubrix states represented in a machine-readable lifecycle declaration.
- Allowed transitions explicit.
- Forbidden transitions testable.
- Authority requirements attached per transition.
- Audit events generated from lifecycle transition rules.
