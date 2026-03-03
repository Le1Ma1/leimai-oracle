(() => {
  function formatUtcNodes() {
    const nodes = Array.from(document.querySelectorAll("[data-utc]"));
    for (const node of nodes) {
      const iso = String(node.getAttribute("data-utc") || "").trim();
      if (!iso) continue;
      const ts = Date.parse(iso);
      if (!Number.isFinite(ts)) continue;
      node.textContent = new Intl.DateTimeFormat("en-GB", {
        dateStyle: "medium",
        timeStyle: "short",
        hour12: false,
        timeZone: "UTC",
      }).format(new Date(ts)) + " UTC";
    }
  }

  function bindSearch() {
    const searchInput = document.getElementById("analysisSearch");
    const cardsWrap = document.getElementById("analysisCards");
    if (!searchInput || !cardsWrap) return;

    const cards = Array.from(cardsWrap.querySelectorAll(".matrix-card"));
    const applyFilter = () => {
      const q = String(searchInput.value || "").trim().toLowerCase();
      let visible = 0;
      for (const card of cards) {
        const hay = String(card.getAttribute("data-filter") || "").toLowerCase();
        const show = !q || hay.includes(q);
        card.style.display = show ? "" : "none";
        if (show) visible += 1;
      }
      cardsWrap.setAttribute("data-visible-count", String(visible));
    };

    searchInput.addEventListener("input", applyFilter);
    applyFilter();
  }

  formatUtcNodes();
  bindSearch();
})();
