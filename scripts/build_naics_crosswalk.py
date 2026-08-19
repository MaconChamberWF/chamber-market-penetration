"""
Phase 2: industry-level market penetration.

Applies data/naics_crosswalk.json (chamber Primary Listing Category -> one
of JobsEQ's 20 published 2-digit NAICS sectors, or null if no single
sector fits -- see that file's own per-category notes for how each
mapping was decided) to the Tier B members in data/members_clean.csv, and
divides by JobsEQ's real establishment counts for Bibb County to get a
per-sector penetration rate.

Per-member overrides (data/naics_member_overrides.json) are checked first,
ahead of the category-level crosswalk -- built for "Utilities & Internet
Service Providers," a 17-member category that splits almost exactly in
half between two sectors on inspection, too material to exclude wholesale
but small enough to classify by hand instead of guessing.

Categories still mapped to null after that (Non-Profit Organizations,
Foundations, Business & Economic Development, and blank) are reported
separately as "not classifiable by this crosswalk," not folded into any
sector's count.

Input:  ../Data Explorer.xlsx (JobsEQ, 2025Q4, Bibb County establishment
        counts by 2-digit NAICS sector)
        ../data/members_clean.csv (Tier B members + Primary Listing Category)
        ../data/naics_crosswalk.json (category -> sector mapping)
        ../data/naics_member_overrides.json (per-member sector, optional)
Output: ../data/naics_penetration.json
"""
import csv
import json
import os
import re

import openpyxl

BASE = os.path.dirname(__file__)
JOBSEQ_XLSX = os.path.join(BASE, "..", "Data Explorer.xlsx")
CLEAN_CSV = os.path.join(BASE, "..", "data", "members_clean.csv")
CROSSWALK_PATH = os.path.join(BASE, "..", "data", "naics_crosswalk.json")
MEMBER_OVERRIDES_PATH = os.path.join(BASE, "..", "data", "naics_member_overrides.json")
OUT = os.path.join(BASE, "..", "data", "naics_penetration.json")

# JobsEQ column header -> 2-digit NAICS code, matching the codes used as
# "sector" values in naics_crosswalk.json. "Total High-Tech" is a
# cross-cutting tag (overlaps other sectors), not a real sector -- skipped.
SECTOR_CODE_RE = re.compile(r"\((\d+)\)\s*$")


def load_jobseq_sectors():
    wb = openpyxl.load_workbook(JOBSEQ_XLSX, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header_row = rows[1]   # sector names, e.g. "Health Care and Social Assistance (62)"
    label_row = rows[2]    # "Establishments" repeated in every data column
    data_row = rows[3]     # "Bibb County, Georgia", FIPS, then the counts

    total = None
    sectors = {}
    for col, name in enumerate(header_row):
        if not name:
            continue
        value = data_row[col]
        if name == "Total - All Industries":
            total = value
            continue
        if name == "Total High-Tech (5)":
            continue
        m = SECTOR_CODE_RE.search(name)
        if not m:
            continue
        code = m.group(1)
        sector_label = name[:m.start()].strip()
        sectors[code] = {"label": sector_label, "establishments": value}
    return total, sectors


def load_tier_b_members():
    with open(CLEAN_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r["is_tier_b"] == "True"]


def load_crosswalk():
    with open(CROSSWALK_PATH, encoding="utf-8") as f:
        crosswalk = json.load(f)
    crosswalk.pop("_readme", None)
    return crosswalk


def load_member_overrides():
    if not os.path.exists(MEMBER_OVERRIDES_PATH):
        return {}
    with open(MEMBER_OVERRIDES_PATH, encoding="utf-8") as f:
        overrides = json.load(f)
    overrides.pop("_readme", None)
    return overrides


def resolve_sector(profile_id, category, crosswalk, member_overrides):
    """The single source of truth for "what sector is this member," reused
    by both this script (industry penetration table) and
    build_map_data.py (industry-color mode on the map) so the two never
    quietly disagree. Returns a 2-digit NAICS code, or None if
    unclassifiable (category maps to null, or isn't in the crosswalk at
    all -- callers that need to distinguish "unclassifiable" from
    "unrecognized category" should check membership themselves)."""
    override = member_overrides.get(profile_id)
    if override is not None:
        return override["sector"]
    entry = crosswalk.get(category or "(blank)")
    if entry is None:
        return None
    return entry["sector"]


def main():
    total_establishments, sectors = load_jobseq_sectors()
    crosswalk = load_crosswalk()
    member_overrides = load_member_overrides()
    members = load_tier_b_members()
    print(f"Loaded {len(members)} Tier B members, {len(sectors)} JobsEQ sectors "
          f"(Bibb County total: {total_establishments})")

    sector_sum = sum(s["establishments"] for s in sectors.values())
    print(f"Sum of published sectors: {sector_sum} vs total {total_establishments} "
          f"-- gap of {total_establishments - sector_sum} (unclassified/not broken out by JobsEQ)")

    counts_by_sector = {code: 0 for code in sectors}
    unclassified_members = []
    uncrosswalked_categories = set()
    member_override_hits = 0

    for m in members:
        pid = m["Profile ID"]
        override = member_overrides.get(pid)
        if override is not None:
            counts_by_sector[override["sector"]] += 1
            member_override_hits += 1
            continue
        cat = m["Primary Listing Category"] or "(blank)"
        entry = crosswalk.get(cat)
        if entry is None:
            uncrosswalked_categories.add(cat)
            continue
        sector = entry["sector"]
        if sector is None:
            unclassified_members.append({"id": m["Profile ID"], "name": m["Organization Name"], "category": cat})
            continue
        counts_by_sector[sector] += 1

    print(f"Applied {member_override_hits} per-member overrides "
          f"({MEMBER_OVERRIDES_PATH})")

    if uncrosswalked_categories:
        raise SystemExit(f"Categories present in members_clean.csv but missing from "
                          f"naics_crosswalk.json: {sorted(uncrosswalked_categories)}")

    classified_total = sum(counts_by_sector.values())
    print(f"\nClassified: {classified_total} members across {len(sectors)} sectors")
    print(f"Unclassifiable: {len(unclassified_members)} members "
          f"({100*len(unclassified_members)/len(members):.1f}% of Tier B)")

    county_avg_penetration = 100 * classified_total / sector_sum

    results = []
    for code, s in sorted(sectors.items(), key=lambda kv: -counts_by_sector[kv[0]]):
        n_members = counts_by_sector[code]
        establishments = s["establishments"]
        penetration = 100 * n_members / establishments if establishments else None
        results.append({
            "naics_code": code,
            "sector_label": s["label"],
            "members": n_members,
            "county_establishments": establishments,
            "penetration_pct": round(penetration, 2) if penetration is not None else None,
            "vs_county_avg_pct": round(penetration - county_avg_penetration, 2) if penetration is not None else None,
        })

    output = {
        "jobseq_source": "Data Explorer.xlsx (JobsEQ, Bibb County, GA -- Industry Data, Covered Employment, 2025Q4)",
        "jobseq_total_establishments": total_establishments,
        "jobseq_sector_sum": sector_sum,
        "jobseq_unclassified_gap": total_establishments - sector_sum,
        "tier_b_total": len(members),
        "tier_b_classified": classified_total,
        "tier_b_member_overrides_applied": member_override_hits,
        "tier_b_unclassifiable": len(unclassified_members),
        "county_avg_penetration_pct": round(county_avg_penetration, 2),
        "sectors": results,
        "unclassified_members": unclassified_members,
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote {OUT}")

    print("\nTop sectors by penetration:")
    for r in sorted(results, key=lambda r: -(r["penetration_pct"] or -1))[:8]:
        print(f"  {r['penetration_pct']:>6.2f}%  {r['members']:>4} / {r['county_establishments']:<5}  {r['sector_label']}")


if __name__ == "__main__":
    main()
