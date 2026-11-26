"""Registered workspace creation templates.

A template is the set of facts the engine sets when it creates a workspace.  The
registry is deliberately a checked-in module rather than a database table: a
template is executable engine behaviour, so a row that names a template the code
cannot apply would be a lie.

There is exactly one registered template today because there is exactly one
creation behaviour in the engine: an active, non-demo workspace with no papers,
classes, members or assignments preloaded.  ``Tenant`` has no other
creation-time settings to vary, and inventing a ``classroom`` or ``demo`` profile
would claim product behaviour that does not exist.  Adding a template here is how
the platform setting becomes a real choice; until then the setting is validated
against this registry and every new workspace records which entry created it.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Recorded on ``tenants.workspace_template`` for every new workspace.
DEFAULT_WORKSPACE_TEMPLATE = "standard"


@dataclass(frozen=True, slots=True)
class WorkspaceTemplate:
    key: str
    label: str
    description: str
    #: Creation-time facts the engine can actually apply.
    is_active: bool
    is_demo: bool


WORKSPACE_TEMPLATES: dict[str, WorkspaceTemplate] = {
    "standard": WorkspaceTemplate(
        key="standard",
        label="Standard workspace",
        description=(
            "An active, non-demo workspace with no preloaded papers, classes or "
            "members. This is the engine's only creation behaviour."
        ),
        is_active=True,
        is_demo=False,
    ),
}


def get_workspace_template(key: str) -> WorkspaceTemplate | None:
    return WORKSPACE_TEMPLATES.get(key)


def template_options() -> list[dict[str, str]]:
    """The registry as the settings API presents it, in a stable order."""

    return [
        {"key": template.key, "label": template.label, "description": template.description}
        for template in WORKSPACE_TEMPLATES.values()
    ]
