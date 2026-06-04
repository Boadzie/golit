# GIS

`golit.gis` — reactive maps as ordinary views. Phase 1 covers vector data with native
MapLibre GL rendering plus DuckDB spatial SQL. Install with `pip install "golit[gis]"`;
everything heavy is imported lazily, so `import golit` never pulls it in. See the
[Maps & GIS tutorial](../tutorial/maps.md) for usage.

## maplibre

A native MapLibre GL map from a style and a camera.

::: golit.gis.maplibre

## geo_map

A GeoPandas `GeoDataFrame` straight to a MapLibre choropleth / line / point map. A view
may also just *return* a `GeoDataFrame` — `render_value` routes it here with defaults.

::: golit.gis.geo_map

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
