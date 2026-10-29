// The catchment maps, drawn with Leaflet on an OpenStreetMap background.
// Each catchment's outline links to its page.
//
// The page sets what to show, on the map's element:
//   data-geojson   the file of outlines and rivers (catchments.geojson)
//   data-links     what goes before a catchment ID to link to its page ("" or "../")
//   data-selected  the catchment to highlight and zoom to (catchment pages only)
(function () {
  "use strict";

  const element = document.getElementById("map");
  if (!element || !window.L) return;

  const COLOURS = { catchment: "#0d6b77", selected: "#b0245a", river: "#1f78b4" };
  const selected = element.dataset.selected;

  const map = L.map(element, { scrollWheelZoom: false });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  fetch(element.dataset.geojson)
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then(function (data) {
      const outlines = L.geoJSON(data, {
        filter: function (feature) { return feature.properties.layer === "catchment"; },
        style: function (feature) { return outline(feature.properties.id === selected, false); },
        onEachFeature: function (feature, layer) {
          layer.bindTooltip(feature.properties.name, { sticky: true });
          if (feature.properties.id === selected) return;
          layer.on("click", function () { window.location.href = element.dataset.links + feature.properties.id + "/"; });
          layer.on("mouseover", function () { layer.setStyle(outline(false, true)); });
          layer.on("mouseout", function () { layer.setStyle(outline(false, false)); });
        },
      }).addTo(map);

      L.geoJSON(data, {
        filter: function (feature) { return feature.properties.layer === "river"; },
        style: { color: COLOURS.river, weight: 2 },
        interactive: false,
      }).addTo(map);

      let focus = outlines;
      outlines.eachLayer(function (layer) {
        if (layer.feature.properties.id === selected) {
          focus = layer;
          layer.bringToFront();
        }
      });
      map.fitBounds(focus.getBounds(), { padding: [8, 8] });
    })
    .catch(function () {
      element.innerHTML = '<p class="map-message">Sorry, the map couldn\'t be loaded.</p>';
    });

  function outline(isSelected, isHovered) {
    const colour = isSelected ? COLOURS.selected : COLOURS.catchment;
    return {
      color: colour,
      weight: isSelected ? 3 : 1.5,
      fillColor: colour,
      fillOpacity: isSelected ? 0.25 : isHovered ? 0.35 : 0.12,
    };
  }
})();
