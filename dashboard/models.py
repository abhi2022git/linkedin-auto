"""
Pydantic response models for the dashboard API.
"""

from pydantic import BaseModel
from typing import Optional, List


class PipelineRunRequest(BaseModel):
    dry_run: bool = False
    platform: str = "linkedin"
    model_override: Optional[str] = None


class SourceToggle(BaseModel):
    enabled: bool


class SourceCreate(BaseModel):
    name: str
    url: str
    source_type: str = "rss"
    category: str = "tech"
    platform: str = "linkedin"
