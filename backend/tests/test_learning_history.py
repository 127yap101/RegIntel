"""History page invariants prevent partial or ambiguous published-version lists."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from regintel.learning.models import GlossaryHistory, GlossaryHistoryItem


def page():
    identity = str(uuid4())
    return {
        "items": (
            GlossaryHistoryItem(
                glossary_version_id=identity, parent_glossary_version_id=None, definition_count=1
            ),
        ),
        "head_glossary_version_id": identity,
        "offset": 0,
        "limit": 20,
        "total": 1,
    }


def test_empty_and_complete_glossary_pages_have_explicit_head_membership():
    assert len(GlossaryHistory(**page()).items) == 1
    assert (
        GlossaryHistory(items=(), head_glossary_version_id=None, offset=0, limit=20, total=0).total
        == 0
    )


@pytest.mark.parametrize("change", ["missing_page", "headless", "empty_head", "duplicate"])
def test_invalid_history_cannot_be_serialized_as_a_complete_published_page(change):
    value = page()
    if change == "missing_page":
        value["items"] = ()
    elif change == "headless":
        value["head_glossary_version_id"] = None
    elif change == "empty_head":
        value["items"], value["total"] = (), 0
    else:
        value["items"] *= 2
        value["total"] = 2
    with pytest.raises(ValidationError):
        GlossaryHistory(**value)
