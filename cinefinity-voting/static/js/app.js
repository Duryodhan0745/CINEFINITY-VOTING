(function () {
  "use strict";

  const config = window.APP_CONFIG || { isAdmin: false, status: "closed", categories: {} };

  // ─── DOM helpers ──────────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);

  const voterNotice      = $("voter-notice");
  const ballotForm       = $("ballot");
  const submitBtn        = $("submit");
  const msgEl            = $("msg");
  const connBanner       = $("conn-banner");
  const voterStatusBar   = $("voter-status-bar");

  const confModal        = $("confirmation-modal");
  const confCloseBtn     = $("conf-close-btn");

  const adminTrigger     = $("admin-trigger");
  const adminLoginModal  = $("admin-login-modal");
  const adminLoginClose  = $("admin-login-close");
  const adminLoginForm   = $("admin-login-form");
  const adminPasswordInp = $("admin-password");
  const adminLoginErr    = $("admin-login-err");

  const adminView              = $("admin-dashboard-view");
  const btnToggleVoter         = $("btn-toggle-voter-view");
  const btnAdminLogout         = $("btn-admin-logout");
  const btnStartVoting         = $("btn-start-voting");
  const btnStopVoting          = $("btn-stop-voting");
  const btnResetVotes          = $("btn-reset-votes");
  const adminStatusBadge       = $("admin-status-badge");
  const adminBallotsCount      = $("admin-ballots-count");
  const adminVotesCount        = $("admin-votes-count");
  const adminContainerEl       = $("admin-contestants-container");
  const adminLiveBanner        = $("admin-live-banner");
  const btnGoToVoting          = $("btn-go-to-voting");

  const projectorView          = $("projector-view");
  const btnOpenProjector       = $("btn-open-projector");
  const btnAdminQuickProjector = $("btn-admin-quick-projector");
  const btnBackToAdmin         = $("btn-back-to-admin");
  const projStatus             = $("proj-status");
  const projCats               = $("proj-cats");

  let projectorInterval  = null;
  let statusPollInterval = null;
  let lastKnownResults   = null;  // keeps last successful fetch for resilience

  // ─────────────────────────────────────────────────────────────────────────
  // 1. PUBLIC VOTING INTERFACE
  // ─────────────────────────────────────────────────────────────────────────

  function getCategoryNames() {
    if (!ballotForm) return [];
    return [...new Set([...ballotForm.querySelectorAll("input[type=radio]")].map((r) => r.name))];
  }

  function updateVoterStatusUI(newStatus, announce) {
    const wasStatus = config.status;
    config.status = newStatus;
    const isClosed = newStatus !== "active";

    if (voterNotice) {
      voterNotice.textContent = isClosed
        ? "Voting is currently closed."
        : "★ Select 1 contestant in each category to submit!";
    }
    if (ballotForm) {
      ballotForm.querySelectorAll("input[type=radio]").forEach((inp) => {
        inp.disabled = isClosed;
      });
    }
    refreshBallot();

    // Show status-change notification only if it actually changed and announce=true
    if (announce && voterStatusBar && wasStatus !== newStatus) {
      if (newStatus === "active") {
        voterStatusBar.textContent = "✅ Voting is now OPEN — cast your vote!";
        voterStatusBar.style.background = "#2d7a2d";
      } else {
        voterStatusBar.textContent = "⛔ Voting has been closed by the organiser.";
        voterStatusBar.style.background = "#c02010";
      }
      voterStatusBar.classList.add("visible");
      setTimeout(() => voterStatusBar.classList.remove("visible"), 6000);
    }
  }

  function refreshBallot() {
    if (!ballotForm) return;
    const catNames = getCategoryNames();
    const isClosed = config.status !== "active";
    let chosenCount = 0;

    catNames.forEach((cat) => {
      const checked = ballotForm.querySelector(`input[name="${cat}"]:checked`);
      if (checked) chosenCount++;
    });

    ballotForm.querySelectorAll(".card").forEach((card) => {
      const radio = card.querySelector("input[type=radio]");
      const isChosen = radio && radio.checked;
      card.classList.toggle("chosen", !!isChosen);
      const selSpan = card.querySelector(".select");
      if (selSpan) selSpan.textContent = isChosen ? "✓ Chosen" : "Select";
    });

    const isComplete = catNames.length > 0 && chosenCount === catNames.length;
    if (submitBtn) submitBtn.disabled = isClosed || !isComplete;

    if (msgEl && !isClosed) {
      if (isComplete) {
        msgEl.textContent = "All categories selected! Ready to submit.";
        msgEl.style.color = "var(--ink)";
      } else if (catNames.length > 0) {
        msgEl.textContent = `${chosenCount} of ${catNames.length} categories chosen`;
        msgEl.style.color = "rgba(23,23,23,0.7)";
      }
    }
  }

  if (ballotForm) {
    ballotForm.addEventListener("change", refreshBallot);

    ballotForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (submitBtn) submitBtn.disabled = true;
      if (msgEl) {
        msgEl.textContent = "Submitting votes…";
        msgEl.style.color = "var(--ink)";
      }

      const catNames = getCategoryNames();
      const selections = {};
      catNames.forEach((c) => {
        const checked = ballotForm.querySelector(`input[name="${c}"]:checked`);
        if (checked) selections[c] = checked.value;
      });

      try {
        const res = await fetch("/vote/submit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ selections }),
          credentials: "same-origin",
        });

        const data = await res.json().catch(() => ({}));

        if (res.ok && data.ok) {
          ballotForm.querySelectorAll("input").forEach((i) => (i.disabled = true));
          if (msgEl) {
            msgEl.textContent = "✓ Vote recorded successfully.";
            msgEl.style.color = "var(--red)";
          }
          if (confModal) confModal.classList.add("active");
          stopStatusPolling(); // no need to poll after voting
          return;
        }

        if (msgEl) {
          msgEl.textContent = data.error || "Submission failed. Please try again.";
          msgEl.style.color = "var(--red)";
        }
      } catch (_err) {
        if (msgEl) {
          msgEl.textContent = "⚠ Your vote was NOT recorded. Check your connection and try again.";
          msgEl.style.color = "var(--red)";
        }
      }

      refreshBallot();
    });
  }

  if (confCloseBtn && confModal) {
    confCloseBtn.addEventListener("click", () => confModal.classList.remove("active"));
  }

  // ─────────────────────────────────────────────────────────────────────────
  // 2. VOTING STATUS POLL (voter page) — makes voting-open/close live for
  //    voters who already have the page open when admin flips the switch.
  // ─────────────────────────────────────────────────────────────────────────

  let _statusConsecutiveFailures = 0;

  async function pollVotingStatus() {
    // Don't disturb a submitted ballot or a confirmed voter
    if (confModal && confModal.classList.contains("active")) return;
    try {
      const res = await fetch("/api/results", { cache: "no-store" });
      if (!res.ok) throw new Error("not-ok");
      const d = await res.json();
      _statusConsecutiveFailures = 0;
      if (connBanner) connBanner.classList.remove("visible");

      // If status changed since this tab opened, update UI
      if (d.status !== config.status) {
        updateVoterStatusUI(d.status, /*announce=*/ true);
      }
    } catch (_) {
      _statusConsecutiveFailures++;
      if (_statusConsecutiveFailures >= 3 && connBanner) {
        connBanner.classList.add("visible");
      }
    }
  }

  function startStatusPolling() {
    if (statusPollInterval) return;
    statusPollInterval = setInterval(pollVotingStatus, 4000);
  }

  function stopStatusPolling() {
    if (statusPollInterval) {
      clearInterval(statusPollInterval);
      statusPollInterval = null;
    }
  }

  // Start polling immediately (unless the voter has already voted)
  // We gate on whether the ballot form still has enabled inputs
  if (ballotForm) {
    startStatusPolling();
  }

  // ─────────────────────────────────────────────────────────────────────────
  // 3. ADMIN ACCESS & AUTH
  // ─────────────────────────────────────────────────────────────────────────

  function openAdmin() {
    if (config.isAdmin) {
      stopStatusPolling(); // admin doesn't need voter status polling
      if (adminView) adminView.classList.add("active");
      loadAdminData();
    } else {
      if (adminLoginModal) {
        adminLoginModal.classList.add("active");
        if (adminPasswordInp) {
          adminPasswordInp.value = "";
          adminPasswordInp.focus();
        }
      }
    }
  }

  if (adminTrigger) adminTrigger.addEventListener("click", openAdmin);

  if (adminLoginClose && adminLoginModal) {
    adminLoginClose.addEventListener("click", () => adminLoginModal.classList.remove("active"));
  }

  if (adminLoginForm) {
    adminLoginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const pw = (adminPasswordInp ? adminPasswordInp.value : "").trim();
      if (!pw) return;

      const loginBtn = adminLoginForm.querySelector("button[type=submit]");
      if (loginBtn) loginBtn.disabled = true;
      if (adminLoginErr) adminLoginErr.style.display = "none";

      try {
        const res = await fetch("/api/admin/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password: pw }),
          credentials: "same-origin",
        });

        const data = await res.json().catch(() => ({}));

        if (res.ok && data.ok) {
          config.isAdmin = true;
          stopStatusPolling();
          if (adminLoginModal) adminLoginModal.classList.remove("active");
          if (adminTrigger) {
            adminTrigger.textContent = "Admin Panel ⚙️";
            adminTrigger.classList.add("admin-logged-in");
          }
          if (adminView) adminView.classList.add("active");
          loadAdminData();
        } else {
          if (adminLoginErr) {
            adminLoginErr.textContent = data.error || "Incorrect password.";
            adminLoginErr.style.display = "block";
          }
        }
      } catch (_) {
        if (adminLoginErr) {
          adminLoginErr.textContent = "Connection error. Please try again.";
          adminLoginErr.style.display = "block";
        }
      } finally {
        if (loginBtn) loginBtn.disabled = false;
      }
    });
  }

  function goToVoting() {
    if (adminView) adminView.classList.remove("active");
    startStatusPolling(); // resume voter status polling
    if (ballotForm) {
      ballotForm.scrollIntoView({ behavior: "smooth" });
    }
  }

  if (btnGoToVoting) {
    btnGoToVoting.addEventListener("click", goToVoting);
  }

  if (btnToggleVoter) {
    btnToggleVoter.addEventListener("click", goToVoting);
  }

  if (btnAdminLogout) {
    btnAdminLogout.addEventListener("click", async () => {
      try { await fetch("/api/admin/logout", { method: "POST" }); } catch (_) {}
      config.isAdmin = false;
      if (adminTrigger) {
        adminTrigger.textContent = "Admin ↗";
        adminTrigger.classList.remove("admin-logged-in");
      }
      if (adminView) adminView.classList.remove("active");
      startStatusPolling(); // resume voter status polling after logout
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // 4. ADMIN DASHBOARD
  // ─────────────────────────────────────────────────────────────────────────

  async function loadAdminData() {
    try {
      const res = await fetch("/api/admin/data", { cache: "no-store" });
      if (!res.ok) return;
      const d = await res.json();
      if (!d.ok) return;

      config.status = d.status;
      updateVoterStatusUI(d.status, /*announce=*/ false);

      if (adminStatusBadge) {
        const active = d.status === "active";
        adminStatusBadge.textContent = active ? "ACTIVE" : "CLOSED";
        adminStatusBadge.className = "pill " + (active ? "live" : "closed");
      }
      if (adminLiveBanner) {
        adminLiveBanner.style.display = d.status === "active" ? "flex" : "none";
      }
      if (adminBallotsCount) adminBallotsCount.textContent = d.ballots;
      if (adminVotesCount) adminVotesCount.textContent = d.total_votes;

      renderAdminContestants(d.groups, d.categories, d.max_per);
    } catch (err) {
      console.error("Failed to load admin data", err);
    }
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function renderAdminContestants(groups, categories, maxPer) {
    if (!adminContainerEl) return;
    adminContainerEl.innerHTML = "";

    groups.forEach((g) => {
      const sec = document.createElement("section");
      sec.className = "panel";
      sec.dataset.catKey = g.key;

      sec.innerHTML = `<h2 style="color:var(--red);margin-top:0">${escHtml(g.label.toUpperCase())}</h2>`;

      const listDiv = document.createElement("div");
      listDiv.className = "cat-contestants-list";

      g.items.forEach((c) => {
        const form = document.createElement("form");
        form.className = "c-form contestant-form";
        form.dataset.cid = c.id;
        form.enctype = "multipart/form-data";

        const photoEl = c.photo_url
          ? `<img src="${escHtml(c.photo_url)}" alt="" width="70" height="70" loading="lazy" style="border-radius:8px;object-fit:cover">`
          : `<div class="ph" style="width:70px;height:70px;border-radius:8px;font-size:1.8rem">★</div>`;

        const catOptions = Object.entries(categories)
          .map(([k, v]) => `<option value="${escHtml(k)}" ${k === c.category ? "selected" : ""}>${escHtml(v)}</option>`)
          .join("");

        form.innerHTML = `
          <div style="display:flex;gap:10px;align-items:center">
            ${photoEl}
            <div style="flex:1">
              <label>Name
                <input name="name" value="${escHtml(c.name || "")}" maxlength="60" required style="width:100%">
              </label>
            </div>
          </div>
          <label>Category
            <select name="category">${catOptions}</select>
          </label>
          <label>Display order
            <input type="number" name="display_order" min="1" max="99" value="${Number(c.display_order) || 1}">
          </label>
          <label class="check">
            <input type="checkbox" name="active" ${c.active ? "checked" : ""}> Enabled on ballot
          </label>
          <label>Photo (max 3 MB)
            <input type="file" name="photo" accept="image/jpeg,image/png,image/webp">
          </label>
          <div class="c-form-actions">
            <button class="btn btn-sm" type="submit">Save Changes</button>
            <button class="btn btn-sm btn-danger btn-delete-contestant" type="button" data-cid="${escHtml(c.id)}">Delete</button>
            <span class="c-form-status notice" style="font-size:0.85rem"></span>
          </div>
        `;

        bindContestantFormEvents(form, c.id);
        listDiv.appendChild(form);
      });

      sec.appendChild(listDiv);

      if (g.items.length < maxPer) {
        const addBtn = document.createElement("button");
        addBtn.type = "button";
        addBtn.className = "btn btn-sm btn-ghost btn-add-contestant";
        addBtn.dataset.catKey = g.key;
        addBtn.style.marginTop = "8px";
        addBtn.textContent = "+ Add Contestant";
        addBtn.addEventListener("click", () => addNewContestant(g.key));
        sec.appendChild(addBtn);
      }

      adminContainerEl.appendChild(sec);
    });
  }

  function bindContestantFormEvents(form, cid) {
    const statusSpan = form.querySelector(".c-form-status");

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const saveBtn = form.querySelector("button[type=submit]");
      if (saveBtn) saveBtn.disabled = true;
      if (statusSpan) { statusSpan.textContent = "Saving…"; statusSpan.style.color = "var(--ink)"; }

      try {
        const res = await fetch(`/api/admin/contestant/${cid}`, {
          method: "POST",
          body: new FormData(form),
          credentials: "same-origin",
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.ok) {
          if (statusSpan) {
            statusSpan.textContent = "✓ Saved!";
            statusSpan.style.color = "green";
            setTimeout(() => { if (statusSpan) statusSpan.textContent = ""; }, 2500);
          }
          loadAdminData();
        } else {
          if (statusSpan) { statusSpan.textContent = data.error || "Save failed."; statusSpan.style.color = "var(--red)"; }
        }
      } catch (_) {
        if (statusSpan) { statusSpan.textContent = "Network error."; statusSpan.style.color = "var(--red)"; }
      } finally {
        if (saveBtn) saveBtn.disabled = false;
      }
    });

    const delBtn = form.querySelector(".btn-delete-contestant");
    if (delBtn) {
      delBtn.addEventListener("click", async () => {
        if (!confirm("Are you sure you want to delete this contestant?")) return;
        delBtn.disabled = true;
        try {
          const res = await fetch(`/api/admin/contestant/${cid}/delete`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
          });
          const data = await res.json().catch(() => ({}));
          if (res.ok && data.ok) {
            loadAdminData();
          } else {
            alert(data.error || "Failed to delete contestant.");
            delBtn.disabled = false;
          }
        } catch (_) {
          alert("Network error.");
          delBtn.disabled = false;
        }
      });
    }
  }

  async function addNewContestant(category) {
    try {
      const res = await fetch("/api/admin/contestant/new", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) loadAdminData();
      else alert(data.error || "Could not add contestant.");
    } catch (_) {
      alert("Network error.");
    }
  }

  // Voting control buttons
  if (btnStartVoting) {
    btnStartVoting.addEventListener("click", async () => {
      btnStartVoting.disabled = true;
      try {
        const res = await fetch("/api/admin/voting", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "start" }),
        });
        const data = await res.json();
        if (data.ok) {
          config.status = "active";
          updateVoterStatusUI("active", false);
          if (adminStatusBadge) { adminStatusBadge.textContent = "ACTIVE"; adminStatusBadge.className = "pill live"; }
          if (adminLiveBanner) { adminLiveBanner.style.display = "flex"; }
        } else {
          alert(data.error || "Failed to start voting.");
        }
      } catch (_) {
        alert("Failed to start voting.");
      } finally {
        btnStartVoting.disabled = false;
      }
    });
  }

  if (btnStopVoting) {
    btnStopVoting.addEventListener("click", async () => {
      btnStopVoting.disabled = true;
      try {
        const res = await fetch("/api/admin/voting", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "stop" }),
        });
        const data = await res.json();
        if (data.ok) {
          config.status = "closed";
          updateVoterStatusUI("closed", false);
          if (adminStatusBadge) { adminStatusBadge.textContent = "CLOSED"; adminStatusBadge.className = "pill closed"; }
          if (adminLiveBanner) { adminLiveBanner.style.display = "none"; }
        } else {
          alert(data.error || "Failed to stop voting.");
        }
      } catch (_) {
        alert("Failed to stop voting.");
      } finally {
        btnStopVoting.disabled = false;
      }
    });
  }

  if (btnResetVotes) {
    btnResetVotes.addEventListener("click", async () => {
      if (config.status === "active") {
        alert("Stop voting before resetting votes.");
        return;
      }
      if (!confirm("Are you sure?\n\nThis will permanently delete ALL votes.\n\nThis action cannot be undone.")) return;
      btnResetVotes.disabled = true;
      try {
        const res = await fetch("/api/admin/reset", { method: "POST" });
        const data = await res.json();
        if (data.ok) {
          alert("All votes have been reset.");
          loadAdminData();
        } else {
          alert(data.error || "Failed to reset votes.");
        }
      } catch (_) {
        alert("Failed to reset votes.");
      } finally {
        btnResetVotes.disabled = false;
      }
    });
  }

  // Bind existing SSR-rendered contestant forms
  if (adminContainerEl) {
    adminContainerEl.querySelectorAll(".contestant-form").forEach((form) => {
      bindContestantFormEvents(form, form.dataset.cid);
    });
    adminContainerEl.querySelectorAll(".btn-add-contestant").forEach((btn) => {
      btn.addEventListener("click", () => addNewContestant(btn.dataset.catKey));
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // 5. LIVE RESULTS — PROJECTOR VIEW
  // ─────────────────────────────────────────────────────────────────────────

  let _projFailures = 0;

  function openProjector() {
    if (!projectorView) return;
    projectorView.classList.add("active");
    _projFailures = 0;
    // Immediately render last known data if available
    if (lastKnownResults) renderProjectorResults(lastKnownResults);
    tickResults();
    if (projectorInterval) clearInterval(projectorInterval);
    projectorInterval = setInterval(tickResults, 2500);
  }

  function closeProjector() {
    if (projectorView) projectorView.classList.remove("active");
    if (projectorInterval) { clearInterval(projectorInterval); projectorInterval = null; }
  }

  if (btnOpenProjector) btnOpenProjector.addEventListener("click", openProjector);
  if (btnAdminQuickProjector) btnAdminQuickProjector.addEventListener("click", openProjector);
  if (btnBackToAdmin) btnBackToAdmin.addEventListener("click", closeProjector);

  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (projectorView && projectorView.classList.contains("active")) closeProjector();
      else if (adminLoginModal && adminLoginModal.classList.contains("active")) adminLoginModal.classList.remove("active");
    }
  });

  async function tickResults() {
    try {
      const res = await fetch("/api/results", { cache: "no-store" });
      if (!res.ok) throw new Error("not-ok");
      const data = await res.json();
      _projFailures = 0;
      lastKnownResults = data; // always preserve latest good response
      renderProjectorResults(data);
    } catch (_) {
      _projFailures++;
      // After 3 consecutive failures, show the reconnecting notice
      // but keep last known numbers on screen (don't zero out)
      if (_projFailures >= 3 && projCats) {
        const notice = document.createElement("p");
        notice.style.cssText = "color:#f88;font-weight:700;text-align:center;padding:12px";
        notice.textContent = "⚠ Connection interrupted — reconnecting…";
        // Only prepend if not already showing
        if (!projCats.querySelector(".conn-notice")) {
          notice.className = "conn-notice";
          projCats.prepend(notice);
        }
      }
    }
  }

  /**
   * Render the full auditorium-grade projector view.
   * Shows:
   *   - Per category: category title
   *   - CURRENT LEADER hero block (name + vote count + photo)
   *   - All 3 contestants with thumbnail, name, bar, exact count
   *   - On closed: winner / tie announcement
   */
  function renderProjectorResults(d) {
    if (!projCats || !projStatus) return;

    const open = d.status === "active";
    projStatus.textContent = open ? "LIVE VOTING" : "VOTING CLOSED";
    projStatus.className = "pill " + (open ? "live" : "closed");

    // Max votes for bar scaling (across all contestants, min 1)
    const allVotes = d.categories.flatMap((c) => c.items.map((i) => i.votes));
    const maxVotes = Math.max(1, ...allVotes);

    const sections = d.categories.map((cat) => {
      const sec = document.createElement("section");
      sec.className = "proj-cat";

      // ── Category title ────────────────────────────────────────────────────
      const h2 = document.createElement("h2");
      h2.textContent = "👑 " + cat.label.toUpperCase();
      sec.appendChild(h2);

      // ── CURRENT LEADER / WINNER block ─────────────────────────────────────
      const leader = cat.leader; // null if no votes yet or exact tie at 0
      if (leader || (cat.winner || cat.tie)) {
        const display = cat.tie
          ? null
          : (cat.winner ? cat.items.find((i) => i.name === cat.winner) : leader);

        const leaderBlock = document.createElement("div");
        leaderBlock.className = "proj-leader-block";

        if (cat.tie) {
          // Tie
          leaderBlock.innerHTML = `
            <span class="proj-leader-crown">🤝</span>
            <div class="proj-leader-info">
              <p class="proj-leader-label">RESULT</p>
              <p class="proj-leader-name" style="font-size:clamp(1.3rem,4vw,2.5rem)">TIE — Manual decision required</p>
            </div>
          `;
        } else if (display) {
          const imgEl = display.photo_url
            ? `<img src="${escHtml(display.photo_url)}" class="proj-leader-img" alt="${escHtml(display.name)}">`
            : `<div class="proj-leader-avatar">★</div>`;
          const labelText = open ? "CURRENT LEADER" : "🏆 WINNER";
          leaderBlock.innerHTML = `
            ${imgEl}
            <div class="proj-leader-info">
              <p class="proj-leader-label">${labelText}</p>
              <p class="proj-leader-name">${escHtml(display.name.toUpperCase())}</p>
              <p class="proj-leader-votes">${display.votes} VOTE${display.votes !== 1 ? "S" : ""}</p>
            </div>
            <span class="proj-leader-crown">${open ? "🥇" : "🏆"}</span>
          `;
        }

        sec.appendChild(leaderBlock);
      }

      // ── All contestants rows ──────────────────────────────────────────────
      cat.items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "proj-contestant-row";

        const thumbEl = item.photo_url
          ? `<img src="${escHtml(item.photo_url)}" class="proj-thumb" alt="${escHtml(item.name)}">`
          : `<div class="proj-thumb-avatar">★</div>`;

        const pct = (item.votes / maxVotes) * 100;

        row.innerHTML = `
          ${thumbEl}
          <span class="proj-contestant-name">${escHtml(item.name)}</span>
          <div class="proj-bar-wrap">
            <div class="proj-bar-fill" style="width:${pct}%"></div>
          </div>
          <span class="proj-vote-count">${item.votes}</span>
        `;

        sec.appendChild(row);
      });

      return sec;
    });

    projCats.replaceChildren(...sections);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // 6. HANDLE URL HASH (deep-link support)
  // ─────────────────────────────────────────────────────────────────────────

  if (window.location.hash === "#admin" || window.location.hash === "#login") {
    openAdmin();
  } else if (window.location.hash === "#results") {
    openProjector();
  }

  // ─────────────────────────────────────────────────────────────────────────
  // 7. INIT
  // ─────────────────────────────────────────────────────────────────────────
  refreshBallot();
})();
