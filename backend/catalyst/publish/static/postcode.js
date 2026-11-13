// The postcode search on the Waterbody Dashboard: a postcode opens the river
// catchment it's in, on the same tab, as clicking it on the map does.
//
// The publish step writes the location's postcodes into postcodes/<district>.json,
// one file per district (e.g. postcodes/EX36.json: {"3AA": "<catchment ID>", ...}),
// so a search fetches one small file from this site and sends nothing anywhere
// else. Each postcode is placed by its centre (Ordnance Survey's Code-Point Open).
// A postcode that isn't in its district's file, or whose district has no file,
// is outside the location's catchments.
//
// The opened page has ?postcode=... on the end, so it can say which catchment
// the postcode is in. It checks first, so a link can't make it say something untrue.
//
// The form sets, on its element:
//   data-postcodes      the folder of district files
//   data-version        added to their links, so browsers fetch them again after a publish
//   data-links          what goes before a catchment ID to link to its page
//   data-selected       the catchment shown now, if one is chosen, and its name
//   data-selected-name
//   data-location       the location's name, e.g. North Devon
(function () {
  "use strict";

  const form = document.querySelector("form.postcode");
  if (!form) return;
  const input = form.querySelector("input");
  const message = form.querySelector(".postcode-message");
  const POSTCODE = /^[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}$/;

  // Opened by a search: say which catchment the postcode is in.
  const searched = tidy(new URLSearchParams(window.location.search).get("postcode") || "");
  if (form.dataset.selected && POSTCODE.test(searched)) {
    find(searched).then(function (id) {
      if (id !== form.dataset.selected) return;
      input.value = searched;
      say(searched + " is in " + form.dataset.selectedName + ".");
    }).catch(function () { /* nothing to say */ });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const postcode = tidy(input.value);
    if (!postcode) return say("Please enter a postcode.");
    if (!POSTCODE.test(postcode)) return say("That doesn't look like a full postcode. Please check it and try again.");
    say("Looking up " + postcode + "…");
    find(postcode).then(function (id) {
      if (!id) return say(postcode + " is outside the " + form.dataset.location + " catchments.");
      if (id === form.dataset.selected) return say(postcode + " is in " + form.dataset.selectedName + ".");
      const page = form.dataset.links + id + "/?postcode=" + encodeURIComponent(postcode);
      if (window.keepScroll) window.keepScroll(page);  // it's laid out like this page, as when clicking the map
      window.location.href = page;
    }).catch(function () {
      say("Sorry, the postcode search isn't working at the moment. Please try again later.");
    });
  });

  // The ID of the catchment the postcode is in, or null if it's outside them all.
  function find(postcode) {
    const parts = postcode.split(" ");
    return fetch(form.dataset.postcodes + parts[0] + ".json?v=" + form.dataset.version)
      .then(function (response) {
        if (response.status === 404) return {};  // no postcodes in that district
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (units) { return Object.prototype.hasOwnProperty.call(units, parts[1]) ? units[parts[1]] : null; });
  }

  // In capitals, with one space before the last three characters: "ex363aa" -> "EX36 3AA".
  function tidy(text) {
    const squashed = text.toUpperCase().replace(/[^A-Z0-9]/g, "");
    return squashed.length > 3 ? squashed.slice(0, -3) + " " + squashed.slice(-3) : squashed;
  }

  function say(text) { message.textContent = text; }
})();
