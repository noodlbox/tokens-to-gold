"""Which reports may be published as what an agent receives (LEDGER B64).

Two arm kinds exist, and only one of them describes a delivered response:

* `DELIVERED` -- the product arm (`ttg.delivered_report`): the exact bytes the
  shipped `nbx` emits, priced and scored as delivered.
* `RANKED_LIST_CEILING` -- every noodl-eval arm: the engine's untrimmed ranked
  list priced in the engine, a RETRIEVAL CEILING, never delivered.

A report is DELIVERED only when it says so itself (`arm_kind = "delivered"`
and `publishable_as_delivered = true`); an engine report carries neither, so it
is a ceiling by construction. Every headline / delivered renderer calls
`require_delivered` first.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum


class ArmKind(str, Enum):
    DELIVERED = "delivered"
    RANKED_LIST_CEILING = "ranked_list_ceiling"


CEILING_LABEL = "retrieval ceiling, not delivered"


class CeilingNotPublishable(ValueError):
    """A ranked-list ceiling report was offered as a delivered / headline number."""


def arm_kind(report: Mapping[str, object]) -> ArmKind:
    return ArmKind.DELIVERED if report.get("arm_kind") == ArmKind.DELIVERED.value else ArmKind.RANKED_LIST_CEILING


def publishable_as_delivered(report: Mapping[str, object]) -> bool:
    return arm_kind(report) is ArmKind.DELIVERED and report.get("publishable_as_delivered") is True


def require_delivered(report: Mapping[str, object]) -> None:
    if not publishable_as_delivered(report):
        raise CeilingNotPublishable(
            f"report arm {report.get('arm')!r} is a {ArmKind.RANKED_LIST_CEILING.value} "
            f"({CEILING_LABEL}); it is never a headline or a delivered number"
        )
