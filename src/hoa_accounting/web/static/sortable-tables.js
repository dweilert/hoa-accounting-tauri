/* Shared sortable + filterable table behavior.
 *
 * Replaces ~60-line per-page IIFEs duplicated across categories_list,
 * vendor_bills_list, edit_records_*, and similar pages.
 *
 * Markup contract for an opt-in table:
 *
 *   <table id="my-table" data-sortable>
 *     <colgroup>…</colgroup>
 *     <thead>
 *       <tr>
 *         <th data-sort="text">Name</th>
 *         <th data-sort="date">Date</th>
 *         <th data-sort="number">Amount</th>
 *         <th>(unsortable)</th>
 *       </tr>
 *     </thead>
 *     <tbody>
 *       <tr> … </tr>
 *     </tbody>
 *   </table>
 *
 *   <!-- optional filter -->
 *   <input data-filter-table="#my-table"
 *          data-filter-count="#my-count">
 *   <span id="my-count">N entries</span>
 *
 * Behavior:
 *   - Click a <th data-sort="…"> to sort; click again to flip direction.
 *   - The <th> gets ``sort-asc`` / ``sort-desc`` class for the indicator.
 *   - The filter input hides rows whose textContent doesn't include the
 *     query (case-insensitive). Hidden rows get ``filtered`` class.
 *   - The optional count element is updated with the visible row count.
 *   - When a tbody row has ``data-keep-following=".inc-edit-row"`` (or any
 *     selector) the next sibling matching that selector is moved with it
 *     during sorting, so inline-edit panels stay attached to their parent
 *     row.
 */
(function () {
  "use strict";

  function cellValue(tr, idx, type) {
    var raw = (tr.children[idx] && tr.children[idx].textContent || "").trim();
    if (type === "number") return parseFloat(raw.replace(/[^0-9.\-]/g, "")) || 0;
    if (type === "date")   return raw;            // YYYY-MM-DD sorts as text
    return raw.toLowerCase();
  }

  function sort(table, th, idx) {
    var type = th.getAttribute("data-sort") || "text";
    var asc = !th.classList.contains("sort-asc");

    Array.prototype.forEach.call(
      table.querySelectorAll("th"),
      function (h) { h.classList.remove("sort-asc", "sort-desc"); }
    );
    th.classList.add(asc ? "sort-asc" : "sort-desc");

    var tbody = table.querySelector("tbody");
    if (!tbody) return;

    // Pair each "primary" row with any following "follower" row so the
    // edit-records pages keep their inline edit-form attached to its
    // parent row through a sort.
    var keepSel = table.getAttribute("data-keep-following") || "";
    var children = Array.prototype.slice.call(tbody.children);
    var pairs = [];
    for (var i = 0; i < children.length; i++) {
      var primary = children[i];
      // A "follower" is a row that immediately follows another row and
      // matches the configured selector. Skip them — they're absorbed
      // into the previous primary's pair.
      if (keepSel && primary.matches && primary.matches(keepSel)) continue;
      var follower = null;
      var next = children[i + 1];
      if (keepSel && next && next.matches && next.matches(keepSel)) {
        follower = next;
      }
      pairs.push([primary, follower]);
    }
    pairs.sort(function (a, b) {
      var av = cellValue(a[0], idx, type);
      var bv = cellValue(b[0], idx, type);
      if (av < bv) return asc ? -1 : 1;
      if (av > bv) return asc ?  1 : -1;
      return 0;
    });
    pairs.forEach(function (p) {
      tbody.appendChild(p[0]);
      if (p[1]) tbody.appendChild(p[1]);
    });
  }

  function wireSortable(table) {
    var ths = table.querySelectorAll("thead th[data-sort]");
    ths.forEach(function (th) {
      th.style.cursor = "pointer";
      // Add a sort indicator span if one isn't already present.
      if (!th.querySelector(".sort-ind")) {
        var span = document.createElement("span");
        span.className = "sort-ind";
        th.appendChild(document.createTextNode(" "));
        th.appendChild(span);
      }
      var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
      th.addEventListener("click", function () { sort(table, th, idx); });
    });
  }

  function applyFilter(input) {
    var sel = input.getAttribute("data-filter-table");
    var table = sel && document.querySelector(sel);
    if (!table) return;
    var q = (input.value || "").trim().toLowerCase();
    var rows = table.querySelectorAll("tbody > tr");
    var keepSel = table.getAttribute("data-keep-following") || "";
    var shown = 0;
    rows.forEach(function (tr) {
      // Followers track the visibility of their primary.
      if (keepSel && tr.matches && tr.matches(keepSel)) return;
      var match = !q || tr.textContent.toLowerCase().indexOf(q) !== -1;
      tr.classList.toggle("filtered", !match);
      if (match) shown++;
      // Hide / show the matching follower in lock-step with the primary.
      if (keepSel) {
        var follower = tr.nextElementSibling;
        if (follower && follower.matches(keepSel)) {
          follower.classList.toggle("filtered", !match);
          // Always collapse follower when filtered out — even if it was
          // expanded before.
          if (!match) follower.style.display = "none";
        }
      }
    });
    var countSel = input.getAttribute("data-filter-count");
    if (countSel) {
      var counter = document.querySelector(countSel);
      if (counter) {
        var noun = counter.getAttribute("data-noun") || "entries";
        counter.textContent = shown + " " + noun;
      }
    }
  }

  function syncStickyOffsets() {
    var topbar = document.querySelector("header.topbar");
    var topH = topbar ? topbar.getBoundingClientRect().height : 0;
    document.documentElement.style.setProperty("--app-topbar-offset", topH + "px");
  }

  function init() {
    document.querySelectorAll("table[data-sortable]").forEach(wireSortable);
    document.querySelectorAll("input[data-filter-table]").forEach(function (inp) {
      inp.addEventListener("input", function () { applyFilter(inp); });
    });
    syncStickyOffsets();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  window.addEventListener("resize", syncStickyOffsets);
})();
