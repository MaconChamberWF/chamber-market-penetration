"""
One-off generator for a print-quality office image of the investor map --
NOT part of the interactive site. Differs from map/chamber-map-template.html
on purpose:
  - Restricted to Bibb County only: points outside Bibb's own boundary are
    dropped (true point-in-polygon test via shapely, not a bounding-box or
    distance-from-center approximation -- Bibb's shape is irregular enough
    that a bbox would let corners of neighboring counties leak in), and no
    other county's boundary renders at all. Simpler and more defensible
    than an earlier version's "tightest box covering 90% of all points"
    heuristic -- this report and map are about Bibb County specifically,
    so restricting the image to exactly that is the more honest crop.
  - Basemap label/POI layers (anything MapLibre style-typed "symbol") are
    hidden for a cleaner, poster-like read -- decided after inspecting the
    Liberty style's own layer list rather than hand-picking IDs, since that
    generalizes across whatever the vector style actually ships.
  - No interactivity (no search, no mode toggle, no click-to-filter) --
    this only ever gets screenshotted, never used live.

County boundary: data/county_boundary/bibb_county.geojson, the same file
the live map itself uses (see scripts/build_map_data.py) -- one source of
truth, not a second copy fetched from elsewhere.

Usage: python3 scripts/build_office_export.py
Output: office-export.html (git-ignored, disposable)
"""
import json
import os

from shapely.geometry import shape, Point

BASE = os.path.dirname(__file__)
CHAMBER_BUILDINGS = os.path.join(BASE, "..", "map", "data", "chamber_buildings.geojson")
BIBB_BOUNDARY = os.path.join(BASE, "..", "data", "county_boundary", "bibb_county.geojson")
OUT_HTML = os.path.join(BASE, "..", "office-export.html")


def filter_to_bibb(members_geojson, bibb_geojson):
    bibb_polygon = shape(bibb_geojson["features"][0]["geometry"])
    kept, dropped = [], []
    for f in members_geojson["features"]:
        lon, lat = f["geometry"]["coordinates"]
        (kept if bibb_polygon.contains(Point(lon, lat)) else dropped).append(f)
    print(f"restricted to Bibb County: kept {len(kept)}/{len(members_geojson['features'])} points "
          f"({len(dropped)} outside Bibb's boundary excluded)")
    return {"type": "FeatureCollection", "features": kept}


def main():
    with open(CHAMBER_BUILDINGS) as f:
        members_geojson = json.load(f)
    with open(BIBB_BOUNDARY) as f:
        bibb_geojson = json.load(f)

    bibb_only_members = filter_to_bibb(members_geojson, bibb_geojson)

    html = HTML_TEMPLATE.replace("__MEMBERS_GEOJSON__", json.dumps(bibb_only_members))
    html = html.replace("__BIBB_GEOJSON__", json.dumps(bibb_geojson))

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

    // Fit tight to Bibb County's own extent -- nothing outside it is even
    // in the data anymore, so this is the natural crop.
    const bounds = new maplibregl.LngLatBounds();
    for (const ring of BIBB_GEOJSON.features[0].geometry.coordinates) {
        for (const pt of ring) bounds.extend(pt);
    }
    map.fitBounds(bounds, { padding: 50, duration: 0 });

    window.__mapReady = true;
});
</script>

</body>
</html>
"""

if __name__ == "__main__":
    main()
