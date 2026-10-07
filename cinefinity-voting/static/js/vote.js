(function () {
  const form = document.getElementById("ballot");
  if (!form) return;
  const btn = document.getElementById("submit");
  const msg = document.getElementById("msg");
  const categories = [...new Set([...form.querySelectorAll("input[type=radio]")].map(r => r.name))];
  const closed = !!form.querySelector("input:disabled");

  function refresh() {
    const complete = categories.every(c => form.querySelector(`input[name="${c}"]:checked`));
    btn.disabled = closed || !complete;
    form.querySelectorAll(".card").forEach(card => {
      card.classList.toggle("chosen", card.querySelector("input").checked);
    });
  }

  form.addEventListener("change", refresh);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    btn.disabled = true;
    msg.textContent = "Submitting…";
    const selections = {};
    categories.forEach(c => {
      selections[c] = form.querySelector(`input[name="${c}"]:checked`).value;
    });
    try {
      const r = await fetch("/vote/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selections }),
        credentials: "same-origin",
      });
      if (r.ok) { location.href = "/confirmation"; return; }
      const data = await r.json().catch(() => ({}));
      msg.textContent = data.error || "Something went wrong. Please try again.";
    } catch (err) {
      msg.textContent = "Network problem. Please check your connection and try again.";
    }
    refresh();
  });

  refresh();
})();
