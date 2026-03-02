(() => {
  const searchInput = document.getElementById("analysisSearch");
  const cardsWrap = document.getElementById("analysisCards");
  if (!searchInput || !cardsWrap) return;

  const cards = Array.from(cardsWrap.querySelectorAll(".matrix-card"));
  const filterCards = () => {
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

  searchInput.addEventListener("input", filterCards);
  filterCards();
})();
