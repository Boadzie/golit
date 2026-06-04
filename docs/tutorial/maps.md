# Maps & GIS

A map is a reactive view like any other — a control rebuilds it. Move a slider that
narrows your data and Golit re-runs only the filter and the map node; everything else is
a memo hit. No special map widget, no callback wiring: a view returns a map and the
fragment swaps in place on the initial load, on POST, and on SSE pushes alike.

Golit renders **vector data** (GeoDataFrames) and **raster data** (georeferenced arrays)
with **native MapLibre GL**, plus **DuckDB spatial SQL** over your frames.

Install the extras:

```bash
pip install "golit[gis]"          # vector: geo_map, spatial_sql, explore
pip install "golit[gis-raster]"   # raster: gis.raster / gis.rgb (rasterio / rioxarray / xarray)
pip install "golit[gis-tiles]"    # tiled rasters: gis.tiles (rio-tiler, large COGs)
```

`gis` pulls in GeoPandas, Shapely, pyproj, and folium. MapLibre GL itself loads from a CDN —
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
        basemap="positron",                  # vector preset (the default); see below
        height="460px",
    )
```

The color mapping is emitted as a MapLibre **style expression**, so the GPU does the
data→color step client-side — the server ships the GeoJSON and the rules, not a
pre-colored image. Polygons get a fill layer, lines a line layer, points a circle layer.

When `color` is set, a **legend** is overlaid automatically — a gradient bar for a numeric
choropleth, swatches for a categorical one. It's plain server-rendered markup (no client
runtime); pass `legend=False` to hide it.

### Basemaps

The default basemap is a free **[OpenFreeMap](https://openfreemap.org/)** vector style
(`positron`) — OpenStreetMap-based, **no API key, no rate limits**, and self-hostable.
`basemap` accepts:

- a **vector preset** — `"positron"` (the default, light/neutral — best under data),
  `"liberty"`, `"bright"`, `"dark"`;
- a **raster preset** — `"osm"`, `"carto-light"`, `"carto-dark"`;
- `"none"` (flat background), a full MapLibre **style `dict`**, or any **style-URL**
  string (`basemap="https://…/style.json"` — the data is overlaid once it loads).

For production, self-host the tiles rather than leaning on the public instance.
`tooltip_trigger="hover"` shows the popup on hover instead of click, and `fit_padding`
controls the bounds-fit inset.

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

## `raster` — georeferenced arrays

`gis.raster` renders a raster — a **rioxarray/xarray `DataArray`**, a **GeoTIFF path**, or a
NumPy 2-D array with explicit `bounds=[w, s, e, n]` — as a native MapLibre image layer. A
DataArray is reprojected to lon/lat via its `.rio` CRS; a single band is colormapped to a
PNG, overlaid on the basemap, and framed. A colorbar legend is overlaid automatically.

```python
from golit import select, slider


@app.view
def map(elevation,                                  # a georeferenced DataArray
        cmap: str = select(["terrain", "viridis", "magma"], default="terrain"),
        opacity: int = slider(20, 100, default=85, step=5)):
    return gis.raster(elevation, cmap=cmap, opacity=opacity / 100, label="Elevation (m)")
```

`cmap` is one of `viridis`, `magma`, `blues`, `terrain`, `greys` (dependency-free — no
matplotlib); `vmin`/`vmax` set the range and NaN nodata is transparent. Large rasters are
downsampled to `max_size` px on the long edge to keep the fragment small. A view may also
just `return` a georeferenced `DataArray`. Needs `pip install "golit[gis-raster]"`.

## `rgb` — true/false-color satellite composites

`gis.rgb` renders a **multiband** raster as an RGB composite — the natural shape of
satellite imagery. It takes the same inputs as `raster` (a multiband `DataArray`, a
multiband GeoTIFF path, or a NumPy array + `bounds`), plus a `bands` triple naming the
three source bands to map to red, green, blue:

```python
from golit import select, slider


@app.view
def scene(stack,                                         # a multiband DataArray
          combo: str = select(["natural", "false-color"], default="natural"),
          gamma: int = slider(50, 200, default=100, step=10)):
    bands = (0, 1, 2) if combo == "natural" else (3, 0, 1)   # NIR·R·G highlights vegetation
    return gis.rgb(stack, bands=bands, gamma=gamma / 100)
```

Each band is contrast-stretched **independently** — by default to its 2nd–98th percentiles
(robust to outliers), or to an explicit `vmin`/`vmax` (a scalar for all three, or a
3-sequence per band). `gamma` brightens (`>1`) or darkens (`<1`) the midtones; pixels that
are nodata in any band are transparent. Band-first `(band, y, x)` (the rasterio/rioxarray
layout) and channel-last `(y, x, band)` arrays are both accepted. Like `raster`, the
composite is a single PNG image layer over the basemap — no client charting runtime.

## `tiles` — very large rasters, streamed

`raster` and `rgb` ship the whole array as one PNG — perfect up to a point, but a
multi-gigabyte scene can't cross the wire that way. `gis.tiles` serves a **Cloud-Optimized
GeoTIFF** (a local path or a remote `http(s)` URL) through a built-in tile route: rio-tiler
reads only the `z/x/y` window each MapLibre request needs — low zooms hit the COG's
overviews, high zooms the native blocks — so the full raster never loads or transmits.

```python
@app.view
def scene(layer: str = select(["elevation", "landcover"], default="elevation")):
    return gis.tiles(f"/data/{layer}.tif", cmap="terrain")   # a COG path or URL
```

`bands` selects the source band(s): omit (or one index) for a single colormapped band
(`cmap` is any rio-tiler colormap), three indexes for an RGB composite. Each band is
contrast-stretched to `rescale=(min, max)` — or automatically to the COG's 2nd–98th
percentile when omitted — and the data's footprint frames the camera. Needs
`pip install "golit[gis-tiles]"` (rio-tiler).

The tile route (`/gis/tiles/{token}/{z}/{x}/{y}`) is part of every Golit server. A view
registers its source under an opaque token; tiles are served by the **same worker** that
rendered the view (Golit's usual session affinity), and the token is a hash — never a path —
so a tile request can only reach a source a view has already opened.

!!! note "GIS phases"
    Phase 1 is vector (GeoDataFrames, spatial SQL); phase 2 is the single-array `raster`
    overlay; phase 2.5 adds multiband `rgb` composites and `tiles` for very large COGs.

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
