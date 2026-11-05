"""Download the EA's data: from its Catchment Data Explorer, its storm overflow
annual returns, and the River Obstacles map service.

Catchment Data Explorer API reference: https://environment.data.gov.uk/catchment-planning/api/docs

The services sometimes answer with an error page instead of the file, so every
response is checked and failed downloads are retried.
"""

from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

BASE_URL = "https://environment.data.gov.uk/catchment-planning"
# The EA's "Event Duration Monitoring - Storm Overflows - Annual Returns", one file a year:
# https://www.data.gov.uk/dataset/event-duration-monitoring-storm-overflows-annual-returns
STORM_OVERFLOWS_URL = (
    "https://environment.data.gov.uk/api/file/download?fileDataSetId=c55e170e-3c75-49a5-8026-a961ff94c8e0"
    "&fileName=EDM_{year}_Storm_Overflow_Annual_Return.zip"
)
# River Obstacles (EA and The Rivers Trust), "River Obstacles Public View", in British National Grid:
# https://river-obstacles-theriverstrust.hub.arcgis.com/
RIVER_OBSTACLES_URL = (
    "https://services3.arcgis.com/Bb8lfThdhugyc4G3/arcgis/rest/services/River_Obstacles_Public_View/FeatureServer/0/query"
)
RIVER_OBSTACLES_PAGE = 1000  # the most the service sends at once
USER_AGENT = "catchment-catalyst-importer (+https://github.com/tom-igi/catchment-catalyst)"


class EAError(Exception):
    """A download from the EA failed."""


class EANotFound(EAError):
    """The EA has no such file, e.g. a year that isn't published yet."""


class EAClient:
    def __init__(self, base_url: str = BASE_URL, retries: int = 3, timeout: float = 60, pause: float = 1.0):
        self.base_url = base_url
        self.retries = retries
        self.timeout = timeout
        self.pause = pause  # seconds between requests, to go easy on the EA's servers

    def waterbody_shapefile(self, waterbody_id: str) -> bytes:
        """The waterbody's shapefile (.zip): its catchment boundary, river line and details."""
        return self._get(self.base_url + f"/WaterBody/{waterbody_id}/shapefile.zip", _is_zip, "a shapefile")

    def waterbody_page(self, waterbody_id: str) -> str:
        """The waterbody's web page, the only place with its length and upstream/downstream links."""
        data = self._get(self.base_url + f"/WaterBody/{waterbody_id}", lambda d: b'id="upstream-water-bodies"' in d, "the waterbody page")
        return data.decode("utf-8")

    def management_catchment(self, management_catchment_id: int) -> dict:
        """The management catchment's waterbodies, as GeoJSON: their IDs, names, types and outlines."""
        data = self._get(self.base_url + f"/ManagementCatchment/{management_catchment_id}.geojson", _is_geojson, "a list of waterbodies")
        return json.loads(data)

    def management_catchment_file(self, management_catchment_id: int, name: str) -> bytes:
        """One of the management catchment's downloads covering all its waterbodies, e.g. rnags.csv."""
        return self._get(self.base_url + f"/ManagementCatchment/{management_catchment_id}/{name}", _is_csv, f"the {name} file")

    def storm_overflows(self, year: int) -> bytes:
        """The year's storm overflow annual return (.zip), for every water company. EANotFound if
        it isn't published yet."""
        return self._get(STORM_OVERFLOWS_URL.format(year=year), _is_zip, "a .zip file")

    def river_obstacles(self, box: tuple[float, float, float, float], offset: int = 0) -> dict:
        """One page of the river obstacles in a box (British National Grid: west, south, east,
        north), as GeoJSON in latitude/longitude."""
        query = urllib.parse.urlencode({
            "where": "1=1",
            "geometry": ",".join(str(round(v)) for v in box),
            "geometryType": "esriGeometryEnvelope",
            "inSR": 27700,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "globalid,ea_obstructid,site_name,obstacle_type,origin,status",
            "orderByFields": "objectid",
            "resultOffset": offset,
            "resultRecordCount": RIVER_OBSTACLES_PAGE,
            "outSR": 4326,
            "f": "geojson",
        })
        return json.loads(self._get(f"{RIVER_OBSTACLES_URL}?{query}", _is_geojson, "a list of obstacles"))

    def _get(self, url: str, looks_right, what: str) -> bytes:
        problem = ""
        for attempt in range(1, self.retries + 1):
            time.sleep(self.pause if attempt == 1 else self.pause * 3 * attempt)
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = response.read()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise EANotFound(f"the EA has no such page ({url})") from e
                problem = f"the EA returned error {e.code}"
                continue
            except (urllib.error.URLError, TimeoutError) as e:
                problem = f"could not reach the EA ({getattr(e, 'reason', e)})"
                continue
            if looks_right(data):
                return data
            problem = f"the EA sent something other than {what}"
        hint = ". The EA also answers this way for IDs it doesn't recognise, so check the ID" if "500" in problem else ""
        raise EAError(f"{problem}, after {self.retries} tries{hint} ({url})")


def _is_zip(data: bytes) -> bool:
    return zipfile.is_zipfile(io.BytesIO(data))


def _is_geojson(data: bytes) -> bool:
    return data.lstrip().startswith(b"{") and b'"FeatureCollection"' in data[:200]


def _is_csv(data: bytes) -> bool:
    return b'"Water Body ID"' in data[:2000]
