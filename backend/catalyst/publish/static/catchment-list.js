// The list of river catchments by name, on the Waterbody Dashboard: choosing
// one opens it on the same tab, as clicking it on the map does.
//
// The page lists them A to Z, each with its group (data-group: its operational
// catchment). The "By area" switch puts them under their groups instead, still
// A to Z within each. The browser remembers the choice (local storage), so the
// next page lists them the same way; without storage, it's A to Z each time.
//
// The list's element sets data-links: what goes before a catchment ID to link to its page.
(function () {
  "use strict";

  const box = document.querySelector(".catchment-list");
  if (!box) return;
  const select = box.querySelector("select");
  const placeholder = select.options[0];
  const options = Array.prototype.slice.call(select.options, 1);  // A to Z, as on the page
  const KEY = "catalyst-list-order";

  select.addEventListener("change", function () {
    if (!select.value) return;
    const page = box.dataset.links + select.value + "/";
    if (window.keepScroll) window.keepScroll(page);  // it's laid out like this page, as when clicking the map
    window.location.href = page;
  });

  // Coming back to this page (e.g. with the Back button): show its own catchment again, not the one chosen.
  window.addEventListener("pageshow", function () {
    (options.find(function (o) { return o.defaultSelected; }) || placeholder).selected = true;
  });

  const switches = box.querySelectorAll('input[name="list-order"]');
  if (!switches.length) return;  // only one group: A to Z only
  switches.forEach(function (input) {
    input.addEventListener("change", function () {
      if (!input.checked) return;
      list(input.value);
      try { localStorage.setItem(KEY, input.value); } catch (e) { /* not remembered */ }
    });
  });
  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { /* no storage: A to Z */ }
  if (saved === "area") {
    box.querySelector('input[value="area"]').checked = true;
    list("area");
  }

  // List the catchments A to Z ("name"), or under their groups ("area"), keeping the one chosen.
  function list(how) {
    const chosen = select.selectedOptions[0];
    select.textContent = "";
    select.append(placeholder);
    if (how === "area") {
      const groups = new Map();
      options.forEach(function (o) {
        if (!groups.has(o.dataset.group)) groups.set(o.dataset.group, []);
        groups.get(o.dataset.group).push(o);
      });
      Array.from(groups.keys()).sort(function (a, b) { return a.localeCompare(b, "en-GB"); }).forEach(function (name) {
        const group = document.createElement("optgroup");
        group.label = name;
        group.append.apply(group, groups.get(name));
        select.append(group);
      });
    } else {
      select.append.apply(select, options);
    }
    if (chosen) chosen.selected = true;
  }
})();
