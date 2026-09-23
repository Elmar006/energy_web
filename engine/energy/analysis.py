"""Counterfactual explanations using the same physical and budget model."""

from .contracts import PlanningInput
from .optimizer import SolveResult, solve


def explain_selected_sites(spec: PlanningInput, baseline: SolveResult, limit: int = 3) -> list[dict]:
    if baseline.status not in ("optimal", "feasible"):
        return []
    items = []
    for selection in baseline.selected[:limit]:
        site_id = selection["site_id"]
        if site_id in spec.locked_site_ids or any(s.id == site_id and s.existing_option_id for s in spec.sites):
            items.append({"site_id": site_id, "status": "fixed", "reason": "existing or locked asset"})
            continue
        alternative = spec.model_copy(deep=True)
        alternative.excluded_site_ids.append(site_id)
        result = solve(alternative)
        items.append({
            "site_id": site_id,
            "status": result.status,
            "lost_served_kwh": {
                scenario.id: round(baseline.served_kwh[scenario.id] - result.served_kwh[scenario.id], 4)
                for scenario in spec.scenarios
            } if result.status in ("optimal", "feasible") else None,
            "lost_npv_rub": {
                scenario.id: round(baseline.cashflow_rub[scenario.id] - result.cashflow_rub[scenario.id], 2)
                for scenario in spec.scenarios
            } if result.status in ("optimal", "feasible") else None,
            "replacement_sites": [x["site_id"] for x in result.selected] if result.status in ("optimal", "feasible") else [],
            "method": "re-optimization with the site excluded",
        })
    return items
