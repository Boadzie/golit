# Maps & GIS

A map is a reactive view like any other — a control rebuilds it. Move a slider that
narrows your data and Golit re-runs only the filter and the map node; everything else is
a memo hit. No special map widget, no callback wiring: a view returns a map and the
fragment swaps in place on the initial load, on POST, and on SSE pushes alike.

Phase 1 covers **vector data** rendered with **native MapLibre GL**, plus **DuckDB
spatial SQL**. (Raster — rasterio/xarray tile layers — is phase 2.)

Install the extra:

```bash
pip install "golit[gis]"
```

It pulls in GeoPandas, Shapely, pyproj, and folium. MapLibre GL itself loads from a CDN —
there's no Python map package and nothing to bundle. Everything heavy is imported lazily
*inside* `golit.gis`, so `import golit` never pays for it.

## Return a GeoDataFrame

The shortest path: a view returns a GeoPandas `GeoDataFrame` and Golit renders it as a
native map. It reprojects to WGS84 if needed, picks a fill/line/circle layer from the
geometry type, and frames the data's bounds.

```python
import geopandas as gpd
from golit import App, create_app, select

app = App(title="Districts")


@app.source
def districts() -> gpd.GeoDataFrame:
    return gpd.read_file("districts.geojson")


@app.reactive
def selected(districts, zone: str = select(["All", "North", "South"], default="All")):
    return districts if zone == "All" else districts[districts["zone"] == zone]


@app.view
def map(selected):
    return selected            # a GeoDataFrame → a MapLibre map
```

## `geo_map` — choropleths, tooltips, basemaps

For control over the styling, call `gis.geo_map` explicitly. `color` names a column to
drive the fill — a blue ramp for a numeric column (a **choropleth**), a categorical
palette for a text one. `tooltip` shows feature properties on click. `basemap` is a
preset or a full MapLibre style dict, and `fit` frames the data.

```python
import golit.gis as gis


@app.view
def map(selected):
    return gis.geo_map(
        selected,
        color="population",                 # numeric → choropleth ramp
        tooltip=["name", "population"],      # click a feature to see these
        basemap="light",                    # "default" | "light" | "dark" | "osm" | "none"
        height="460px",
    )
```

The color mapping is emitted as a MapLibre **style expression**, so the GPU does the
data→color step client-side — the server ships the GeoJSON and the rules, not a
pre-colored image. Polygons get a fill layer, lines a line layer, points a circle layer.

When `color` is set, a **legend** is overlaid automatically — a gradient bar for a numeric
choropleth, swatches for a categorical one. It's plain server-rendered markup (no client
runtime); pass `legend=False` to hide it.

`basemap` also accepts a **vector style-URL** (`basemap="https://…/style.json"`) — the data
is overlaid once the remote style loads — and `tooltip_trigger="hover"` shows the popup on
hover instead of click. `fit_padding` controls the bounds-fit inset.

## `maplibre` — a native map from a style

When you want a base map for its own sake — a vector tile style, 3D buildings, terrain —
build it from a style and a camera. `style` is a style-URL string or a full MapLibre
style dict; `pitch` and `bearing` tilt and rotate for 3D.

```python
@app.view
def city(center):
    return gis.maplibre(
        "https://demotiles.maplibre.org/style.json",
        center=[center["lng"], center["lat"]],
        zoom=11,
        pitch=45,           # tilt; pair with fill-extrusion / terrain layers for 3D
    )
```

A MapLibre map owns a WebGL context, so Golit disposes the old map when its fragment is
replaced — you can drive a map from a slider continuously without leaking contexts.

## DuckDB spatial SQL

A reactive node can be written as spatial SQL. `gis.spatial_sql` loads the DuckDB
`spatial` extension (so `ST_*` functions work) and runs the query over your named frames,
returning **Polars**. It needs only the `sql` extra; DuckDB downloads the extension on
first use.

```python
from golit import slider


@app.reactive
def nearby(places, radius_km: float = slider(1, 50, default=10)):
    return gis.spatial_sql(
        "SELECT name, ST_AsWKB(geom) AS geometry FROM p "
        f"WHERE ST_DWithin(geom, ST_Point(-0.19, 5.6), {radius_km} / 111.0)",
        p=places,
    )
```

Because `spatial_sql` returns a plain frame (geometry as a WKB/WKT column), bridge it to a
map with `gis.to_geo` — or just point `geo_map` at the geometry column directly:

```python
@app.view
def map(nearby):                       # nearby is the spatial_sql frame above
    return gis.geo_map(nearby, geometry="geometry", color="name")
    # equivalently: gis.geo_map(gis.to_geo(nearby, geometry="geometry"), color="name")
```

`gis.to_geo(frame, geometry="geometry")` parses a WKB-bytes, WKT-text, or shapely geometry
column into a `GeoDataFrame` (defaulting to EPSG:4326). Select geometry as `ST_AsWKB(geom)`
(or `ST_AsText(geom)`) in the query.

## The folium escape hatch

Want the folium ecosystem — marker clusters, layer control, plugins? `gis.explore`
delegates to `gdf.explore(**kwargs)` and embeds the result. It ships folium's client
runtime (versus `geo_map`'s zero-runtime native render), but swaps cleanly like any
fragment:

```python
@app.view
def map(selected):
    return gis.explore(selected, column="population", cmap="Blues")
```

## Full example

The [`geo_explorer`](https://github.com/boadzie/golit/tree/main/examples/geo_explorer)
example loads a bundled GeoJSON of district polygons; a zone filter and a population
slider drive a native MapLibre choropleth. Move a control and only the filter, map, and
KPIs recompute — the data-only overview never re-renders. That selective recompute is the
whole point, maps included.

## Next

**[UI components](ui-components.md)** — cards, metrics, tabs, and more, all server-rendered.
