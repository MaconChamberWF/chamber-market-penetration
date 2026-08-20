"""
One-off generator for a print-quality office image of the investor map --
NOT part of the interactive site. Differs from map/chamber-map-template.html
on purpose:
  - Tight zoom on Bibb + its 6 contiguous counties only (Crawford, Houston,
    Jones, Monroe, Peach, Twiggs), not the wide multi-county view the live
    map uses for exploring.
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
import os
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

    // Fit to Bibb + its 6 contiguous counties, not the wide regional view
    // the live map uses.
    const bounds = new maplibregl.LngLatBounds();
    for (const f of NEIGHBORS_GEOJSON.features.concat(BIBB_GEOJSON.features)) {
        const coords = f.geometry.type === "Polygon" ? f.geometry.coordinates : f.geometry.coordinates.flat();
        for (const ring of coords) for (const pt of ring) bounds.extend(pt);
    }
    map.fitBounds(bounds, { padding: 40, duration: 0 });

    window.__mapReady = true;
});
</script>

</body>
</html>
"""

if __name__ == "__main__":
    main()
