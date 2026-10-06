"""Insert ordering breaks only real FK cycles, and only at nullable columns (DESIGN §6.1)."""

import pytest
from sqlalchemy import Column, ForeignKey, MetaData, Table, Text

from cam_testdata import db
from cam_testdata.build import BuildError, _insert_order


def test_model_defers_only_study_do_id() -> None:
    order, cyclic = _insert_order(db.registry_tables())
    names = [t.name for t in order]
    assert cyclic == {"Study": ["do_id"]}
    assert names.index("AccessPolicy") < names.index("Study") < names.index("DOI")
    assert (
        names.index("Subject")
        < names.index("Encounter")
        < names.index("BiospecimenCollection")
    )


def test_cycle_through_not_null_columns_is_an_error() -> None:
    md = MetaData()
    a = Table(
        "A",
        md,
        Column("id", Text, primary_key=True),
        Column("b_id", Text, ForeignKey("B.id"), nullable=False),
    )
    b = Table(
        "B",
        md,
        Column("id", Text, primary_key=True),
        Column("a_id", Text, ForeignKey("A.id"), nullable=False),
    )
    with pytest.raises(BuildError, match="no nullable column"):
        _insert_order([a, b])


def test_unrelated_not_null_fks_are_never_deferred() -> None:
    md = MetaData()
    p = Table("P", md, Column("id", Text, primary_key=True))
    a = Table(
        "A",
        md,
        Column("id", Text, primary_key=True),
        Column("p_id", Text, ForeignKey("P.id"), nullable=False),
        Column("b_id", Text, ForeignKey("B.id"), nullable=True),
    )
    b = Table(
        "B",
        md,
        Column("id", Text, primary_key=True),
        Column("p_id", Text, ForeignKey("P.id"), nullable=False),
        Column("a_id", Text, ForeignKey("A.id"), nullable=False),
    )
    order, cyclic = _insert_order([p, a, b])
    assert cyclic == {"A": ["b_id"]}
    assert [t.name for t in order] == ["P", "A", "B"]
