"""Backwards-compatible shim: unified settings live in core.config."""
from core.config import Settings, config

__all__ = ["Settings", "config"]
