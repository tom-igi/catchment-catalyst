// The catchment maps: every catchment in the location, coloured by its
// ecological status as on the original dashboard, with its rivers, over an
// OpenStreetMap background. Clicking a catchment opens its page.
//
// The page sets what to show, on the map's element:
//   data-geojson   the file of outlines and rivers (catchments.geojson), with each catchment's status
//   data-links     what goes before a catchment ID to link to its page
//   data-selected  the catchment to highlight, if one is chosen
//
// The colours come from the --status-... colours in style.css.
(function () {
  "use strict";

  const element = document.getElementById("map");
  if (!element || !window.L) return;

  const selected = element.dataset.selected;
  const styles = getComputedStyle(document.documentElement);

  const RIVER = "#1f78b4";

  const map = L.map(element, { scrollWheelZoom: false, zoomSnap: 0.25 });
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
        style: function (feature) { return outline(feature, false); },
        onEachFeature: function (feature, layer) {
          const status = feature.properties.status;
          layer.bindTooltip(feature.properties.name + (status ? " (" + status + ")" : ""), { sticky: true });
          if (feature.properties.id === selected) return;
          layer.on("click", function () { window.location.href = element.dataset.links + feature.properties.id + "/"; });
          layer.on("mouseover", function () { layer.setStyle(outline(feature, true)); });
          layer.on("mouseout", function () { layer.setStyle(outline(feature, false)); });
        },
      }).addTo(map);

      outlines.eachLayer(function (layer) {
        if (layer.feature.properties.id === selected) layer.bringToFront();
      });

      L.geoJSON(data, {
        filter: function (feature) { return feature.properties.layer === "river"; },
        style: function (feature) { return { color: RIVER, weight: feature.properties.id === selected ? 2.5 : 1.5 }; },
        interactive: false,
      }).addTo(map);
      map.fitBounds(outlines.getBounds(), { padding: [4, 4] });
    })
    .catch(function () {
      element.innerHTML = '<p class="map-message">Sorry, the map couldn\'t be loaded.</p>';
    });

  function outline(feature, isHovered) {
    const isSelected = feature.properties.id === selected;
    // With a catchment chosen, the others are faded, as on the original. The
    // colours are partly see-through, so the background map shows.
    const faded = selected && !isSelected;
    return {
      color: isSelected ? "#333333" : isHovered ? "#555555" : "#ffffff",
      weight: isSelected ? 2.5 : isHovered ? 2 : 1,
      fillColor: colour(feature.properties.status),
      fillOpacity: isHovered ? 0.8 : faded ? 0.3 : 0.65,
    };
  }

  function colour(status) {
    const name = status ? "--status-" + status.toLowerCase().split(/\s+/).join("-") : "--status-none";
    return styles.getPropertyValue(name).trim() || styles.getPropertyValue("--status-none").trim();
  }
})();
