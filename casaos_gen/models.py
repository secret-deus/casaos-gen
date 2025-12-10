"""Pydantic data models shared across the CasaOS generator."""
from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field


class EnvItem(BaseModel):
    container: str
    description: str = ""


class PortItem(BaseModel):
    container: str
    description: str = ""


class VolumeItem(BaseModel):
    container: str
    description: str = ""


class ServiceMeta(BaseModel):
    envs: List[EnvItem] = Field(default_factory=list)
    ports: List[PortItem] = Field(default_factory=list)
    volumes: List[VolumeItem] = Field(default_factory=list)


class AppMeta(BaseModel):
    title: str = ""
    tagline: str = ""
    description: str = ""
    category: str
    author: str
    main: str
    port_map: str
    architectures: List[str] = Field(default_factory=lambda: ["amd64"])
    index: str = "/"
    scheme: str = "http"


class CasaOSMeta(BaseModel):
    app: AppMeta
    services: Dict[str, ServiceMeta] = Field(default_factory=dict)

    def to_json(self) -> str:
        """Return a compact JSON representation for debugging/export."""
        return self.model_dump_json(indent=2)

