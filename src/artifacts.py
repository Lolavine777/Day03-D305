"""Project structured tool observations into stable UI artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProjectedArtifacts:
    """Optional artifact updates produced by one tool observation."""

    properties: list[dict[str, Any]] | None = None
    slots: list[dict[str, Any]] | None = None
    booking: dict[str, Any] | None = None


def project_tool_artifacts(
    tool_name: str,
    observation: dict[str, Any],
) -> ProjectedArtifacts:
    """Extract typed UI artifacts without coupling the agent loop to tool payloads."""

    data = observation.get("data")
    if not isinstance(data, dict):
        data = {}
    if observation.get("ok") is not True:
        return ProjectedArtifacts()

    if tool_name in {"search_properties", "compare_properties"}:
        properties = data.get("properties") or data.get("items") or []
        return ProjectedArtifacts(
            properties=properties if isinstance(properties, list) else []
        )

    if tool_name == "get_property_details":
        property_item = data.get("property") or data
        return ProjectedArtifacts(
            properties=(
                [property_item]
                if isinstance(property_item, dict) and property_item
                else []
            )
        )

    if tool_name == "get_available_viewing_slots":
        slots = data.get("slots") or data.get("items") or []
        return ProjectedArtifacts(slots=slots if isinstance(slots, list) else [])

    if tool_name == "book_viewing" and observation.get("ok") is True:
        booking = data.get("booking") or data
        return ProjectedArtifacts(
            booking=booking if isinstance(booking, dict) and booking else None
        )

    return ProjectedArtifacts()


__all__ = ["ProjectedArtifacts", "project_tool_artifacts"]
