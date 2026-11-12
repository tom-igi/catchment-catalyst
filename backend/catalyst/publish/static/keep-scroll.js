// Keeping your place: choosing another catchment (on the map, or by an upstream
// or downstream river's name), another tab, or another part of the catchment on
// the Catchment Dashboard opens the new page scrolled to where you were, rather
// than at the top. Those pages share a layout, so you stay on the same panel.
//
// Links inside an element with data-keep-scroll do this, and so does map.js
// when its map has data-keep-scroll (window.keepScroll). Where you were is kept
// in the browser tab's session storage, only for the page being opened, and
// only briefly. Without this script (or storage) pages open at the top, as before.
(function () {
  "use strict";

  const KEY = "catalyst-keep-scroll";
  const FOR_MS = 30000;  // long enough for a slow connection, short enough not to surprise later

  function withoutHash(url) { return url.split("#")[0]; }

  // Remember the scroll position for the page at `url`.
  window.keepScroll = function (url) {
    try {
      sessionStorage.setItem(KEY, JSON.stringify({
        url: withoutHash(new URL(url, window.location.href).href), y: window.scrollY, at: Date.now(),
      }));
    } catch (e) { /* no session storage, e.g. blocked: the page opens at the top */ }
  };

  document.addEventListener("click", function (event) {
    const link = event.target.closest ? event.target.closest("a[href]") : null;
    if (!link || !link.closest("[data-keep-scroll]")) return;
    // Only a plain click that opens another page of this dashboard in this tab.
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    if ((link.target && link.target !== "_self") || link.origin !== window.location.origin) return;
    if (link.pathname === window.location.pathname && link.search === window.location.search) return;
    window.keepScroll(link.href);
  });

  // Opening a page: go back to where you were, if you came from one of those links.
  let kept = null;
  try {
    kept = JSON.parse(sessionStorage.getItem(KEY));
    sessionStorage.removeItem(KEY);
  } catch (e) { return; }
  if (!kept || kept.url !== withoutHash(window.location.href) || !(Date.now() - kept.at < FOR_MS)) return;
  window.scrollTo(0, kept.y);
  const reached = window.scrollY;
  // If the page wasn't long enough yet, try again once it has loaded, unless you've scrolled since.
  if (reached < kept.y) {
    window.addEventListener("load", function () {
      if (window.scrollY === reached) window.scrollTo(0, kept.y);
    });
  }
})();
