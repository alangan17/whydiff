from pathlib import Path

PACKAGE = Path(__file__).parents[1]


def test_package_has_sql_only_public_macros() -> None:
    key_macro = (PACKAGE / "macros" / "compare_key_coverage.sql").read_text()
    measure_macro = (PACKAGE / "macros" / "compare_measures.sql").read_text()
    generic_test = (PACKAGE / "macros" / "generic_test.sql").read_text()
    helpers = (PACKAGE / "macros" / "helpers.sql").read_text()

    assert "macro compare_key_coverage" in key_macro
    assert "macro compare_measures" in measure_macro
    assert "test reconciliation" in generic_test
    assert "finding_code" in generic_test
    assert "is not distinct from" in helpers.lower()
    assert key_macro.index("then 'duplicate_key'") < key_macro.index("then 'right_only'")
    assert "python" not in (key_macro + measure_macro + generic_test).lower()
