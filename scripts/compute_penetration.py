"""
Cross-tab Tier A / Tier B member counts against the researched denominators
to produce the penetration-rate matrix used in the overview report.

Input:  ../data/members_clean.csv  (from clean_members.py)
Output: ../data/penetration_results.json

Denominator sourcing is documented inline — see the handoff summary in the
conversation this was built from, and the plan at
/Users/GMCOC/.claude/plans/i-am-trying-to-expressive-axolotl.md.
"""
import csv
import json
import os

IN = os.path.join(os.path.dirname(__file__), "..", "data", "members_clean.csv")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "penetration_results.json")

DENOMINATORS = {
    "cbp_2023": {
        "label": "CBP 2023 employer establishments (Bibb County)",
        "value": 4147,
        "source": "U.S. Census Bureau, County Business Patterns, 2023, Bibb County, GA",
        "role": "primary",
        "note": "Most methodologically transparent employer-establishment count; corroborated by JobsEQ/QCEW (~4,300).",
    },
    "esri_data_axle_2026": {
        "label": "Esri/Data Axle ‘2026 Total Businesses (NAICS)’ (MBCIA Local Data page)",
        "value": 6713,
        "source": "MBCIA Local Data page, embedded Esri Workforce Overview dashboard (business-listing file, April 2026 vintage)",
        "role": "secondary",
        "note": "Broader universe than CBP — Data Axle's own methodology says it includes freelancers, contractors, home-based businesses, and coworking spaces. Not a clean employer-establishment count. Geographic scope (Bibb County vs. broader labor market area) is ASSUMED, not confirmed — verify against MBCIA site before publishing externally.",
    },
}


def load_rows():
    with open(IN, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def to_bool(s):
    return str(s).strip() == "True"


def rate(numerator, denominator):
    return round(100 * numerator / denominator, 2) if denominator else None


def main():
    rows = load_rows()

    tier_a_all = sum(1 for r in rows if to_bool(r["is_tier_a"]))
    tier_a_in_county = sum(1 for r in rows if to_bool(r["is_tier_a"]) and to_bool(r["is_in_county"]))
    tier_b_all = sum(1 for r in rows if to_bool(r["is_tier_b"]))
    tier_b_in_county = sum(1 for r in rows if to_bool(r["is_tier_b"]) and to_bool(r["is_in_county"]))

    tiers = {
        "tier_a": {
            "label": "Tier A — Naive/Raw (all 783 investor profiles, no cleaning)",
            "all_members": tier_a_all,
            "in_county_members": tier_a_in_county,
        },
        "tier_b": {
            "label": "Tier B — Cleaned (excl. Government/Places of Worship; multi-location listings kept, not deduped)",
            "all_members": tier_b_all,
            "in_county_members": tier_b_in_county,
        },
    }

    results = {"denominators": DENOMINATORS, "tiers": tiers, "matrix": []}

    for tier_key, tier in tiers.items():
        for denom_key, denom in DENOMINATORS.items():
            for scope_key, scope_label, numerator in [
                ("all", "All investor profiles (incl. out-of-county)", tier["all_members"]),
                ("in_county", "In-Bibb-County members only", tier["in_county_members"]),
            ]:
                results["matrix"].append({
                    "tier": tier_key,
                    "tier_label": tier["label"],
                    "denominator": denom_key,
                    "denominator_label": denom["label"],
                    "denominator_value": denom["value"],
                    "scope": scope_key,
                    "scope_label": scope_label,
                    "numerator": numerator,
                    "penetration_pct": rate(numerator, denom["value"]),
                })

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"{'Tier':<8} {'Scope':<28} {'Denominator':<14} {'Numerator':>9} {'Denom':>7} {'Rate':>8}")
    for cell in results["matrix"]:
        print(
            f"{cell['tier']:<8} {cell['scope_label']:<28} {cell['denominator']:<14} "
            f"{cell['numerator']:>9} {cell['denominator_value']:>7} {cell['penetration_pct']:>7}%"
        )
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
