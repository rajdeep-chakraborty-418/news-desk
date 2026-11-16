/* Backdrop module: the picture behind the header of the landing page and of each section page.
     Backdrop.apply(place)   place is "landing" or a section key; picks one image of that place's set at random.
   The sets come from backgrounds.json (built from external_config/backgrounds/); no entry or no file = plain header.
   It only touches <header>, so it can be removed or replaced without touching the rest of the page. Styles: backdrop.css. */
const Backdrop = (() => {
  let sets = null;
  async function load() {
    if (sets) return sets;
    try { sets = await (await fetch("backgrounds.json?t=" + Date.now(), { cache: "no-store" })).json(); } catch (e) { sets = {}; }
    return sets;
  }
  async function apply(place) {
    const header = document.querySelector("header");
    const list = ((await load())[place]) || [];
    if (!header) return;
    if (!list.length) { header.classList.remove("banded"); header.style.backgroundImage = ""; return; }
    const pick = list[Math.floor(Math.random() * list.length)];
    header.style.backgroundImage = `url("${pick}")`;
    header.classList.add("banded");
    header.dataset.place = place;
  }
  return { apply };
})();
