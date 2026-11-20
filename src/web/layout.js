/* Layout module for the landing page and section pages. index.html (the stories, filters and refresh) only talks to it
   through this small interface, so the layout can change without touching the page logic:
     Layout.openSection(key)                  open a section in its own browser tab (or bring its tab forward)
     Layout.applyMode({home, section, label}) show the landing page (panels, section buttons, refresh controls) or a
                                              section page (filters, stories), set the headline, title and tab name
     Layout.setMax(panel, on)                 maximise a landing-page panel / return it to standard
   It expects the elements named below to exist in index.html; the styles are in layout.css. */
const Layout = (() => {
  const $ = (id) => document.getElementById(id);

  // Each section lives at ?section=<key> in a tab named rcnd-<key>. If that tab is already open it is only brought
  // forward (nothing reloads, its filters stay); otherwise a new tab opens and starts clean.
  function openSection(key) {
    const url = new URL("?section=" + encodeURIComponent(key), location.href).href;
    let w = null;
    try { w = window.open("", "rcnd-" + key); } catch (e) {}
    if (!w) { location.href = url; return; }                       // pop-ups blocked: use this tab instead
    let reuse = false;
    try { reuse = w.location.href !== "about:blank" && new URL(w.location.href).searchParams.get("section") === key; } catch (e) {}
    if (!reuse) {
      try { w.opener = null; } catch (e) {}
      w.location.replace(url + "&fresh=1");                         // fresh: ignore anything remembered for this section
    }
    try { w.focus(); } catch (e) {}
  }

  // Panels start compact ("Standard"); Maximise gives one panel the whole window, Standard or Esc brings it back.
  function setMax(panel, on) {
    document.querySelectorAll(".hpanel.max").forEach((p) => {
      if (p !== panel || !on) { p.classList.remove("max"); const b = p.querySelector(".pmax"); b.textContent = "Maximise"; b.setAttribute("aria-pressed", "false"); p.dispatchEvent(new CustomEvent("panelmax", { detail: { max: false } })); }
    });
    if (on) { panel.classList.add("max"); const b = panel.querySelector(".pmax"); b.textContent = "Standard"; b.setAttribute("aria-pressed", "true"); panel.dispatchEvent(new CustomEvent("panelmax", { detail: { max: true } })); }
    document.body.classList.toggle("pmax", !!on);
  }

  // Landing page: refresh controls, panels and section buttons. Section page: filters and stories.
  function applyMode({ home, section, label }) {
    document.body.dataset.mode = home ? "home" : "section";
    $("secname").textContent = label ? " – " + label : "";
    document.title = label ? "SJ News Desk – " + label : "SJ News Desk";
    if (home) $("homelink").removeAttribute("href"); else { $("homelink").href = location.pathname; window.name = "rcnd-" + section; }
    for (const id of ["homeonly", "homeview", "refmsg", "tabs"]) $(id).hidden = !home;      // landing page only
    for (const id of ["filters", "sectionview", "reset"]) $(id).hidden = home;
    $("footnote").hidden = !home;
    if (home) $("papersframe").src = "newspaper-list/?embed=1&t=" + Date.now();       // t: never show a cached copy of the list page
  }

  document.addEventListener("click", (e) => { const b = e.target.closest(".hpanel .pmax"); if (!b) return; const p = b.closest(".hpanel"); setMax(p, !p.classList.contains("max")); });      // delegated: panels can be added later
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setMax(null, false); });
  // The Newspaper Homepage panel shows the separate page newspaper-list/; maximised, it grows to the height that page reports.
  window.addEventListener("message", (e) => {
    if (e.origin !== location.origin || !e.data || e.data.type !== "rcnd-height") return;
    $("panel-papers").style.setProperty("--fh", Math.max(300, Math.ceil(e.data.height)) + "px");
  });

  return { openSection, applyMode, setMax };
})();
