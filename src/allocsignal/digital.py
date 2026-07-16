"""Digital campaign unit economics and non-causal attribution audit."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .errors import DataProblem


@dataclass(frozen=True)
class DigitalRoles:
    label: str
    impressions: str
    clicks: str
    conversions: str
    spend: str
    contribution_margin: str | None = None
    platform_conversions: str | None = None
    keyword: str | None = None
    default_margin: float = 0.0
    allow_view_through: bool = False


@dataclass(frozen=True)
class DigitalEconomicsResult:
    rows: pd.DataFrame
    totals: pd.DataFrame
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class AttributionConfig:
    method: str
    identity_coverage: float
    lookback_days: int
    includes_view_through: bool
    cross_device_linked: bool
    experiment_calibrated: bool
    long_term_effects_included: bool
    removal_redistributes_traffic: bool | None = None


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    left = numerator.to_numpy(float)
    right = denominator.to_numpy(float)
    return pd.Series(np.divide(left, right, out=np.full_like(left, np.nan), where=right > 0), index=numerator.index)


def evaluate_digital_economics(frame: pd.DataFrame, roles: DigitalRoles) -> DigitalEconomicsResult:
    """Calculate transparent funnel and contribution economics without causal attribution claims."""
    required = [roles.label, roles.impressions, roles.clicks, roles.conversions, roles.spend]
    optional = [roles.contribution_margin, roles.platform_conversions, roles.keyword]
    missing = [column for column in [*required, *[item for item in optional if item]] if column not in frame.columns]
    if missing:
        raise DataProblem("These selected digital-economics columns are missing: " + ", ".join(missing))
    if frame.empty:
        raise DataProblem("The digital-economics table has no rows.")
    work = pd.DataFrame({"label": frame[roles.label].astype("string").fillna("(missing)").str.strip()})
    if roles.keyword:
        work["keyword"] = frame[roles.keyword].astype("string").fillna("(missing)").str.strip()
    for output, source in (
        ("impressions", roles.impressions),
        ("clicks", roles.clicks),
        ("conversions", roles.conversions),
        ("spend", roles.spend),
    ):
        work[output] = pd.to_numeric(frame[source], errors="coerce")
    if work[["impressions", "clicks", "conversions", "spend"]].isna().any().any():
        raise DataProblem("Impressions, clicks, conversions, and spend must be complete numeric values.")
    if (work[["impressions", "clicks", "conversions", "spend"]] < 0).any().any():
        raise DataProblem("Impressions, clicks, conversions, and spend cannot be negative.")
    if (work["clicks"] > work["impressions"]).any():
        raise DataProblem("Clicks cannot exceed impressions in the declared funnel.")
    if not roles.allow_view_through and (work["conversions"] > work["clicks"]).any():
        raise DataProblem("Conversions cannot exceed clicks unless view-through conversions are explicitly allowed.")
    if roles.contribution_margin:
        work["margin_per_conversion"] = pd.to_numeric(frame[roles.contribution_margin], errors="coerce")
    else:
        work["margin_per_conversion"] = float(roles.default_margin)
    if work["margin_per_conversion"].isna().any() or (work["margin_per_conversion"] < 0).any():
        raise DataProblem("Contribution margin per conversion must be complete and non-negative.")
    if roles.platform_conversions:
        work["platform_conversions"] = pd.to_numeric(frame[roles.platform_conversions], errors="coerce")
        if work["platform_conversions"].isna().any() or (work["platform_conversions"] < 0).any():
            raise DataProblem("Platform-reported conversions must be complete and non-negative when selected.")
    else:
        work["platform_conversions"] = np.nan

    work["ctr"] = _safe_divide(work["clicks"], work["impressions"])
    work["cvr"] = _safe_divide(work["conversions"], work["clicks"])
    work["cpm"] = 1000 * _safe_divide(work["spend"], work["impressions"])
    work["cpc"] = _safe_divide(work["spend"], work["clicks"])
    work["cpa"] = _safe_divide(work["spend"], work["conversions"])
    work["gross_contribution"] = work["conversions"] * work["margin_per_conversion"]
    work["net_contribution"] = work["gross_contribution"] - work["spend"]
    work["contribution_roas"] = _safe_divide(work["gross_contribution"], work["spend"])
    work["break_even_cpc"] = work["cvr"] * work["margin_per_conversion"]
    work["break_even_cpa"] = work["margin_per_conversion"]
    work["tracking_coverage"] = _safe_divide(work["conversions"], work["platform_conversions"])
    work["economic_status"] = np.select(
        [work["net_contribution"] > 0, np.isclose(work["net_contribution"], 0)],
        ["POSITIVE OBSERVED CONTRIBUTION", "OBSERVED BREAK-EVEN"],
        default="NEGATIVE OBSERVED CONTRIBUTION",
    )

    total_impressions = float(work["impressions"].sum())
    total_clicks = float(work["clicks"].sum())
    total_conversions = float(work["conversions"].sum())
    total_spend = float(work["spend"].sum())
    total_gross = float(work["gross_contribution"].sum())
    total_platform = float(work["platform_conversions"].sum(min_count=1))
    totals = pd.DataFrame(
        [
            {
                "rows": int(len(work)),
                "impressions": total_impressions,
                "clicks": total_clicks,
                "conversions": total_conversions,
                "spend": total_spend,
                "ctr": total_clicks / total_impressions if total_impressions else np.nan,
                "cvr": total_conversions / total_clicks if total_clicks else np.nan,
                "cpm": 1000 * total_spend / total_impressions if total_impressions else np.nan,
                "cpc": total_spend / total_clicks if total_clicks else np.nan,
                "cpa": total_spend / total_conversions if total_conversions else np.nan,
                "gross_contribution": total_gross,
                "net_contribution": total_gross - total_spend,
                "contribution_roas": total_gross / total_spend if total_spend else np.nan,
                "tracking_coverage": total_conversions / total_platform if total_platform and total_platform > 0 else np.nan,
            }
        ]
    )
    warnings = [
        "Observed conversions and contribution are accounting outputs, not incremental effects caused by the channel."
    ]
    if roles.platform_conversions and (work["tracking_coverage"] > 1.05).any():
        warnings.append("Tracked conversions exceed platform-reported conversions in at least one row; reconcile definitions and windows.")
    if work[["ctr", "cvr", "cpc", "cpa"]].isna().any().any():
        warnings.append("At least one rate or cost is undefined because its denominator is zero.")
    if roles.allow_view_through:
        warnings.append("View-through conversions are allowed; exposure, identity, and lookback assumptions require separate scrutiny.")
    return DigitalEconomicsResult(rows=work, totals=totals, warnings=tuple(warnings))


def audit_attribution(config: AttributionConfig) -> pd.DataFrame:
    """Return an explicit assumption audit; never convert retrospective attribution into causality."""
    if not 0 <= config.identity_coverage <= 1:
        raise DataProblem("Identity coverage must be between 0 and 1.")
    if not 1 <= config.lookback_days <= 365:
        raise DataProblem("Lookback window must be between 1 and 365 days.")
    rows: list[dict[str, str]] = []

    def add(area: str, status: str, consequence: str, next_step: str) -> None:
        rows.append({"audit_area": area, "status": status, "consequence": consequence, "next_step": next_step})

    causal_status = "CALIBRATED, NOT PROVEN" if config.experiment_calibrated else "DESCRIPTIVE ONLY"
    add(
        "Incrementality",
        causal_status,
        "Attribution reallocates observed credit; it does not observe the untreated counterfactual.",
        "Use randomized holdouts or a defensible causal design for incremental lift.",
    )
    add(
        "Identity coverage",
        "LIMITED" if config.identity_coverage < 0.80 else "DECLARED",
        f"Only {config.identity_coverage:.0%} of relevant journeys are linkable under the declared identity rule.",
        "Report unlinked traffic and compare channel mix inside and outside the observable subset.",
    )
    add(
        "Lookback window",
        "ASSUMPTION",
        f"Credit depends on a {config.lookback_days}-day window; earlier or later influence is excluded.",
        "Re-run plausible windows and report which channel rankings change.",
    )
    add(
        "View-through credit",
        "INCLUDED" if config.includes_view_through else "EXCLUDED",
        "View-through credit is sensitive to exposure quality and passive correlation." if config.includes_view_through else "Non-click exposure effects are omitted.",
        "Separate click-through and view-through results and calibrate with an exposure experiment.",
    )
    add(
        "Cross-device journeys",
        "LINKED" if config.cross_device_linked else "FRAGMENTED",
        "Journey paths may be split across devices." if not config.cross_device_linked else "Cross-device linkage itself can be incomplete or probabilistic.",
        "Document deterministic versus probabilistic linkage and its coverage.",
    )
    add(
        "Long-term effects",
        "INCLUDED BY DESIGN" if config.long_term_effects_included else "OMITTED",
        "Short-window conversion credit can miss brand building, retention, and customer value.",
        "Pair immediate conversion evidence with longer-run experiments, cohorts, or customer-value analysis.",
    )
    if "markov" in config.method.casefold() or "removal" in config.method.casefold():
        redistribution = config.removal_redistributes_traffic
        add(
            "Removal assumption",
            "REDISTRIBUTED" if redistribution else "SENT TO NULL" if redistribution is False else "UNDECLARED",
            "Removal effects depend on where traffic is assumed to go when a touchpoint disappears.",
            "Show both null-state and plausible redistribution scenarios when operationally credible.",
        )
    add(
        "Decision boundary",
        "NO AUTOMATIC REALLOCATION",
        "Historical credit depends on past spend, targeting, availability, and measurement architecture.",
        "Treat attribution as journey description; use AllocSignal curves and ExperimentSignal evidence for budget decisions.",
    )
    return pd.DataFrame(rows)
