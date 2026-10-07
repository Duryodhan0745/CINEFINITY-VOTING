(function () {
  const root = document.getElementById("cats");
  const statusEl = document.getElementById("status");

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function render(d) {
    const open = d.status === "active";
    statusEl.textContent = open ? "LIVE VOTING" : "VOTING CLOSED";
    statusEl.className = "pill " + (open ? "live" : "closed");
    const max = Math.max(1, ...d.categories.flatMap(c => c.items.map(i => i.votes)));
    root.replaceChildren(...d.categories.map(c => {
      const sec = el("section", "proj-cat");
      sec.appendChild(el("h2", "", c.label.toUpperCase()));
      if (!open && c.tie) sec.appendChild(el("p", "winner", "TIE — Manual decision required"));
      else if (!open && c.winner) sec.appendChild(el("p", "winner", "🏆 Winner: " + c.winner));
      c.items.forEach(i => {
        const row = el("div", "bar-row");
        row.appendChild(el("span", "bar-name", i.name));
        const track = el("div", "bar-track");
        const fill = el("div", "bar-fill");
        fill.style.width = (i.votes / max * 100) + "%";
        track.appendChild(fill);
        row.appendChild(track);
        row.appendChild(el("span", "bar-count", String(i.votes)));
        sec.appendChild(row);
      });
      return sec;
    }));
  }

  async function tick() {
    try {
      const r = await fetch("/api/results", { cache: "no-store" });
      if (r.ok) render(await r.json());
    } catch (e) { /* keep last good view */ }
  }
  tick();
  setInterval(tick, 3000);
})();
