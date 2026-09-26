"""Deterministic calculation engine. The LLM never finalises numbers — this module does."""
from __future__ import annotations

import ast
import math
import operator
from dataclasses import dataclass, field
from typing import Any

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos,
        ast.FloorDiv: operator.floordiv}
_FUNCS = {"round": round, "min": min, "max": max, "abs": abs, "sqrt": math.sqrt, "log": math.log, "exp": math.exp}


class CalcError(ValueError):
    pass


def safe_eval(expr: str, variables: dict[str, float] | None = None) -> float:
    """Evaluate an arithmetic expression without exec/eval."""
    variables = variables or {}

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in variables:
                return variables[node.id]
            raise CalcError(f"unknown variable {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise CalcError(f"unsupported expression element: {type(node).__name__}")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise CalcError(str(e)) from e
    return float(ev(tree))


@dataclass
class Assumption:
    key: str
    label: str
    value: float
    unit: str = ""
    kind: str = "ASSUMPTION"  # ASSUMPTION | USER INPUT | SOURCE | ESTIMATE
    source_id: int | None = None
    note: str = ""


@dataclass
class FinancialModel:
    assumptions: list[Assumption]
    years: int = 5
    rows: list[dict[str, float]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str) -> float:
        for a in self.assumptions:
            if a.key == key:
                return a.value
        raise KeyError(key)


def default_assumptions() -> list[Assumption]:
    """Clearly-labelled placeholder ASSUMPTIONS the user is expected to edit. Not facts."""
    return [
        Assumption("customers_y1", "1년차 유료 고객 수", 200, "명", note="사용자 검토 필요"),
        Assumption("customer_growth", "연간 고객 성장률", 0.6, "%"),
        Assumption("arpu", "고객당 연 매출(ARPU)", 1_200_000, "원"),
        Assumption("price_growth", "연간 가격 인상률", 0.03, "%"),
        Assumption("gross_margin", "매출총이익률", 0.7, "%"),
        Assumption("fixed_costs_y1", "1년차 고정비", 300_000_000, "원"),
        Assumption("fixed_cost_growth", "고정비 증가율", 0.25, "%"),
        Assumption("cac", "고객 획득 비용(CAC)", 400_000, "원"),
        Assumption("churn", "연간 이탈률", 0.2, "%"),
    ]


def compute_financials(assumptions: list[Assumption], years: int = 5) -> FinancialModel:
    m = FinancialModel(assumptions, years)
    g = m.get
    customers = g("customers_y1")
    arpu = g("arpu")
    fixed = g("fixed_costs_y1")
    cumulative = 0.0
    breakeven_year = None
    prev_customers = 0.0
    for y in range(1, years + 1):
        if y > 1:
            customers = customers * (1 + g("customer_growth"))
            arpu = arpu * (1 + g("price_growth"))
            fixed = fixed * (1 + g("fixed_cost_growth"))
        new_customers = max(customers - prev_customers * (1 - g("churn")), 0)
        revenue = customers * arpu
        gross = revenue * g("gross_margin")
        acquisition = new_customers * g("cac")
        op_income = gross - fixed - acquisition
        cumulative += op_income
        if breakeven_year is None and op_income >= 0:
            breakeven_year = y
        m.rows.append({"year": y, "customers": round(customers, 2), "new_customers": round(new_customers, 2),
                       "arpu": round(arpu, 2), "revenue": round(revenue, 2), "gross_profit": round(gross, 2),
                       "fixed_costs": round(fixed, 2), "acquisition_cost": round(acquisition, 2),
                       "operating_income": round(op_income, 2), "cumulative_income": round(cumulative, 2)})
        prev_customers = customers
    lifetime = 1 / g("churn") if g("churn") > 0 else float("inf")
    ltv = g("arpu") * g("gross_margin") * lifetime
    m.summary = {
        "breakeven_year": breakeven_year,
        "ltv": round(ltv, 2),
        "ltv_cac_ratio": round(ltv / g("cac"), 2) if g("cac") else None,
        "payback_months": round(g("cac") / (g("arpu") * g("gross_margin") / 12), 2) if g("arpu") else None,
        "year5_revenue": m.rows[-1]["revenue"],
    }
    return m


def market_sizing(tam: float, sam_share: float, som_share: float) -> dict[str, float]:
    sam = tam * sam_share
    return {"TAM": tam, "SAM": round(sam, 2), "SOM": round(sam * som_share, 2)}


def cagr(start: float, end: float, years: float) -> float:
    if start <= 0 or years <= 0:
        raise CalcError("CAGR requires positive start value and years")
    return (end / start) ** (1 / years) - 1
