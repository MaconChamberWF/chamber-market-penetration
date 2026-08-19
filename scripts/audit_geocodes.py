"""
Cross-check every already-geocoded chamber member against an independent
Nominatim business-NAME search, to look for more cases like "Z Beans
Coffee" -- a member whose address geocoded "successfully," but to the
chamber's own wrong address-of-record (it matched a different, unrelated
member at the same address). A wrong-but-valid address is invisible to
the geocoding pipeline itself; it can only be caught by cross-referencing
against a second, independent source.

Method: for each of the ~729 points in data/chamber_map_points.json, run
the same business-name search geocode_members.py's Pass 3 already uses
(name + city + state), and measure the distance between that result and
the point currently on the map. A wide gap is the Z Beans signature.

This is NOT proof of an error by itself -- a name search can genuinely
land on a same-named chain location elsewhere, or on an unrelated
business that happens to share words with this one, or simply fail to
find anything for a small business with no OSM presence (Nominatim's
business-name coverage is thin, same limitation noted in
geocode_members.py's Pass 3). It's a triage signal: sort by distance,
manually verify the top of the list, and expect a real false-positive
rate rather than treating every flagged row as a confirmed mistake.

Input:  data/chamber_map_points.json, data/members_clean.csv,
        data/Chamber investors dump.csv (via geocode_members.load_filtered_rows)
Output: data/geocode_audit_report.json -- every point with a name-search
        result, sorted by distance descending.
"""
import json
import math
import os
import time

from geocode_members import (
    BASE, OUT, load_filtered_rows, simplify_business_name, nominatim_search_full,
)

AUDIT_OUT = os.path.join(BASE, "..", "data", "geocode_audit_report.json")


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main():
    with open(OUT, encoding="utf-8") as f:
        points = {p["id"]: p for p in json.load(f)}
    rows = {r["id"]: r for r in load_filtered_rows()}
    print(f"Auditing {len(points)} geocoded members via Nominatim name search...")

    results = []
    checked = 0
    for pid, p in points.items():
        r = rows.get(pid)
        if not r:
            continue
        q = f"{simplify_business_name(p['name'])} {r['city']} {r['state']}"
        hit = nominatim_search_full(q)
        checked += 1
        if checked % 50 == 0:
            print(f"  ...{checked} / {len(points)}")
        if not hit:
            results.append({
                "id": pid, "name": p["name"], "current_source": p["geocode_source"],
                "current_lat": p["lat"], "current_lon": p["lon"],
                "name_search_found": False, "distance_km": None,
            })
            time.sleep(1.1)
            continue
        nlat, nlon = float(hit["lat"]), float(hit["lon"])
        dist = haversine_km(p["lat"], p["lon"], nlat, nlon)
        results.append({
            "id": pid, "name": p["name"], "current_source": p["geocode_source"],
            "current_lat": p["lat"], "current_lon": p["lon"],
            "name_search_found": True, "name_search_lat": nlat, "name_search_lon": nlon,
            "name_search_display_name": hit.get("display_name"),
            "distance_km": round(dist, 3),
        })
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec

    with_dist = [r for r in results if r["distance_km"] is not None]
    with_dist.sort(key=lambda r: r["distance_km"], reverse=True)
    no_match = [r for r in results if r["distance_km"] is None]

    flagged = [r for r in with_dist if r["distance_km"] > 1.0]
    print(f"\n{len(with_dist)} had a name-search result, {len(no_match)} had none "
          f"(no independent cross-check possible for those).")
    print(f"{len(flagged)} flagged (>1km from current point) for manual review:")
    for r in flagged:
        print(f"  {r['distance_km']:>7.2f} km  {r['id']:>7}  {r['name']}")

    ordered = with_dist + no_match
    with open(AUDIT_OUT, "w", encoding="utf-8") as f:
        json.dump(ordered, f, indent=2)
    print(f"\nWrote full audit report ({len(ordered)} rows) to {AUDIT_OUT}")


if __name__ == "__main__":
    main()
