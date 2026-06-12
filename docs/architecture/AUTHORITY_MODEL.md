# Authority Model

This document summarizes detected authority boundaries.

## Human / Operator

Protected local mutations require `BOH_OPERATOR_TOKEN` sent as `X-BOH-Operator-Token`.

Actor identity is separate from authorization and is sent as `X-BOH-Actor-ID` for attribution.

## LLM / Model

Docs state the invariant: LLM proposes, human governs, system audits.

Ollama and LLM proposal flows are gated and routed through review surfaces. Do not treat model output as canonical authority.

## Retrieval Connector

Read-only retrieval uses `BOH_RETRIEVAL_TOKEN` and `X-BOH-Retrieval-Token`. External tools should not receive the operator token.

## Agent Development Authority

Coding agents must follow the repository's governed work-order contract (agent contract, active work order, and done gate — maintained in the private working repository). Agents may not expand scope or weaken runtime authority boundaries.
