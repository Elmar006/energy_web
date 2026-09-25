"""Expose what the inputs and independent operational runs actually support."""
from __future__ import annotations

from collections import defaultdict
from statistics import mean

from .contracts import PlanningInput
from .optimizer import SolveResult


def describe_input_quality(spec: PlanningInput) -> dict:
    observed = [zone.id for zone in spec.zones if zone.arrival_profile is not None
                and zone.arrival_profile.source_kind == "observed"]
    assumed = [zone.id for zone in spec.zones if zone.arrival_profile is not None
               and zone.arrival_profile.source_kind == "assumed"]
    parametric = [zone.id for zone in spec.zones if zone.arrival_profile is None]
    mobility_zones = [zone.id for zone in spec.zones
                      if zone.provenance.source.startswith("mobility-v1:")]
    mobility_sources = [{"sha256": dataset.sha256, "source_kind": dataset.source_kind}
                        for dataset in spec.datasets if dataset.transform_version == "mobility-v1"]
    warnings = []
    if observed:
        warnings.append("Observed charging sessions describe fulfilled charging only; latent unmet demand is unknown.")
        warnings.append("The 'observed' source label is supplied by the importer and has not been independently verified.")
    unverified_coverage = [zone.id for zone in spec.zones if zone.arrival_profile is not None
                           and not zone.arrival_profile.coverage_complete]
    claimed_coverage = [zone.id for zone in spec.zones if zone.arrival_profile is not None
                        and zone.arrival_profile.coverage_complete]
    if unverified_coverage:
        warnings.append("Session export day-by-day completeness is unverified for some zones; days without records are rejected unless full coverage is explicitly asserted.")
    if claimed_coverage:
        warnings.append("Complete day-by-day session coverage was asserted by the importer, not independently verified.")
    if any(zone.arrival_profile is not None and
           zone.arrival_profile.hourly_load_method == "uniform_session_duration"
           for zone in spec.zones):
        warnings.append("Hourly charging load was apportioned uniformly across each session duration; interval meter readings were not supplied.")
    if assumed:
        warnings.append("Some session profiles are declared assumed; their apparent precision does not imply measurement.")
    if parametric:
        warnings.append("Zones without session profiles infer arrivals from hourly energy and assumed mean session size.")
    if mobility_zones:
        if spec.service_calendar is not None:
            warnings.append("Dated mobility requests represent potential public charging from supplied trips and parking windows; no population representativeness or external calibration is established.")
            warnings.append("Calendar annualization repeats the supplied dated horizon by an explicit scenario factor; it is not a measured annual demand or locally validated NPV.")
            if spec.service_calendar.legacy_profile_zone_ids:
                warnings.append("Some zones use an explicitly declared representative 24-hour profile alongside dated requests; those zones are scenario assumptions, not dated observations.")
        else:
            warnings.append("Mobility-derived zones represent potential public charging from supplied trips; legacy day profiles are averaged and simulation re-samples arrivals rather than replaying the requests.")
        if any(source["source_kind"] == "observed" for source in mobility_sources):
            warnings.append("Observed mobility source labels are supplied by the importer and have not been independently verified.")
    if any(zone.arrival_profile is not None and
           (zone.arrival_profile.observation_days < 7 or zone.arrival_profile.sample_count < 30)
           for zone in spec.zones):
        warnings.append("At least one session profile has fewer than 7 days or 30 sessions; its temporal and energy distributions are weakly estimated.")
    if any(node.provenance.kind != "observed" for node in spec.grid_nodes):
        warnings.append("At least one grid headroom profile is not labeled observed; connection feasibility remains scenario-based.")
    return {
        "observed_session_zone_ids": observed,
        "assumed_session_zone_ids": assumed,
        "parametric_zone_ids": parametric,
        "mobility_derived_zone_ids": mobility_zones,
        "mobility_sources": mobility_sources,
        "temporal_demand_mode": "dated_requests" if spec.service_calendar is not None else "representative_24h",
        "dated_covered_days": (len(spec.service_calendar.covered_dates)
                               if spec.service_calendar is not None else None),
        "unverified_coverage_zone_ids": unverified_coverage,
        "claimed_complete_coverage_zone_ids": claimed_coverage,
        "demand_scope": ("mobility_potential" if len(mobility_zones) == len(spec.zones) else
                         "served_sessions_only" if len(observed) == len(spec.zones) else
                         "assumed_session_profiles" if len(assumed) == len(spec.zones) else
                         "mixed" if observed or assumed or mobility_zones else "scenario_assumptions"),
        "warnings": warnings,
    }


def compare_operations(result: SolveResult, simulations: list[dict]) -> list[dict]:
    """Compare service fractions, since sampled arrivals need not equal hourly MILP demand."""
    by_period: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for run in simulations:
        by_period[(run["scenario_id"], run["year"])].append(run)
    rows = []
    for optimized in result.service_by_year:
        key = (optimized["scenario_id"], optimized["year"])
        runs = by_period[key]
        if not runs:
            continue
        optimization_fraction = (optimized["served_kwh"] / optimized["demand_kwh"]
                                 if optimized["demand_kwh"] > 0 else 1.0)
        fractions = [run["energy_kwh"] / run["requested_energy_kwh"]
                     if run["requested_energy_kwh"] > 0 else 1.0 for run in runs]
        simulated_fraction = mean(fractions)
        rows.append({
            "scenario_id": key[0], "year": key[1], "seeds": len(runs),
            "optimized_service_fraction": round(optimization_fraction, 6),
            "simulated_service_fraction_mean": round(simulated_fraction, 6),
            "simulated_service_fraction_min": round(min(fractions), 6),
            "simulated_service_fraction_max": round(max(fractions), 6),
            "service_gap_percentage_points": round(100 * (optimization_fraction - simulated_fraction), 3),
            "simulation_days": runs[0].get("simulation_days", 1),
            "requested_energy_kwh_mean": round(mean(run["requested_energy_kwh"] /
                                                     run.get("simulation_days", 1) for run in runs), 3),
            "delivered_energy_kwh_mean": round(mean(run["energy_kwh"] /
                                                     run.get("simulation_days", 1) for run in runs), 3),
            "unserved_energy_kwh_mean": round(mean(run["unserved_energy_kwh"] /
                                                    run.get("simulation_days", 1) for run in runs), 3),
        })
    return rows


def compare_economics(spec: PlanningInput, result: SolveResult, simulations: list[dict]) -> list[dict]:
    """Reprice simulated energy flows using the same nominal assumptions as the MILP.

    The estimate extrapolates a representative day or an explicitly weighted
    dated horizon. It captures queues and causal grid/battery use, not a
    measured annual cash flow or independently validated local NPV.
    """
    by_scenario_seed: dict[tuple[str, int], dict[int, dict]] = defaultdict(dict)
    for run in simulations:
        key = (run["scenario_id"], run["seed"])
        if run["year"] in by_scenario_seed[key]:
            raise ValueError("duplicate simulation for scenario, seed and year")
        by_scenario_seed[key][run["year"]] = run
    options = {option.id: option for option in spec.options}
    investments = {row["year"]: row["rub"] for row in result.investment_rub_by_year}
    par = spec.parameters
    rows = []
    for scenario in spec.scenarios:
        npvs = []
        for (scenario_id, _seed), yearly in sorted(by_scenario_seed.items()):
            if scenario_id != scenario.id:
                continue
            if set(yearly) != set(par.years):
                raise ValueError("simulated economics requires every planning year for each seed")
            npv = 0.0
            for period, year in enumerate(par.years):
                run = yearly[year]
                fixed = sum(options[item["option_id"]].annual_fixed_rub
                            for item in result.selected if item["year"] <= year)
                grid = sum(site["grid_kwh"] for site in run["dispatch_by_site"])
                discharged = sum(site["battery_discharge_kwh"] for site in run["dispatch_by_site"])
                annualizer = (spec.service_calendar.annualization_factor
                              if spec.service_calendar is not None
                              else 365 / run.get("simulation_days", 1))
                annual = annualizer * (
                    run["energy_kwh"] * par.sale_rub_per_kwh * scenario.tariff_multiplier
                    - grid * par.purchase_rub_per_kwh
                    - discharged * par.storage_degradation_rub_per_kwh
                ) - fixed - investments.get(year, 0)
                npv += annual / ((1 + par.discount_rate) ** period)
            npvs.append(npv)
        if not npvs:
            continue
        optimized = result.cashflow_rub[scenario.id]
        simulated = mean(npvs)
        rows.append({
            "scenario_id": scenario.id, "seeds": len(npvs),
            "annualization_basis": ("assumed_repeat_dated_horizon"
                                     if spec.service_calendar is not None
                                     else "assumed_repeat_representative_day"),
            "annualization_factor": (spec.service_calendar.annualization_factor
                                     if spec.service_calendar is not None else None),
            "optimized_npv_rub": round(optimized, 2),
            "simulated_npv_rub_mean": round(simulated, 2),
            "simulated_npv_rub_min": round(min(npvs), 2),
            "simulated_npv_rub_max": round(max(npvs), 2),
            "optimism_gap_rub": round(optimized - simulated, 2),
            "profitability_sign_changed": (optimized > 0 > simulated or optimized < 0 < simulated),
        })
    return rows
