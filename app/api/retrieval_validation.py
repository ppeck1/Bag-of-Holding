"""Explicit request fields for answer-oriented retrieval scope."""
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.core.retrieval import FILTER_KEYS


class RetrievalFilterFields(BaseModel):
    model_config = ConfigDict(extra='forbid')
    doc_id: str | None = None
    status: str | None = None
    authority_state: str | None = None
    canonical_layer: str | None = None
    project: str | None = None
    chunk_type: str | None = None
    library_id: str | None = None

    def retrieval_filters(self) -> dict[str, str]:
        return {key:getattr(self,key) for key in FILTER_KEYS if getattr(self,key) is not None}


def require_query_fields(request: Request, allowed: set[str]) -> None:
    if set(request.query_params) - allowed:
        raise HTTPException(status_code=422, detail='unsupported retrieval query parameter')
    if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise HTTPException(status_code=422, detail='duplicate retrieval query parameter')
