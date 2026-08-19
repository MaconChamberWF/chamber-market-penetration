"""
Build the chamber-member map data: a plain point per geocoded Tier B
member, no building-footprint matching at all.

This replaces an escalating series of attempts to match each member to its
real building polygon (point-in-polygon + nearest-within-distance against
Microsoft Building Footprints, then an OSM-name-search pass to fix cases
that approach got wrong). The OSM pass fixed real cases (Amici Macon was
matching to the wrong, much larger neighboring building) but not all of
them -- confirmed more mismatches remained after that fix, and building-
polygon matching has no ceiling of "good enough" short of matching every
building perfectly, which real-world address/geocoding precision doesn't
support. Decided to drop building-polygon rendering entirely rather than
keep patching it: a point marker doesn't have a "size" that can be wrong
the way a mismatched building polygon does, so the whole failure mode goes
away, not just the cases caught so far.

The geocoded points from scripts/geocode_members.py are used as-is --
that script already runs its own 3-pass geocoding (Census batch, Nominatim
address fallback, Nominatim business-name fallback), so there's no
additional OSM lookup here. A ~50-100m difference between a Census address
geocode and a more precise OSM point, which mattered enormously for
picking the *correct building polygon*, is not something a reader can even
perceive in a dot on a map at any reasonable zoom.

Each point also carries a "sector" property (2-digit NAICS code, or
"unclassified") -- the same resolution used for the report's industry
penetration table (scripts/build_naics_crosswalk.py's resolve_sector),
reused here rather than reimplemented so the map's industry-color mode
and the report's industry table can never quietly disagree about which
sector a member belongs to.

Input:  data/county_boundary/bibb_county.geojson  (drawn as a boundary line)
        data/chamber_map_points.json  (Tier B members, all counties,
          already geocoded to lat/lon by scripts/geocode_members.py)
        data/members_clean.csv  (Primary Listing Category per member, for
          sector resolution)
        data/naics_crosswalk.json, data/naics_member_overrides.json
Output: map/data/chamber_buildings.geojson  (one Point feature per member --
          filename kept from the building-matching version rather than
          renamed, since chamber-map-template.html and the report's iframe
          reference it; content is now points, not polygons)
        map/chamber-map.html  (assembled from map/chamber-map-template.html,
          the GeoJSON inlined directly -- fetch() of the sibling .geojson
          file is blocked by Chrome's file:// CORS restrictions)
"""
import csv
import json
import os
import sys

BASE = os.path.dirname(__file__)
COUNTY_BOUNDARY = os.path.join(BASE, "..", "data", "county_boundary", "bibb_county.geojson")
CHAMBER_POINTS = os.path.join(BASE, "..", "data", "chamber_map_points.json")
CLEAN_CSV = os.path.join(BASE, "..", "data", "members_clean.csv")
OUT_PATH = os.path.join(BASE, "..", "map", "data", "chamber_buildings.geojson")
BOUNDARY_OUT_PATH = os.path.join(BASE, "..", "map", "data", "bibb_county_boundary.geojson")

sys.path.insert(0, BASE)
from build_naics_crosswalk import load_crosswalk, load_member_overrides, resolve_sector  # noqa: E402


def load_categories_by_id():
    with open(CLEAN_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {r["Profile ID"]: r["Primary Listing Category"] for r in rows}


def main():
    print("loading chamber member points...")
    with open(CHAMBER_POINTS) as f:
        members = json.load(f)
    print(f"  {len(members)} geocoded members")

    print("resolving industry sectors...")
    categories_by_id = load_categories_by_id()
    crosswalk = load_crosswalk()
    member_overrides = load_member_overrides()
    sector_counts = {}
    for m in members:
        category = categories_by_id.get(m["id"], "")
        sector = resolve_sector(m["id"], category, crosswalk, member_overrides)
        m["sector"] = sector or "unclassified"
        sector_counts[m["sector"]] = sector_counts.get(m["sector"], 0) + 1
    print(f"  {len(sector_counts)} distinct sectors ({sector_counts.get('unclassified', 0)} unclassified)")

    out_features = [
        {
            "type": "Feature",
            "properties": {"name": m["name"], "bucket": m["bucket"], "sector": m["sector"]},
            "geometry": {"type": "Point", "coordinates": [m["lon"], m["lat"]]},
        }
        for m in members
    ]
    geojson_obj = {"type": "FeatureCollection", "features": out_features}

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(geojson_obj, f)
    print(f"wrote {len(out_features)} member points to {OUT_PATH}")

    print("writing county boundary geojson...")
    with open(COUNTY_BOUNDARY) as f:
        county_geojson = json.load(f)
    with open(BOUNDARY_OUT_PATH, "w") as f:
        json.dump(county_geojson, f)
    print(f"wrote {BOUNDARY_OUT_PATH}")

    print("assembling chamber-map.html...")
    template_path = os.path.join(BASE, "..", "map", "chamber-map-template.html")
    html_out_path = os.path.join(BASE, "..", "map", "chamber-map.html")
    with open(template_path) as f:
        html = f.read()
    html = html.replace("__CHAMBER_BUILDINGS_GEOJSON__", json.dumps(geojson_obj))
    html = html.replace("__COUNTY_BOUNDARY_GEOJSON__", json.dumps(county_geojson))
    with open(html_out_path, "w") as f:
        f.write(html)
    print(f"wrote {html_out_path}")


if __name__ == "__main__":
    main()
