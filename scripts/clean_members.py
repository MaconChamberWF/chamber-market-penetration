"""
Clean the raw GrowthZone/ChamberMaster member export into an audit-trailed
per-row flag table used to compute Tier A (naive/raw) and Tier B (cleaned)
member counts for the chamber market-penetration report.

Input:  ../Chamber investors dump.csv  (783 rows, 1 per Profile ID)
Output: ../data/members_clean.csv

See /Users/GMCOC/.claude/plans/i-am-trying-to-expressive-axolotl.md for the
full methodology this implements.
"""
import csv
import os

SRC = os.path.join(os.path.dirname(__file__), "..", "Chamber investors dump.csv")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "members_clean.csv")

# Categories with no plausible presence in CBP/QCEW's private-sector employer
# establishment counts. "Non-Profit Organizations" is deliberately NOT here —
# CBP includes nonprofit employers with paid staff, so excluding it would be
# an unsupported assumption, not a documented fact.
NON_COVERED_CATEGORIES = {"Government", "Places of Worship"}

ADDITIONAL_LISTING_TIERS = {
    "Additional Listing",
    "Additional Listing - Cornerstone (Unpaid)",
    "Additional Listing - Cornerstone (Paid)",
}


def is_sentinel_date(s: str) -> bool:
    s = s.strip()
    return s == "" or s.startswith("1/1/1900")


def load_rows():
    with open(SRC, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build_bibb_zip_whitelist(rows):
    """Empirical zip-code fallback for the 10 rows with a blank Profile County,
    built from zip codes that appear on rows with a *confirmed* Bibb county —
    not a guessed canonical GA zip list."""
    return {
        row["Profile Zip Code"].strip()
        for row in rows
        if row.get("Profile County", "").strip() == "Bibb" and row.get("Profile Zip Code", "").strip()
    }


def clean(rows):
    bibb_zips = build_bibb_zip_whitelist(rows)
    out = []
    for row in rows:
        pid = row["Profile ID"].strip()
        org_name = row["Profile Organization Name"].strip()
        tier_name = row["Membership Level Name"].strip()
        category = row["Primary Listing Category"].strip()
        county = row.get("Profile County", "").strip()
        zip_code = row.get("Profile Zip Code", "").strip()

        # A real (non-sentinel) Date Inactive value means the profile WAS
        # marked inactive/dropped -> active means the sentinel is present.
        is_active = is_sentinel_date(row.get("Profile Date Inactive", ""))

        inherit_id = row.get("Inherit Address From Profile ID", "0").strip()
        is_dup_by_address = inherit_id not in ("", "0")
        is_additional_listing_tier = tier_name in ADDITIONAL_LISTING_TIERS

        is_non_covered_category = category in NON_COVERED_CATEGORIES

        # county resolution: direct field, else empirical zip fallback, else unknown
        if county:
            resolved_county = county
        elif zip_code in bibb_zips:
            resolved_county = "Bibb (zip-inferred)"
        else:
            resolved_county = "Unknown"
        is_in_county = resolved_county.startswith("Bibb")

        # All 783 profiles are the chamber's official investor count (Reid's
        # call) -- Profile Date Inactive is not used to exclude rows, it's
        # kept as an informational column only. Multi-location/parent-child
        # listings (is_dup_by_address) are also not deduped: CBP/QCEW counts
        # each physical establishment separately, so a multi-location member
        # is mirrored the same way on the denominator side -- deduping only
        # the numerator would introduce a mismatch, not remove one.
        is_tier_a = True
        is_tier_b = not is_non_covered_category

        out.append({
            "Profile ID": pid,
            "Organization Name": org_name,
            "Membership Level Name": tier_name,
            "Primary Listing Category": category,
            "Profile County": county,
            "Resolved County": resolved_county,
            "Profile Zip Code": zip_code,
            "is_active": is_active,
            "is_dup_by_address": is_dup_by_address,
            "is_additional_listing_tier": is_additional_listing_tier,
            "is_non_covered_category": is_non_covered_category,
            "is_in_county": is_in_county,
            "is_tier_a": is_tier_a,
            "is_tier_b": is_tier_b,
        })
    return out


def main():
    rows = load_rows()
    cleaned = clean(rows)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cleaned[0].keys()))
        w.writeheader()
        w.writerows(cleaned)

    total = len(cleaned)
    active = sum(1 for r in cleaned if r["is_active"])
    tier_a = sum(1 for r in cleaned if r["is_tier_a"])
    tier_b = sum(1 for r in cleaned if r["is_tier_b"])
    tier_a_in_county = sum(1 for r in cleaned if r["is_tier_a"] and r["is_in_county"])
    tier_b_in_county = sum(1 for r in cleaned if r["is_tier_b"] and r["is_in_county"])
    noncov_dropped = sum(1 for r in cleaned if r["is_non_covered_category"])
    multi_location = sum(1 for r in cleaned if r["is_dup_by_address"])
    unresolved_county = sum(1 for r in cleaned if r["Resolved County"] == "Unknown")

    print(f"Total rows in export:            {total}")
    print(f"  (informational only -- not used to filter) marked inactive: {total - active}")
    print(f"Tier A (all 783, naive/raw):      {tier_a}")
    print(f"  Tier A, in-county (Bibb):        {tier_a_in_county}")
    print(f"Tier B (cleaned):                 {tier_b}")
    print(f"  Tier B, in-county (Bibb):        {tier_b_in_county}")
    print(f"  -> dropped for Govt/Worship:      {noncov_dropped}")
    print(f"  (informational only -- not deduped) multi-location/parent-child rows: {multi_location}")
    print(f"Rows with unresolved county:      {unresolved_county}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
