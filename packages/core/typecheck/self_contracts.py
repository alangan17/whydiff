"""Static regression checks for public subtype-preserving APIs."""

from typing_extensions import assert_type
from whydiff.adapters import DuckDBAdapter
from whydiff.engine import WhyDiff


class SpecializedDuckDBAdapter(DuckDBAdapter):
    """Concrete subtype used to verify the adapter context-manager contract."""


class SpecializedWhyDiff(WhyDiff):
    """Concrete subtype used to verify facade factory and context-manager contracts."""


def verify_self_contracts() -> None:
    """Fail static analysis if a public ``Self`` return widens to its base class."""
    adapter = SpecializedDuckDBAdapter()
    assert_type(adapter.__enter__(), SpecializedDuckDBAdapter)

    engine = SpecializedWhyDiff.duckdb()
    assert_type(engine, SpecializedWhyDiff)
    assert_type(engine.__enter__(), SpecializedWhyDiff)
