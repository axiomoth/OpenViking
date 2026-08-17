"""Shared target resolution for user-supplied content destinations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from openviking_cli.exceptions import InvalidArgumentError


@dataclass(frozen=True)
class ContentTargetSpec:
    """Canonical content destination fields for resource and skill writes."""

    to: str = ""
    parent: str = ""
    create_parent: bool = False

    @classmethod
    def from_fields(
        cls,
        *,
        to: Optional[str] = None,
        parent: Optional[str] = None,
        create_parent: bool = False,
    ) -> "ContentTargetSpec":
        if (to or "").strip() and (parent or "").strip():
            raise InvalidArgumentError("Cannot specify both 'to' and 'parent' at the same time.")
        return cls(
            to=to or "",
            parent=parent or "",
            create_parent=create_parent,
        )
