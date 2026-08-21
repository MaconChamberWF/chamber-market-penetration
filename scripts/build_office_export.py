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
import glob
import gzip
import json
import os

from shapely.geometry import box, mapping, shape, Point

BASE = os.path.dirname(__file__)
CHAMBER_BUILDINGS = os.path.join(BASE, "..", "map", "data", "chamber_buildings.geojson")
BIBB_BOUNDARY = os.path.join(BASE, "..", "data", "county_boundary", "bibb_county.geojson")
MS_FOOTPRINTS_GLOB = os.path.join(BASE, "..", "data", "ms_footprints", "*.csv.gz")
OUT_HTML = os.path.join(BASE, "..", "office-export.html")
OUT_HTML_DOWNTOWN = os.path.join(BASE, "..", "office-export-downtown.html")

# Downtown Macon core (around Poplar/Cherry St and the Ocmulgee River) --
# a fixed, tight framing purely to show the poster palette's building
# fills. OpenStreetMap (and so OpenFreeMap's tiles, built from it) turned
# out to have ZERO building footprints anywhere in Bibb County -- checked
# 5 spread-out locations at zoom 15.3, all empty, so this isn't a zoom or
# style issue. Real building geometry instead comes from the Microsoft
# Building Footprints data already sitting in data/ms_footprints/
# (currently unused by the live map, which switched to point-rendering --
# see build_map_data.py's docstring -- but the raw footprints are exactly
# what a building-filled poster needs). Not meant to show "most
# investors" the way the county view is -- this is a second, separate
# image, by Reid's own call.
DOWNTOWN_CENTER = [-83.6324, 32.8407]
DOWNTOWN_ZOOM = 15.3
DOWNTOWN_PAD_DEG = 0.03  # ~generous margin around DOWNTOWN_CENTER at zoom 15.3


def load_ms_footprints_in_bbox(bbox):
    """bbox = (west, south, east, north). Streams every quadkey_*.csv.gz
    file (each line is one GeoJSON Feature -- Microsoft's actual on-disk
    format despite the .csv extension) and keeps only buildings whose
    first vertex falls in bbox. That's an approximation (not a true
    polygon-in-bbox test), acceptable here since this layer is purely
    visual flavor for the downtown poster, not a boundary computation
    anything downstream depends on. ~756k total rows across all files,
    ~9.4k typically match a zoom-15.3-sized bbox -- plenty fast to stream
    in a few seconds, no need to pre-index."""
    west, south, east, north = bbox
    features = []
    for path in sorted(glob.glob(MS_FOOTPRINTS_GLOB)):
        with gzip.open(path, "rt") as f:
            for line in f:
                try:
                    feat = json.loads(line)
                except json.JSONDecodeError:
                    continue
                lon, lat = feat["geometry"]["coordinates"][0][0]
                if west <= lon <= east and south <= lat <= north:
                    features.append({"type": "Feature", "geometry": feat["geometry"], "properties": {}})
    print(f"MS Building Footprints: {len(features)} buildings in downtown bbox {bbox}")
    return {"type": "FeatureCollection", "features": features}


def build_outside_mask(bibb_geojson):
    """A single polygon-with-a-hole: a generous box around Bibb County,
    minus Bibb's own shape. Rendered as an opaque fill on top of
    everything else, it blanks out roads/parks/water/etc. beyond the
    county line -- "remove any visual detail outside of Bibb County" --
    without needing per-layer clip logic on every basemap layer. Padding
    is degrees, not km, but 1 degree (~110km at this latitude) comfortably
    covers any framing this script uses, including the county-wide fitBounds."""
    bibb_polygon = shape(bibb_geojson["features"][0]["geometry"])
    minx, miny, maxx, maxy = bibb_polygon.bounds
    pad = 1.0
    mask_box = box(minx - pad, miny - pad, maxx + pad, maxy + pad)
    mask_geom = mask_box.difference(bibb_polygon)
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": mapping(mask_geom), "properties": {}}]}


def filter_to_bibb(members_geojson, bibb_geojson):
    bibb_polygon = shape(bibb_geojson["features"][0]["geometry"])
    kept, dropped = [], []
    for f in members_geojson["features"]:
        lon, lat = f["geometry"]["coordinates"]
        (kept if bibb_polygon.contains(Point(lon, lat)) else dropped).append(f)
    print(f"restricted to Bibb County: kept {len(kept)}/{len(members_geojson['features'])} points "
          f"({len(dropped)} outside Bibb's boundary excluded)")
    return {"type": "FeatureCollection", "features": kept}


# Draw order within a single circle layer follows the source's feature
# array order, not tier -- so wherever points overlap (downtown especially),
# whichever bucket happened to come later in the raw export data won by
# accident. Sorting the array itself, lowest tier first, fixes that: higher
# tiers always draw on top in a cluster instead of getting buried.
TIER_DRAW_PRIORITY = {
    "additional_listing": 0,
    "tier1_micro_basic": 1,
    "tier2_catalyst": 2,
    "tier3_community": 3,
    "tier4_regional_stakeholder": 4,
    "tier5_driver_investor": 5,
}


def sort_by_tier_priority(members_geojson):
    features = sorted(
        members_geojson["features"],
        key=lambda f: TIER_DRAW_PRIORITY.get(f["properties"]["bucket"], 0),
    )
    return {"type": "FeatureCollection", "features": features}


def main():
    with open(CHAMBER_BUILDINGS) as f:
        members_geojson = json.load(f)
    with open(BIBB_BOUNDARY) as f:
        bibb_geojson = json.load(f)

    bibb_only_members = filter_to_bibb(members_geojson, bibb_geojson)
    bibb_only_members = sort_by_tier_priority(bibb_only_members)
    members_json = json.dumps(bibb_only_members)
    bibb_json = json.dumps(bibb_geojson)
    mask_json = json.dumps(build_outside_mask(bibb_geojson))

    # County-wide: the main deliverable, fit to all of Bibb County.
    county_view_js = """
    const bounds = new maplibregl.LngLatBounds();
    for (const ring of BIBB_GEOJSON.features[0].geometry.coordinates) {
        for (const pt of ring) bounds.extend(pt);
    }
    map.fitBounds(bounds, { padding: 50, duration: 0 });
    """
    investor_count = len(bibb_only_members["features"])
    html = HTML_TEMPLATE.replace("__MEMBERS_GEOJSON__", members_json)
    html = html.replace("__BIBB_GEOJSON__", bibb_json)
    html = html.replace("__MASK_GEOJSON__", mask_json)
    html = html.replace("__INITIAL_CENTER__", "[-83.65, 32.85]")
    html = html.replace("__INITIAL_ZOOM__", "9")
    html = html.replace("__VIEW_JS__", county_view_js)
    html = html.replace("__MS_BUILDINGS_GEOJSON__", "null")
    html = html.replace("__MS_BUILDINGS_JS__", "")
    html = html.replace("__CHROME_CSS__", SIDEBAR_CSS)
    html = html.replace("__CHROME_HTML__", SIDEBAR_HTML.replace("__INVESTOR_COUNT__", str(investor_count)))
    with open(OUT_HTML, "w") as f:
        f.write(html)
    print(f"wrote {OUT_HTML}")

    # Downtown detail: a second, separate image purely to show the poster
    # palette's building fills via the Microsoft footprints data (see
    # module docstring for why OSM's own building layer can't be used
    # here). Fixed center/zoom, no fitBounds -- not trying to frame any
    # particular set of points.
    dt_bbox = (
        DOWNTOWN_CENTER[0] - DOWNTOWN_PAD_DEG, DOWNTOWN_CENTER[1] - DOWNTOWN_PAD_DEG,
        DOWNTOWN_CENTER[0] + DOWNTOWN_PAD_DEG, DOWNTOWN_CENTER[1] + DOWNTOWN_PAD_DEG,
    )
    ms_buildings_geojson = load_ms_footprints_in_bbox(dt_bbox)
    ms_buildings_js = """
    map.addSource("ms-buildings", { type: "geojson", data: MS_BUILDINGS_GEOJSON });
    map.addLayer({
        id: "ms-buildings-fill", type: "fill", source: "ms-buildings",
        paint: { "fill-color": POSTER.building, "fill-opacity": 0.9 },
    });
    """
    html_dt = HTML_TEMPLATE.replace("__MEMBERS_GEOJSON__", members_json)
    html_dt = html_dt.replace("__BIBB_GEOJSON__", bibb_json)
    html_dt = html_dt.replace("__MASK_GEOJSON__", mask_json)
    html_dt = html_dt.replace("__INITIAL_CENTER__", json.dumps(DOWNTOWN_CENTER))
    html_dt = html_dt.replace("__INITIAL_ZOOM__", str(DOWNTOWN_ZOOM))
    html_dt = html_dt.replace("__VIEW_JS__", "")
    html_dt = html_dt.replace("__MS_BUILDINGS_GEOJSON__", json.dumps(ms_buildings_geojson))
    html_dt = html_dt.replace("__MS_BUILDINGS_JS__", ms_buildings_js)
    html_dt = html_dt.replace("__CHROME_CSS__", FLOATING_PANEL_CSS)
    html_dt = html_dt.replace("__CHROME_HTML__", FLOATING_PANEL_HTML)
    with open(OUT_HTML_DOWNTOWN, "w") as f:
        f.write(html_dt)
    print(f"wrote {OUT_HTML_DOWNTOWN}")


# Downtown detail image: the small floating legend from earlier
# iterations, unchanged -- that image was never meant to dedicate real
# layout space to itself, it's a corner annotation on a map that's the
# whole point of the frame.
FLOATING_PANEL_CSS = """
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
    .boundary-swatch { width: 18px; height: 3px; background: #3a332a; border-radius: 2px; flex-shrink: 0; }
"""

FLOATING_PANEL_HTML = """
<div id="map"></div>

<div class="panel">
    <div class="panel-title">Chamber of Commerce Investors</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#06aed5"></span>Micro / Basic Membership</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#3a86ff"></span>Business Catalyst</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#8338ec"></span>Community Advocate / Partner</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#fb5607"></span>Regional Influencer / Key Stakeholder</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#d62828"></span>Economic Driver / Leading Investor</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#6b7280"></span>Additional listing (extra location/brand)</div>
    <div class="boundary-key"><span class="boundary-swatch"></span>Bibb County</div>
</div>
"""

# County-wide image: the main deliverable. A full-height title/legend
# sidebar instead of a small floating box, so the map itself gets pushed
# to the right and the legend gets real room to breathe -- Reid's ask.
SIDEBAR_CSS = """
    body { display: flex; }
    #map { flex: 1 1 auto; height: 100%; position: relative; }
    .sidebar {
        width: 34%; max-width: 560px; height: 100%; flex-shrink: 0;
        background: #1c1815; color: #ece7dc;
        padding: 56px 44px; display: flex; flex-direction: column;
    }
    .eyebrow {
        font-size: 0.8rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
        color: #06aed5; margin-bottom: 18px; display: flex; align-items: center; gap: 10px;
    }
    .eyebrow::before { content: ''; width: 26px; height: 3px; background: #06aed5; border-radius: 2px; }
    .sidebar .title {
        font-family: ui-serif, Georgia, "Times New Roman", serif; font-weight: 600;
        font-size: 3rem; line-height: 1.08; letter-spacing: -0.01em; color: #fff; margin-bottom: 20px;
    }
    .sidebar .subtitle { font-size: 1.05rem; color: #b8b0a0; line-height: 1.55; }
    .sidebar .subtitle b { color: #fff; font-variant-numeric: tabular-nums; }
    .legend-heading {
        font-size: 0.78rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
        color: #8a8272; margin: 40px 0 14px; padding-top: 28px; border-top: 1px solid #322d26;
    }
    .sidebar .legend-row { display: flex; align-items: center; gap: 15px; padding: 8px 0; font-size: 1.08rem; }
    .sidebar .legend-swatch { width: 20px; height: 20px; border-radius: 6px; flex-shrink: 0; }
    .sidebar .boundary-key {
        display: flex; align-items: center; gap: 15px; margin-top: 22px;
        padding-top: 22px; border-top: 1px solid #322d26; font-size: 1.08rem;
    }
    .sidebar .boundary-swatch { width: 28px; height: 3px; background: #ece7dc; border-radius: 2px; flex-shrink: 0; }
    .sidebar-footer { margin-top: auto; padding-top: 28px; font-size: 0.74rem; color: #6b6456; }
"""

SIDEBAR_HTML = """
<div class="sidebar">
    <div class="eyebrow">Greater Macon Chamber of Commerce</div>
    <div class="title">Where Macon<br>Invests</div>
    <div class="subtitle"><b>__INVESTOR_COUNT__</b> chamber investors located across Bibb County, Georgia.</div>
    <div class="legend-heading">Investor Tier</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#06aed5"></span>Micro / Basic Membership</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#3a86ff"></span>Business Catalyst</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#8338ec"></span>Community Advocate / Partner</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#fb5607"></span>Regional Influencer / Key Stakeholder</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#d62828"></span>Economic Driver / Leading Investor</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#6b7280"></span>Additional listing (extra location/brand)</div>
    <div class="boundary-key"><span class="boundary-swatch"></span>Bibb County boundary</div>
    <div class="sidebar-footer">Source: Chamber member directory, geocoded</div>
</div>
<div id="map"></div>
"""

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
    __CHROME_CSS__
</style>
</head>
<body>

__CHROME_HTML__

<script>
const CHAMBER_BUCKET_COLOR = {
    tier1_micro_basic: "#06aed5",
    tier2_catalyst: "#3a86ff",
    tier3_community: "#8338ec",
    tier4_regional_stakeholder: "#fb5607",
    tier5_driver_investor: "#d62828",
    additional_listing: "#6b7280",
};
const FILL_COLOR_EXPR = ["match", ["get", "bucket"], ...Object.entries(CHAMBER_BUCKET_COLOR).flat(), "#ffffff"];

const MEMBERS_GEOJSON = __MEMBERS_GEOJSON__;
const BIBB_GEOJSON = __BIBB_GEOJSON__;
// A box-minus-Bibb polygon (with Bibb as the hole) -- painted opaque on
// top of the basemap to blank out everything beyond the county line.
const MASK_GEOJSON = __MASK_GEOJSON__;
// Real Macon building footprints (Microsoft Building Footprints) --
// null for the county-wide image, a FeatureCollection for the downtown
// one. OSM has no buildings mapped in Bibb County at all, so this
// replaces rather than supplements the style's own "building" layer.
const MS_BUILDINGS_GEOJSON = __MS_BUILDINGS_GEOJSON__;

const map = new maplibregl.Map({
    container: "map",
    style: "https://tiles.openfreemap.org/styles/liberty",
    center: __INITIAL_CENTER__,
    zoom: __INITIAL_ZOOM__,
    interactive: false,
});

// Poster palette -- a deliberate small set (not copied from any
// reference image), applied to the Liberty style's real layers via
// setPaintProperty rather than swapping basemaps. Layer IDs below were
// read directly off map.getStyle().layers, not guessed.
const POSTER = {
    background:  "#f2ede1", // warm cream land
    parkFill:    "#c9dbb0", parkLine: "#a8c48a",
    woodFill:    "#b9d1a0",
    grassFill:   "#d3e3bd",
    pitchFill:   "#c9dbb0",
    cemeteryFill:"#c7d3b8",
    institFill:  "#e3dfd2", // school/hospital grounds -- neutral, not a park
    water:       "#a9cbe8",
    waterLine:   "#8ab4d9",
    building:    "#a89478", // needs real contrast against the cream background -- a close tan/cream (#c9b8a0) rendered as near-invisible outlines-only in testing
    roadFill:    "#fdfaf1",
    roadCasing:  "#c9bfa8",
    rail:        "#a89c86",
    aeroway:     "#e5e1d5",
    outsideMask: "#ffffff",
    boundary:    "#3a332a", // dark warm charcoal, not the old gold -- reads as a clean cartographic line instead of a highlighter
};

map.on("load", () => {
    // Declutter: hide every label/icon layer (MapLibre styles put place
    // names, road names, and POI icons in "symbol"-type layers) so the
    // basemap reads as a clean reference map, not a street-navigation app.
    for (const layer of map.getStyle().layers) {
        if (layer.type === "symbol") map.setLayoutProperty(layer.id, "visibility", "none");
    }

    map.setPaintProperty("background", "background-color", POSTER.background);
    map.setPaintProperty("landuse_residential", "fill-color", POSTER.background);

    map.setPaintProperty("park", "fill-color", POSTER.parkFill);
    map.setPaintProperty("park_outline", "line-color", POSTER.parkLine);
    map.setPaintProperty("landcover_wood", "fill-color", POSTER.woodFill);
    map.setPaintProperty("landcover_grass", "fill-color", POSTER.grassFill);
    map.setPaintProperty("landuse_pitch", "fill-color", POSTER.pitchFill);
    map.setPaintProperty("landuse_track", "fill-color", POSTER.pitchFill);
    map.setPaintProperty("landuse_cemetery", "fill-color", POSTER.cemeteryFill);
    map.setPaintProperty("landuse_school", "fill-color", POSTER.institFill);
    map.setPaintProperty("landuse_hospital", "fill-color", POSTER.institFill);

    map.setPaintProperty("water", "fill-color", POSTER.water);
    map.setPaintProperty("waterway_river", "line-color", POSTER.waterLine);
    map.setPaintProperty("waterway_other", "line-color", POSTER.waterLine);

    // OSM has zero building footprints anywhere in Bibb County (checked
    // 5 locations county-wide) -- both style layers are empty here
    // regardless, hidden explicitly for clarity rather than left to rely
    // on that emptiness. Real buildings (downtown image only) come from
    // MS_BUILDINGS_GEOJSON instead, added below.
    map.setLayoutProperty("building", "visibility", "none");
    map.setLayoutProperty("building-3d", "visibility", "none");

    // Road hierarchy (motorway > trunk/primary > secondary/tertiary >
    // minor) is already encoded in Liberty's width expressions per
    // layer/zoom -- only recoloring, not re-widening.
    const roadFillLayers = [
        "road_motorway", "road_trunk_primary", "road_secondary_tertiary",
        "road_minor", "road_link", "road_service_track", "road_path_pedestrian",
    ];
    const roadCasingLayers = [
        "road_motorway_casing", "road_trunk_primary_casing", "road_secondary_tertiary_casing",
        "road_minor_casing", "road_link_casing", "road_service_track_casing",
    ];
    for (const id of roadFillLayers) map.setPaintProperty(id, "line-color", POSTER.roadFill);
    for (const id of roadCasingLayers) map.setPaintProperty(id, "line-color", POSTER.roadCasing);
    map.setPaintProperty("road_major_rail", "line-color", POSTER.rail);
    map.setPaintProperty("road_transit_rail", "line-color", POSTER.rail);
    map.setPaintProperty("aeroway_fill", "fill-color", POSTER.aeroway);

    // The base style's own state/country boundary lines aren't our focus
    // (Bibb's own boundary, added below, is) -- muted low so they don't
    // compete with it.
    map.setPaintProperty("boundary_2", "line-opacity", 0.25);
    map.setPaintProperty("boundary_3", "line-opacity", 0.15);

    __MS_BUILDINGS_JS__

    // Blank out everything beyond Bibb County's own line -- painted after
    // the basemap/buildings so it covers them, before the boundary line
    // and investor dots so those still draw crisply on top.
    map.addSource("outside-mask", { type: "geojson", data: MASK_GEOJSON });
    map.addLayer({
        id: "outside-mask-fill", type: "fill", source: "outside-mask",
        paint: { "fill-color": POSTER.outsideMask, "fill-opacity": 1 },
    });

    map.addSource("bibb-county", { type: "geojson", data: BIBB_GEOJSON });
    map.addLayer({
        id: "bibb-county-line", type: "line", source: "bibb-county",
        paint: { "line-color": POSTER.boundary, "line-width": 2.5 },
    });

    map.addSource("chamber-members", { type: "geojson", data: MEMBERS_GEOJSON });
    map.addLayer({
        id: "chamber-members-halo", type: "circle", source: "chamber-members",
        paint: { "circle-radius": 7.5, "circle-color": "#ffffff", "circle-opacity": 0.95 },
    });
    map.addLayer({
        id: "chamber-members-dot", type: "circle", source: "chamber-members",
        paint: { "circle-radius": 5.5, "circle-color": FILL_COLOR_EXPR },
    });

    __VIEW_JS__

    window.__mapReady = true;
});
</script>

</body>
</html>
"""

if __name__ == "__main__":
    main()
