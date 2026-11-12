// Tabs within a page: the Catchment Dashboard's text (Why is the river system
// failing?, ...) and the focus areas on Intervention Management and Catchment
// Insights.
//
// Works on every element with data-tabs that has role="tab" buttons and
// role="tabpanel" sections (each button's aria-controls names its section).
// One can be inside another's section, e.g. the twelve interventions inside
// Interventions Detail: each only uses its own buttons. Without this script
// every section is shown and the buttons are hidden, so nothing is out of
// reach. A link to a section's ID (#fish), or to anything inside it, opens it.
(function () {
  "use strict";

  document.querySelectorAll("[data-tabs]").forEach(function (box) {
    const buttons = Array.from(box.querySelectorAll('[role="tab"]')).filter(function (button) {
      return button.closest("[data-tabs]") === box;  // not those of a set of tabs inside this one
    });
    const panels = buttons.map(function (button) { return document.getElementById(button.getAttribute("aria-controls")); });
    if (!buttons.length || panels.some(function (panel) { return !panel; })) return;
    box.classList.add("tabs-ready");

    function show(index, focus) {
      buttons.forEach(function (button, i) {
        button.setAttribute("aria-selected", i === index ? "true" : "false");
        button.tabIndex = i === index ? 0 : -1;
        panels[i].hidden = i !== index;
      });
      if (focus) buttons[index].focus();
    }

    buttons.forEach(function (button, i) {
      button.addEventListener("click", function () { show(i, false); });
      button.addEventListener("keydown", function (event) {
        const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
        if (event.key === "Home") show(0, true);
        else if (event.key === "End") show(buttons.length - 1, true);
        else if (step) show((i + step + buttons.length) % buttons.length, true);
        else return;
        event.preventDefault();
      });
    });

    const target = window.location.hash ? document.getElementById(decodeURIComponent(window.location.hash.slice(1))) : null;
    const linked = panels.findIndex(function (panel) { return target && panel.contains(target); });
    show(linked >= 0 ? linked : 0, false);
  });
})();
