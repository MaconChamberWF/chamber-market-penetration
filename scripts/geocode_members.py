"""
Geocode the Tier B chamber members (all counties -- 754 rows) for the map.

Three passes, each only attempted on what the previous one missed:
  1. Census Bureau batch geocoder (address -> lat/lon), one request for
     everything.
  2. Nominatim, per-address, with suite/unit text stripped (helps a
     handful the batch geocoder's stricter parser misses).
  3. Nominatim, per-BUSINESS-NAME instead of address ("{name} Macon GA") --
     added because large industrial employers (Kumho Tire, Graphic
     Packaging confirmed) sit on privately-named roads ("Kumho Parkway",
     "Graphic Packing International Way") that no address geocoder
     resolves, but that are mapped in OpenStreetMap as named facilities
     (man_made=works) findable by name. Skipped for PO boxes and
     "Call for more information"-style non-addresses -- there's no
     business name search that fixes a listing with no real location.

No distance-based outlier filtering here (an earlier version of this
script dropped points far from Bibb County's center, back when the map
only ever showed in-county members) -- this run deliberately includes
members outside Bibb County, so "far from Bibb" is no longer evidence of
a bad geocode.

A fourth "pass," checked first: ../data/geocode_overrides.json, a small
hand-researched file for members none of the three automated passes could
resolve (private/undeveloped-in-OSM office parks, street-name mismatches
between the chamber's records and the real name, etc.) -- see that file's
own per-entry notes for how each one was actually found and how much to
trust its precision. Real data input, not a hack: kept as its own file
specifically so it stays inspectable/editable on its own rather than
buried in this script.

Input:  ../Chamber investors dump.csv (street addresses)
        ../data/members_clean.csv (tier/county flags + membership level)
        ../data/geocode_overrides.json (hand-researched fallback, optional)
Output: ../data/chamber_map_points.json
"""
import csv
import json
import os
import re
import time
import urllib.request
import urllib.parse

BASE = os.path.dirname(__file__)
DUMP_CSV = os.path.join(BASE, "..", "data", "Chamber investors dump.csv")
CLEAN_CSV = os.path.join(BASE, "..", "data", "members_clean.csv")
OUT = os.path.join(BASE, "..", "data", "chamber_map_points.json")
OVERRIDES_PATH = os.path.join(BASE, "..", "data", "geocode_overrides.json")
BATCH_INPUT = os.path.join(BASE, "..", "data", "geocode_batch_input.csv")
BATCH_RAW_OUTPUT = os.path.join(BASE, "..", "data", "geocode_batch_result.csv")

CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
BENCHMARK = "Public_AR_Current"
# Ordinal tier -> map-color-bucket, matching the report's tier ramp exactly
# (was previously assigned in a one-off terminal step, not saved in this
# script -- restored here as the real place it belongs).
BUCKET_MAP = {
    "Micro Membership": "tier1_micro_basic",
    "Basic Membership": "tier1_micro_basic",
    "Business Catalyst": "tier2_catalyst",
    "Community Advocate": "tier3_community",
    "Community Partner": "tier3_community",
    "Regional Influencer": "tier4_regional_stakeholder",
    "Key Stakeholder": "tier4_regional_stakeholder",
    "Economic Driver": "tier5_driver_investor",
    "Leading Investor": "tier5_driver_investor",
    "Additional Listing": "additional_listing",
    "Additional Listing - Cornerstone (Unpaid)": "additional_listing",
    "Additional Listing - Cornerstone (Paid)": "additional_listing",
}
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_UA = "ChamberPenetrationStudy/1.0 (research use, reid)"
NO_REAL_ADDRESS_RE = re.compile(r"P\.?O\.?\s*Box|Call [Ff]or", re.I)
# Legal-entity suffixes stripped before a Pass 3 name search -- confirmed by
# direct testing that this matters a lot: "Graphic Packaging International,
# Inc. Macon GA" and "YKK AP America Inc. Macon GA" both return zero
# Nominatim results, while the simplified "Graphic Packaging Macon GA" and
# "YKK AP Macon GA" both find the real OSM-mapped facility. OSM names real
# businesses/landuse areas the way people actually refer to them, not by
# their registered legal name.
LEGAL_SUFFIX_RE = re.compile(
    r",?\s+(International,?\s+)?(Inc\.?|LLC|L\.L\.C\.?|Corp\.?|Corporation|Co\.?|Company|Ltd\.?|L\.?P\.?|LLP|PC|P\.C\.?)\s*$",
    re.I,
)


def simplify_business_name(name):
    prev = None
    while prev != name:
        prev = name
        name = LEGAL_SUFFIX_RE.sub("", name).strip()
    return name
SUITE_UNIT_RE = re.compile(r",?\s*(Suite|Ste\.?|Unit|Floor|Fl\.?|#)\s*\S+.*$", re.I)


def to_bool(v):
    return str(v).strip() == "True"


def load_filtered_rows():
    with open(CLEAN_CSV, newline="", encoding="utf-8") as f:
        clean_rows = {r["Profile ID"]: r for r in csv.DictReader(f)}

    with open(DUMP_CSV, newline="", encoding="utf-8-sig") as f:
        dump_rows = {r["Profile ID"]: r for r in csv.DictReader(f)}

    filtered = []
    for pid, c in clean_rows.items():
        if to_bool(c["is_tier_b"]):
            d = dump_rows[pid]
            street = (d.get("Profile Address1", "").strip() + " " + d.get("Profile Address 2", "").strip()).strip()
            filtered.append({
                "id": pid,
                "name": c["Organization Name"],
                "tier": c["Membership Level Name"],
                "street": street,
                "city": d.get("Profile City", "").strip() or "Macon",
                "state": d.get("Profile State", "").strip() or "GA",
                "zip": d.get("Profile Zip Code", "").strip(),
            })
    return filtered


def write_batch_input(rows):
    with open(BATCH_INPUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow([r["id"], r["street"], r["city"], r["state"], r["zip"]])


def call_census_batch(rows):
    """POST the batch file as multipart/form-data to the Census geocoder.
    Census's batch endpoint accepts up to 10,000 addresses per call, so one
    request covers everything."""
    boundary = "----chamberGeocodeBoundary"
    with open(BATCH_INPUT, "rb") as f:
        file_bytes = f.read()

    parts = []
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(b'Content-Disposition: form-data; name="addressFile"; filename="batch.csv"\r\n')
    parts.append(b"Content-Type: text/csv\r\n\r\n")
    parts.append(file_bytes)
    parts.append(b"\r\n")
    for field, value in [("benchmark", BENCHMARK)]:
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(
        CENSUS_BATCH_URL, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result_bytes = resp.read()
    with open(BATCH_RAW_OUTPUT, "wb") as f:
        f.write(result_bytes)
    return result_bytes.decode("utf-8", errors="replace")


def parse_batch_result(csv_text):
    """Census batch result columns (no header row):
    ID, input address, match(Match/No_Match/Tie), match type,
    matched address, "lon,lat", tiger line id, side
    """
    matched = {}
    reader = csv.reader(csv_text.splitlines())
    for row in reader:
        if len(row) < 6:
            continue
        rid, match_status = row[0], row[2]
        if match_status != "Match":
            continue
        lonlat = row[5]
        lon_str, lat_str = lonlat.split(",")
        matched[rid] = (float(lat_str), float(lon_str))
    return matched


def nominatim_search_full(query, polygon=False):
    """Returns the full first result dict (lat, lon, and -- if polygon=True
    and OSM has one -- a real 'geojson' polygon/way geometry, not just a
    point), or None. Used by build_map_data.py's OSM-first matching pass to
    get an actual building shape straight from OSM when one exists, instead
    of only a point that then needs a separate footprint lookup."""
    params = {"q": query, "format": "json", "limit": 1, "countrycodes": "us"}
    if polygon:
        params["polygon_geojson"] = 1
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": NOMINATIM_UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except Exception as e:
        print(f"  Nominatim error for {query!r}: {e}")
        return None
    if not data:
        return None
    return data[0]


def nominatim_search(query):
    result = nominatim_search_full(query)
    if not result:
        return None
    return float(result["lat"]), float(result["lon"])


def main():
    rows = load_filtered_rows()
    print(f"Filtered to {len(rows)} Tier B members (all counties)")

    write_batch_input(rows)
    print(f"Wrote batch input: {BATCH_INPUT}")

    print("Pass 1: Census Bureau batch geocoder...")
    t0 = time.time()
    result_text = call_census_batch(rows)
    print(f"  got response in {time.time()-t0:.1f}s")
    census_matched = parse_batch_result(result_text)
    print(f"  matched {len(census_matched)} / {len(rows)} ({100*len(census_matched)/len(rows):.1f}%)")

    points = {}
    for r in rows:
        if r["id"] in census_matched:
            lat, lon = census_matched[r["id"]]
            points[r["id"]] = {"id": r["id"], "name": r["name"], "tier": r["tier"],
                                "lat": lat, "lon": lon, "geocode_source": "census_batch"}

    still_unmatched = [r for r in rows if r["id"] not in points]
    geocodable = [r for r in still_unmatched if not NO_REAL_ADDRESS_RE.search(r["street"])]
    skipped = [r for r in still_unmatched if NO_REAL_ADDRESS_RE.search(r["street"])]
    print(f"\nPass 2: Nominatim address fallback for {len(geocodable)} "
          f"(skipping {len(skipped)} with no real street address -- PO box / placeholder)...")
    pass2_hits = 0
    for r in geocodable:
        q = f"{SUITE_UNIT_RE.sub('', r['street']).strip()}, {r['city']}, {r['state']} {r['zip']}"
        hit = nominatim_search(q)
        if hit:
            lat, lon = hit
            points[r["id"]] = {"id": r["id"], "name": r["name"], "tier": r["tier"],
                                "lat": lat, "lon": lon, "geocode_source": "nominatim_address"}
            pass2_hits += 1
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
    print(f"  matched {pass2_hits} / {len(geocodable)}")

    still_unmatched = [r for r in rows if r["id"] not in points]
    geocodable = [r for r in still_unmatched if not NO_REAL_ADDRESS_RE.search(r["street"])]
    print(f"\nPass 3: Nominatim NAME search for {len(geocodable)} still-unmatched "
          f"(catches employers on privately-named roads standard geocoders can't resolve)...")
    pass3_hits = 0
    for r in geocodable:
        q = f"{simplify_business_name(r['name'])} {r['city']} {r['state']}"
        hit = nominatim_search(q)
        if hit:
            lat, lon = hit
            points[r["id"]] = {"id": r["id"], "name": r["name"], "tier": r["tier"],
                                "lat": lat, "lon": lon, "geocode_source": "nominatim_name"}
            pass3_hits += 1
            print(f"  recovered: {r['name']!r}")
        time.sleep(1.1)
    print(f"  matched {pass3_hits} / {len(geocodable)}")

    # Overrides apply to any row named in the file, not just still-unmatched
    # ones -- some entries correct an automated pass that "succeeded" but
    # geocoded the chamber's own wrong address (e.g. Z Beans Coffee), not
    # just fill gaps left by no automated match at all.
    if os.path.exists(OVERRIDES_PATH):
        with open(OVERRIDES_PATH) as f:
            overrides = json.load(f)
        applied = 0
        corrected = 0
        for r in rows:
            ov = overrides.get(r["id"])
            if not ov:
                continue
            if r["id"] in points:
                corrected += 1
            points[r["id"]] = {"id": r["id"], "name": r["name"], "tier": r["tier"],
                                "lat": ov["lat"], "lon": ov["lon"], "geocode_source": "manual_override"}
            applied += 1
        print(f"\nPass 4: manual overrides ({OVERRIDES_PATH}) -- applied {applied} ({corrected} corrected an automated match, {applied - corrected} filled a gap)")

    final_points = list(points.values())
    for p in final_points:
        p["bucket"] = BUCKET_MAP[p["tier"]]
    print(f"\nTotal geocoded: {len(final_points)} / {len(rows)} ({100*len(final_points)/len(rows):.1f}%)")

    unmatched = [r for r in rows if r["id"] not in points]
    if unmatched:
        print(f"\n{len(unmatched)} still unmatched:")
        for r in unmatched:
            print(f"  {r['id']}: {r['name']!r} -- {r['street']!r}, {r['city']}, {r['state']} {r['zip']}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(final_points, f, indent=2)
    print(f"\nWrote {len(final_points)} geocoded points to {OUT}")


if __name__ == "__main__":
    main()
