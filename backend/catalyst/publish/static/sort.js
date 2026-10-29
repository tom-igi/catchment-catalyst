// Sortable tables: click a column heading to sort by it, and click again to reverse.
//
// Works on every <table class="sortable">. Each heading says what its column
// holds in data-type ("number", "date" or anything else for text), and each
// cell can give the value to sort by in data-sort (otherwise its text is used).
// Empty cells always go last.
(function () {
  "use strict";

  document.querySelectorAll("table.sortable").forEach(function (table) {
    Array.from(table.tHead.rows[0].cells).forEach(function (heading, index) {
      const button = document.createElement("button");
      button.type = "button";
      button.append(...heading.childNodes);
      heading.append(button);
      button.addEventListener("click", function () { sort(table, heading, index); });
    });
  });

  function sort(table, heading, index) {
    const ascending = heading.getAttribute("aria-sort") !== "ascending";
    for (const other of heading.parentNode.cells) other.removeAttribute("aria-sort");
    heading.setAttribute("aria-sort", ascending ? "ascending" : "descending");

    const type = heading.dataset.type;
    const body = table.tBodies[0];
    const rows = Array.from(body.rows, function (row) { return { row: row, value: valueOf(row.cells[index]) }; });
    rows.sort(function (a, b) {
      if (a.value === "" || b.value === "") return (a.value === "") - (b.value === "");
      const order = compare(a.value, b.value, type);
      return ascending ? order : -order;
    });
    body.append(...rows.map(function (r) { return r.row; }));
  }

  function valueOf(cell) {
    if (!cell) return "";
    return (cell.dataset.sort !== undefined ? cell.dataset.sort : cell.textContent).trim();
  }

  function compare(a, b, type) {
    if (type === "number") return parseFloat(a) - parseFloat(b);
    if (type === "date") return a < b ? -1 : a > b ? 1 : 0; // ISO dates sort correctly as text
    return a.localeCompare(b, "en-GB", { numeric: true, sensitivity: "base" });
  }
})();
