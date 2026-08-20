"""
One-off generator for a print-quality office image of the investor map --
NOT part of the interactive site. Differs from map/chamber-map-template.html
on purpose:
  - Zoomed as tight as possible while still keeping >=90% of the 729
    geocoded points on-screen (a judgment call Reid asked for explicitly --
    see compute_90pct_bounds()'s docstring for the method and its tradeoffs).
    This replaced an earlier version framed to Bibb + its 6 contiguous
    counties; that framing is still drawn (for locator context) but no
    longer what decides the crop.
  - Neighbor county borders drawn thin/muted; Bibb's own border stays bold.
  - Basemap label/POI layers (anything MapLibre style-typed "symbol") are
    hidden for a cleaner, poster-like read -- decided after inspecting the
    Liberty style's own layer list rather than hand-picking IDs, since that
    generalizes across whatever the vector style actually ships.
  - No interactivity (no search, no mode toggle, no click-to-filter) --
    this only ever gets screenshotted, never used live.

Neighbor list confirmed via web search, not assumed. County boundary
geometry: US Census TIGERweb State_County/MapServer (layer 11, Counties),
queried live for Bibb + its 6 neighbors by name/state FIPS.

Usage: python3 scripts/build_office_export.py
Output: office-export.html (git-ignored, disposable)
"""
import json
import math
import os
import statistics
import urllib.parse
import urllib.request

BASE = os.path.dirname(__file__)
CHAMBER_BUILDINGS = os.path.join(BASE, "..", "map", "data", "chamber_buildings.geojson")
OUT_HTML = os.path.join(BASE, "..", "office-export.html")

NEIGHBOR_COUNTIES = [
    "Bibb County", "Crawford County", "Houston County",
    "Jones County", "Monroe County", "Peach County", "Twiggs County",
]

TIGERWEB_URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/11/query"

COVERAGE = 0.90


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def compute_90pct_bounds(features, coverage=COVERAGE):
    """The judgment call: "zoom in as close as possible, subject to still
    showing >=90% of points" has no single textbook answer -- the true
    optimum (smallest-area window covering 90% of an arbitrary point set)
    is a real optimization problem, not a closed-form calculation. This
    uses a standard, defensible approximation instead: rank every point by
    distance from the dataset's own center and drop the farthest 10%,
    rather than, say, minimizing bounding-box area directly (which chases
    whichever single outlier is cheapest to cut and can produce a lopsided,
    gerrymandered-looking box). Center = per-axis median, not mean --
    robust to the small number of extreme outliers already known to exist
    in this dataset (a Houston TX HQ, a Wisconsin office, etc., all
    hundreds+ km out) -- a mean would get dragged toward them.
    """
    pts = [
        (f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0], f["properties"]["name"])
        for f in features
    ]
    med_lat = statistics.median(p[0] for p in pts)
    med_lon = statistics.median(p[1] for p in pts)
    ranked = sorted(
        ((haversine_km(med_lat, med_lon, lat, lon), lat, lon, name) for lat, lon, name in pts),
        key=lambda r: r[0],
    )
    n_keep = math.ceil(len(ranked) * coverage)
    kept, dropped = ranked[:n_keep], ranked[n_keep:]
    lats = [r[1] for r in kept]
    lons = [r[2] for r in kept]
    bounds = (min(lons), min(lats), max(lons), max(lats))  # west, south, east, north

    print(f"90%-coverage bounds: kept {len(kept)}/{len(ranked)} points "
          f"(closest {kept[-1][0]:.1f} km of {dropped[0][0]:.1f}+ km cutoff)")
    print(f"  bounds: west={bounds[0]:.4f} south={bounds[1]:.4f} east={bounds[2]:.4f} north={bounds[3]:.4f}")
    print(f"  dropped {len(dropped)} points (farthest from center):")
    for dist, lat, lon, name in dropped:
        print(f"    {dist:7.1f} km  {name}")
    return bounds


def fetch_county_boundaries():
    names_clause = ",".join(f"'{n}'" for n in NEIGHBOR_COUNTIES)
    params = {
        "where": f"STATE='13' AND NAME IN ({names_clause})",
        "outFields": "NAME,GEOID",
        "f": "geojson",
    }
    url = TIGERWEB_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.load(resp)
    found = {f["properties"]["NAME"] for f in data["features"]}
    missing = set(NEIGHBOR_COUNTIES) - found
    if missing:
        raise SystemExit(f"TIGERweb didn't return: {missing}")
    print(f"fetched {len(data['features'])} county boundaries: {sorted(found)}")
    return data


def main():
    with open(CHAMBER_BUILDINGS) as f:
        members_geojson = json.load(f)

    bounds = compute_90pct_bounds(members_geojson["features"])

    counties_geojson = fetch_county_boundaries()
    bibb_geojson = {
        "type": "FeatureCollection",
        "features": [f for f in counties_geojson["features"] if f["properties"]["NAME"] == "Bibb County"],
    }
    neighbors_geojson = {
        "type": "FeatureCollection",
        "features": [f for f in counties_geojson["features"] if f["properties"]["NAME"] != "Bibb County"],
    }

    html = HTML_TEMPLATE.replace("__MEMBERS_GEOJSON__", json.dumps(members_geojson))
    html = html.replace("__BIBB_GEOJSON__", json.dumps(bibb_geojson))
    html = html.replace("__NEIGHBORS_GEOJSON__", json.dumps(neighbors_geojson))
    html = html.replace("__BOUNDS__", json.dumps(list(bounds)))

    with open(OUT_HTML, "w") as f:
        f.write(html)
    print(f"wrote {OUT_HTML}")


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Chamber Investor Map -- Office Export</title>
<link rel="stylesheet" href="map/vendor/maplibre-gl.css">
<script src="map/vendor/maplibre-gl.js"></script>
<style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html, body { height: 100%; overflow: hidden; }
    body { font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }
    #map { position: absolute; inset: 0; }
    .panel {
        position: absolute; left: 16px; bottom: 16px; z-index: 5;
        background: rgba(20,20,22,0.94); border: 1px solid #27272a; border-radius: 10px;
        padding: 16px 18px; font-size: 0.86rem; color: #d4d4d8; line-height: 1.7;
        box-shadow: 0 4px 20px rgba(0,0,0,0.5); max-width: 260px;
    }
    .panel-title {
        font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
        color: #898781; margin-bottom: 10px;
    }
    .legend-row { display: flex; align-items: center; gap: 9px; padding: 2px 0; }
    .legend-swatch { width: 13px; height: 13px; border-radius: 3px; flex-shrink: 0; }
    .boundary-key { display: flex; align-items: center; gap: 9px; margin-top: 8px; }
    .boundary-swatch { width: 18px; height: 3px; background: #ffcc33; border-radius: 2px; flex-shrink: 0; }
    .boundary-key.neighbor .boundary-swatch { background: #6b6b70; }
</style>
</head>
<body>

<div id="map"></div>

<div class="panel">
    <div class="panel-title">Chamber of Commerce Investors</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#b7d3f6"></span>Micro / Basic Membership</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#6da7ec"></span>Business Catalyst</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#2a78d6"></span>Community Advocate / Partner</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#1c5cab"></span>Regional Influencer / Key Stakeholder</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#184f95"></span>Economic Driver / Leading Investor</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#9085e9"></span>Additional listing (extra location/brand)</div>
    <div class="boundary-key"><span class="boundary-swatch"></span>Bibb County</div>
    <div class="boundary-key neighbor"><span class="boundary-swatch"></span>Neighboring counties</div>
</div>

<script>
const CHAMBER_BUCKET_COLOR = {
    tier1_micro_basic: "#b7d3f6",
    tier2_catalyst: "#6da7ec",
    tier3_community: "#2a78d6",
    tier4_regional_stakeholder: "#1c5cab",
    tier5_driver_investor: "#184f95",
    additional_listing: "#9085e9",
};
const FILL_COLOR_EXPR = ["match", ["get", "bucket"], ...Object.entries(CHAMBER_BUCKET_COLOR).flat(), "#ffffff"];

const MEMBERS_GEOJSON = __MEMBERS_GEOJSON__;
const BIBB_GEOJSON = __BIBB_GEOJSON__;
const NEIGHBORS_GEOJSON = __NEIGHBORS_GEOJSON__;
// [west, south, east, north] -- computed in Python as the tightest box
// covering the closest 90% of points to the dataset's median center. See
// compute_90pct_bounds() in build_office_export.py for the method.
const POINT_BOUNDS = __BOUNDS__;

const map = new maplibregl.Map({
    container: "map",
    style: "https://tiles.openfreemap.org/styles/liberty",
    center: [-83.65, 32.85],
    zoom: 9,
    interactive: false,
});

map.on("load", () => {
    // Declutter: hide every label/icon layer (MapLibre styles put place
    // names, road names, and POI icons in "symbol"-type layers) so the
    // basemap reads as a clean reference map, not a street-navigation app.
    for (const layer of map.getStyle().layers) {
        if (layer.type === "symbol") map.setLayoutProperty(layer.id, "visibility", "none");
    }

    map.addSource("neighbor-counties", { type: "geojson", data: NEIGHBORS_GEOJSON });
    map.addLayer({
        id: "neighbor-counties-line", type: "line", source: "neighbor-counties",
        paint: { "line-color": "#6b6b70", "line-width": 1.5, "line-opacity": 0.8 },
    });

    map.addSource("bibb-county", { type: "geojson", data: BIBB_GEOJSON });
    map.addLayer({
        id: "bibb-county-halo", type: "line", source: "bibb-county",
        paint: { "line-color": "#1a1400", "line-width": 6, "line-opacity": 0.5 },
    });
    map.addLayer({
        id: "bibb-county-line", type: "line", source: "bibb-county",
        paint: { "line-color": "#ffcc33", "line-width": 3 },
    });

    map.addSource("chamber-members", { type: "geojson", data: MEMBERS_GEOJSON });
    map.addLayer({
        id: "chamber-members-halo", type: "circle", source: "chamber-members",
        paint: { "circle-radius": 6, "circle-color": "#ffffff", "circle-opacity": 0.9 },
    });
    map.addLayer({
        id: "chamber-members-dot", type: "circle", source: "chamber-members",
        paint: { "circle-radius": 4.2, "circle-color": FILL_COLOR_EXPR },
    });

    // Fit to the tightest box covering 90% of investor points -- not the
    // county polygons (those still render for locator context, but no
    // longer decide the crop).
    const bounds = new maplibregl.LngLatBounds(
        [POINT_BOUNDS[0], POINT_BOUNDS[1]], [POINT_BOUNDS[2], POINT_BOUNDS[3]]
    );
    map.fitBounds(bounds, { padding: 50, duration: 0 });

    window.__mapReady = true;
});
</script>

</body>
</html>
"""

if __name__ == "__main__":
    main()
