import pytest

from app.tools.calc import CalcError, cagr, compute_financials, default_assumptions, market_sizing, safe_eval


def test_safe_eval_arithmetic_and_vars():
    assert safe_eval("(1+2)*3/2") == 4.5
    assert safe_eval("max(a, b) + round(2.6)", {"a": 1, "b": 5}) == 8


@pytest.mark.parametrize("expr", ["__import__('os').system('ls')", "a.b", "[1,2]", "open('x')", "lambda: 1"])
def test_safe_eval_rejects_code(expr):
    with pytest.raises(CalcError):
        safe_eval(expr, {"a": 1})


def test_financial_model_consistency():
    m = compute_financials(default_assumptions())
    r = m.rows
    assert len(r) == 5
    for row in r:
        assert row["revenue"] == pytest.approx(row["customers"] * row["arpu"], rel=1e-6)
        assert row["operating_income"] == pytest.approx(row["gross_profit"] - row["fixed_costs"] - row["acquisition_cost"], abs=1)
    assert r[-1]["cumulative_income"] == pytest.approx(sum(x["operating_income"] for x in r), abs=5)
    assert m.summary["ltv_cac_ratio"] == pytest.approx(1_200_000 * 0.7 / 0.2 / 400_000, rel=1e-3)


def test_market_sizing_and_cagr():
    assert market_sizing(1000, 0.3, 0.1) == {"TAM": 1000, "SAM": 300.0, "SOM": 30.0}
    assert cagr(100, 121, 2) == pytest.approx(0.1)
    with pytest.raises(CalcError):
        cagr(0, 1, 1)
