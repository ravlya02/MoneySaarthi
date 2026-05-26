"""Plotly figure builders (§D.1). Build the figure server-side, serialize with
pio.to_json, hydrate client-side with Plotly.newPlot. No iframes, no static PNGs.
Serialized JSON is cached in investment_plans.plan_detail."""

import plotly.graph_objects as go
import plotly.io as pio

from app.models.reports import Allocation, TaxResult


def build_allocation_fig(alloc: Allocation) -> str:
    fig = go.Figure(data=[go.Pie(
        labels=["Equity", "Debt", "Real Estate", "Metals", "Cash"],
        values=[float(alloc.equity), float(alloc.debt), float(alloc.realestate), float(alloc.metals), float(alloc.cash)],
        hole=0.45,
    )])
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=True)
    return pio.to_json(fig)


def build_tax_breakdown_fig(tax: TaxResult) -> str:
    fig = go.Figure(data=[go.Bar(
        x=["Old regime", "New regime"],
        y=[float(tax.old_regime_tax), float(tax.new_regime_tax)],
    )])
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10))
    return pio.to_json(fig)
