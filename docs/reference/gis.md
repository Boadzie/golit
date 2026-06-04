# GIS

`golit.gis` — reactive maps as ordinary views: vector data (GeoDataFrames), raster data
(georeferenced arrays), and DuckDB spatial SQL, all rendered with native MapLibre GL.
Install with `pip install "golit[gis]"` (vector) and `"golit[gis-raster]"` (raster);
everything heavy is imported lazily, so `import golit` never pulls it in. See the
[Maps & GIS tutorial](../tutorial/maps.md) for usage.

## maplibre

A native MapLibre GL map from a style and a camera.

::: golit.gis.maplibre

## geo_map

A GeoPandas `GeoDataFrame` straight to a MapLibre choropleth / line / point map. A view
may also just *return* a `GeoDataFrame` — `render_value` routes it here with defaults.

::: golit.gis.geo_map

## raster

Render a georeferenced raster (rioxarray/xarray `DataArray`, GeoTIFF path, or NumPy array + bounds) as a native MapLibre image layer.

::: golit.gis.raster

## rgb

Render a multiband raster (satellite imagery) as a true/false-color RGB composite — three selected bands, each contrast-stretched independently, as a MapLibre image layer.

::: golit.gis.rgb

## tiles

Stream a very large Cloud-Optimized GeoTIFF as on-demand `z/x/y` map tiles via rio-tiler — only the visible window crosses the wire. Needs `pip install "golit[gis-tiles]"`.

::: golit.gis.tiles

## terrain

Run a WhiteboxTools terrain operation (hillshade, slope, aspect, fill, flow accumulation, …) on a DEM, returning a georeferenced `DataArray` that feeds `raster`/`tiles`. Needs `pip install "golit[gis-terrain]"`.

::: golit.gis.terrain

## ee_layer

Overlay a Google Earth Engine image as live XYZ tiles — EE renders the imagery, Golit points a MapLibre raster source at the tile URL from `getMapId(vis)`. Needs `pip install "golit[gis-ee]"` and an Earth Engine account.

::: golit.gis.ee_layer

## explore

The folium/leafmap escape hatch — embed `gdf.explore()` as a swappable fragment.

::: golit.gis.explore

## spatial_sql

DuckDB `ST_*` SQL over Polars/GeoJSON sources, returning Polars (bridge to `geo_map` with `to_geo`).

::: golit.gis.spatial_sql

## to_geo

Turn a frame with a WKB/WKT/shapely geometry column into a `GeoDataFrame` — the bridge from `spatial_sql` to `geo_map`.

::: golit.gis.to_geo

## is_geodataframe

::: golit.gis.is_geodataframe

## is_dataarray

::: golit.gis.is_dataarray
