"""Native amendment supports on actual sealed authored source; not real filing gold."""

from uuid import UUID

import pytest
from psycopg.types.json import Jsonb

from backend.tests.integration import test_numerical_context_storage as contexts
from backend.tests.integration.test_native_context_storage import native as native
from backend.tests.integration.test_native_context_storage import unsealed as unsealed
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.test_native_amendment_support import REFERENCE, STATEMENT, ordered_support
from backend.tests.test_numerical_context import Options, authored
from regintel.db.migrations import connect_database
from regintel.entities.repository import EntityRepository
from regintel.publication.support import native_word_index, support_text

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def amendment_context(monkeypatch):
    monkeypatch.setattr(
        contexts,
        "authored",
        lambda path: authored(
            path,
            Options(
                unit="(INR in million)",
                currency=(),
                amendment_reference=REFERENCE,
                amendment_statement=STATEMENT,
            ),
        ),
    )


def test_sql_and_python_inspect_the_same_complete_sealed_native_statement(native):
    sealed = EntityRepository(native.source.database).sealed_evidence_for_parse(
        native.result.artifact.id
    )
    index = native_word_index(sealed.artifact, sealed.evidence)
    value = ordered_support(index, STATEMENT)
    expected = support_text(
        value,
        sealed.artifact.filing_version_id,
        sealed.artifact.id,
        {item.id: item for item in sealed.evidence},
        index,
        statement=True,
    )
    assert expected == STATEMENT
    with connect_database(native.source.database) as connection:
        assert connection.execute(
            "SELECT regintel.publication_support_text(%s,%s,TRUE)",
            (Jsonb(value.model_dump(mode="json")), UUID(sealed.artifact.id)),
        ).fetchone() == (expected,)
    assert len(value.spans) > 3 and "quote" not in value.model_dump(mode="json")
