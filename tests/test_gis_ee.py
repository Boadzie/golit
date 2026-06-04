"""GIS phase 3: Earth Engine overlays — gis.ee_layer turns an ee.Image's getMapId() into a
MapLibre raster tile source.

ee_layer imports no Earth Engine itself (it duck-types getMapId), so most tests run with a
fake image and need no credentials. One test exercises the real earthengine-api getMapId
return shape (ee.data.TileFetcher), skipped if the client isn't installed. A *live* tile
paint needs a Google Earth Engine account and is out of scope here."""

from __future__ import annotations

import html
import json

import pytest
from golit import gis


def _spec_of(fragment: str) -> dict:
    marker = 'data-chart-spec="'
    start = fragment.index(marker) + len(marker)
    end = fragment.index('"', start)
    return json.loads(html.unescape(fragment[start:end]))


def _raster_source(spec: dict) -> dict:
    return (spec.get("overlay") or spec["style"])["sources"]["golit-raster"]


class _FakeFetcher:
    url_format = "https://earthengine.googleapis.com/v1/projects/p/maps/abc/tiles/{z}/{x}/{y}"


class _FakeImage:
    """An ee.Image stand-in: records the vis it was asked for and returns a getMapId dict."""

    def __init__(self, map_id: dict) -> None:
        self._map_id = map_id
        self.requested_vis: dict | None = None

    def getMapId(self, vis: dict) -> dict:  # noqa: N802 - mirrors the ee.Image method name
        self.requested_vis = vis
        return self._map_id


def test_ee_layer_builds_a_raster_tile_source_from_getmapid() -> None:
    img = _FakeImage({"tile_fetcher": _FakeFetcher(), "mapid": "abc", "token": ""})
    spec = _spec_of(gis.ee_layer(img, vis={"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}))
    source = _raster_source(spec)
    assert source["type"] == "raster"
    assert source["tiles"] == [_FakeFetcher.url_format]
    assert "{z}/{x}/{y}" in source["tiles"][0]
    assert source["tileSize"] == 256
    assert img.requested_vis == {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}


def test_ee_layer_opacity_attribution_center_zoom() -> None:
    img = _FakeImage({"tile_fetcher": _FakeFetcher()})
    spec = _spec_of(
        gis.ee_layer(img, opacity=0.6, attribution="EE", center=[-0.15, 5.62], zoom=10)
    )
    layer = next(
        layer_ for layer_ in (spec.get("overlay") or spec["style"])["layers"]
        if layer_["id"] == "golit-raster"
    )
    assert layer["paint"]["raster-opacity"] == 0.6
    assert _raster_source(spec)["attribution"] == "EE"
    assert spec["center"] == [-0.15, 5.62]
    assert spec["zoom"] == 10


def test_ee_layer_legacy_mapid_token_fallback() -> None:
    # No tile_fetcher -> build the legacy /map/{mapid}/{z}/{x}/{y} URL (with {z}/{x}/{y} literal).
    img = _FakeImage({"mapid": "M", "token": "T"})
    url = _raster_source(_spec_of(gis.ee_layer(img)))["tiles"][0]
    assert url == "https://earthengine.googleapis.com/map/M/{z}/{x}/{y}?token=T"


def test_ee_layer_empty_mapid_raises() -> None:
    img = _FakeImage({"mapid": "", "token": ""})  # neither a fetcher nor a usable id
    with pytest.raises(ValueError):
        gis.ee_layer(img)


def test_ee_tile_url_handles_the_real_getmapid_shape() -> None:
    pytest.importorskip("ee")
    from ee.data import TileFetcher

    url = "https://earthengine.googleapis.com/v1/projects/p/maps/abc/tiles/{z}/{x}/{y}"
    map_id = {
        "mapid": "projects/p/maps/abc",
        "token": "",
        "tile_fetcher": TileFetcher(url, map_name="projects/p/maps/abc"),
    }
    assert gis._ee_tile_url(map_id) == url
