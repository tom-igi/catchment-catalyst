"""Download files from the EA's Catchment Data Explorer.

API reference: https://environment.data.gov.uk/catchment-planning/api/docs

The service sometimes answers with an error page instead of the file, so every
response is checked and failed downloads are retried.
"""

from __future__ import annotations

import io
import time
import urllib.error
import urllib.request
import zipfile

BASE_URL = "https://environment.data.gov.uk/catchment-planning"
USER_AGENT = "catchment-catalyst-importer (+https://github.com/tom-igi/catchment-catalyst)"


class EAError(Exception):
    """A download from the EA failed."""


class EAClient:
    def __init__(self, base_url: str = BASE_URL, retries: int = 3, timeout: float = 60, pause: float = 1.0):
        self.base_url = base_url
        self.retries = retries
        self.timeout = timeout
        self.pause = pause  # seconds between requests, to go easy on the EA's servers

    def waterbody_shapefile(self, waterbody_id: str) -> bytes:
        """The waterbody's shapefile (.zip): its catchment boundary, river line and details."""
        return self._get(f"/WaterBody/{waterbody_id}/shapefile.zip", _is_zip, "a shapefile")

    def waterbody_page(self, waterbody_id: str) -> str:
        """The waterbody's web page, the only place with its length and upstream/downstream links."""
        data = self._get(f"/WaterBody/{waterbody_id}", lambda d: b'id="upstream-water-bodies"' in d, "the waterbody page")
        return data.decode("utf-8")

    def _get(self, path: str, looks_right, what: str) -> bytes:
        url = self.base_url + path
        problem = ""
        for attempt in range(1, self.retries + 1):
            time.sleep(self.pause if attempt == 1 else self.pause * 3 * attempt)
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = response.read()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise EAError(f"the EA has no such page ({url})") from e
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
