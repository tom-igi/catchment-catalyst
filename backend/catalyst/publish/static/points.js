// The small maps of points in a catchment (storm overflow outlets, river
// obstacles), over OpenStreetMap, with the catchment's outline and river.
//
// Each map's element (class "points-map") says what to show:
//   data-geojson    the file of outlines and rivers (catchments.geojson)
//   data-catchment  the catchment to outline
//   data-points     the points, as JSON: [[latitude, longitude, label], ...]
//   data-colour     the points' colour
(function () {
  "use strict";

  if (!window.L) return;
  const RIVER = "#1f78b4";

  document.querySelectorAll(".points-map").forEach(function (element) {
    const catchment = element.dataset.catchment;
    const map = L.map(element, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);

    const points = L.featureGroup(JSON.parse(element.dataset.points || "[]").map(function (point) {
      const label = document.createElement("span");
      label.textContent = point[2];
      return L.circleMarker([point[0], point[1]], {
        radius: 6, color: "#ffffff", weight: 1.5, fillColor: element.dataset.colour, fillOpacity: 1,
      }).bindTooltip(label);
    }));

    fetch(element.dataset.geojson)
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (data) {
        const outline = L.geoJSON(data, {
          filter: function (feature) { return feature.properties.id === catchment; },
          style: function (feature) {
            return feature.properties.layer === "river"
              ? { color: RIVER, weight: 2 }
              : { color: "#333333", weight: 2, fill: false };
          },
          interactive: false,
        }).addTo(map);
        points.addTo(map);
        const bounds = outline.getBounds();
        if (points.getLayers().length) bounds.extend(points.getBounds());
        map.fitBounds(bounds, { padding: [8, 8] });
      })
      .catch(function () {
        element.innerHTML = '<p class="map-message">Sorry, the map couldn\'t be loaded.</p>';
      });
  });
})();
