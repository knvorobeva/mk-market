const heroBtn = document.querySelector("#hero-search-btn");
const catalogBtn = document.querySelector("#catalog-search-btn");

const guessTarget = (value) => {
  const cleaned = value.trim();
  if (!cleaned) return "catalog.html";
  const words = cleaned.split(/\s+/).filter(Boolean);
  // Простая эвристика: если 2+ слова — считаем, что это ФИО мастера
  return words.length >= 2 ? "master.html" : "catalog.html";
};

const go = (value) => {
  const target = guessTarget(value);
  const url = value.trim() ? `${target}?q=${encodeURIComponent(value.trim())}` : target;
  window.location.href = url;
};

if (heroBtn) {
  heroBtn.addEventListener("click", () => {
    const value = document.querySelector("#hero-search")?.value || "";
    go(value);
  });
}

if (catalogBtn) {
  catalogBtn.addEventListener("click", () => {
    const value = document.querySelector("#catalog-search")?.value || "";
    go(value);
  });
}

const params = new URLSearchParams(window.location.search);
const q = params.get("q");
if (q) {
  const heroInput = document.querySelector("#hero-search");
  const catalogInput = document.querySelector("#catalog-search");
  if (heroInput) heroInput.value = q;
  if (catalogInput) catalogInput.value = q;
}
