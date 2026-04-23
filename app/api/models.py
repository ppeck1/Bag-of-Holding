"""app/api/models.py: Pydantic request/response models for Bag of Holding v2.

Consolidated from inline BaseModel definitions in main.py (v0P).
"""

from typing import Optional
from pydantic import BaseModel


class IndexRequest(BaseModel):
    library_root: Optional[str] = None


class PlanarFactRequest(BaseModel):
    plane_path: str
    r: float
    d: int
    q: float
    c: float
    context_ref: Optional[str] = ""
    m: Optional[str] = None
    valid_until: Optional[int] = None
    subject_id: Optional[str] = None
