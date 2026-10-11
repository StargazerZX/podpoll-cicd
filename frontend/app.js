/* PodPoll UI. Polls the API and renders the cards. Pure helpers live in logic.js. */
(function () {
  "use strict";
  const L = window.PodPollLogic;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const link = (url, text) => (L.isSafeUrl(url)
    ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>` : esc(text));

  // ---- this frontend's own build (stamped into <body> at image build time) ----------------
  const FE = document.body.dataset;
  const FRONTEND_VERSION = FE.version;
  document.body.dataset.major = L.majorOf(FRONTEND_VERSION);
  $("fe-ver").textContent = FRONTEND_VERSION;

  let seen = {};
  let platform = null;     // learned from the API's /api/info
  let apiBuild = null;
  let resetProtected = false;

  // Bars: widths are set through the CSSOM, because the CSP forbids inline style="" attributes.
  function applyBars(container) {
    container.querySelectorAll("i[data-w]").forEach((i) => { i.style.width = i.dataset.w + "%"; });
  }

  function banner(html) {
    const b = $("banner");
    b.innerHTML = html || "";
    b.classList.toggle("show", Boolean(html));
  }

  async function getJSON(url) {
    const res = await fetch(url, { cache: "no-store" });
    const fe = res.headers.get("X-Frontend-Pod");
    if (fe) $("fe-pod").textContent = fe;
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  // ---- platform-aware copy (all strings live in logic.js HINTS) ---------------------------
  function applyPlatform(p) {
    if (p === platform) return;
    platform = p;
    const h = L.hintsFor(p);
    if (!h) return;
    $("platform").textContent = "on " + p;
    $("platform").hidden = false;
    $("who-sub").textContent = h.whoSub;
    $("who-hint").textContent = h.whoHint;
    document.querySelectorAll(".instance-word").forEach((el) => { el.textContent = h.instance; });
    $("api-env-label").textContent = h.envLabel;
    $("nodes-title").textContent = h.nodesTitle;
    $("nodes-hint").textContent = h.nodesHint;
    $("storage-sub").textContent = h.storageSub;
    $("card-rbac").hidden = p !== "kubernetes";
    document.querySelectorAll(".task-row").forEach((el) => { el.hidden = p !== "ecs"; });
  }

  // ---- card 2: who answered? / card 1+4: which store? --------------------------------------
  async function pollInfo() {
    try {
      const d = await getJSON("/api/info");
      banner("");
      applyPlatform(d.platform || "docker");
      const h = L.hintsFor(platform);
      $("api-pod").textContent = d.pod;
      $("api-ver").textContent = d.version;
      $("api-node").textContent = d.node;
      const env = d.env || d.namespace;
      $("api-ns").textContent = platform === "kubernetes" ? d.namespace : env;
      if (d.task) $("api-task").textContent = `${d.task.family}:${d.task.revision}  (${d.task.cluster})`;
      const badge = $("env");
      badge.textContent = `${h.envLabel}: ${env}`;
      badge.classList.remove("env-unknown");
      badge.style.background = L.envColour(env);
      const chaos = L.chaosSummary(d.chaos);
      $("chaos").textContent = "chaos: " + chaos;
      $("chaos").hidden = !chaos;
      resetProtected = Boolean(d.reset_protected);
      seen[d.pod] = (seen[d.pod] || 0) + 1;
      renderSeen();

      const db = "<code>" + esc(d.db_server) + "</code>";
      if (d.store === "postgres") {
        $("vote-hint").innerHTML = h.votePostgres.replace("{db}", db);
        $("storage-hint").textContent = h.storagePostgres;
      } else {
        $("vote-hint").innerHTML = h.voteRedis;
        $("storage-hint").textContent = h.storageRedis;
      }
      $("store-kind").textContent = d.store;
      $("store-host").textContent = d.db_host;
      $("store-server").textContent = d.db_server;
      $("store-status").querySelector(".dot").classList.toggle("bad", !d.db_ok);
      $("store-status-text").textContent = d.db_ok ? "reachable" : "unreachable";
    } catch (e) {
      const h = L.hintsFor(platform);
      const cmds = h ? h.debug : L.UNKNOWN_PLATFORM_DEBUG;
      banner("⚠️ API unreachable (" + esc(e.message) + "). Debug it like a pro: " +
             cmds.map((c) => "<code>" + esc(c) + "</code>").join(" · "));
    }
  }

  function renderSeen() {
    const names = Object.keys(seen).sort();
    const max = Math.max(1, ...Object.values(seen));
    $("seen").innerHTML = names.map((n) =>
      `<div class="row seen"><span class="name">${esc(n)}</span>` +
      `<div class="bar"><i data-w="${(100 * seen[n]) / max}"></i></div><span>${seen[n]}</span></div>`).join("")
      || '<div class="empty">no responses yet</div>';
    applyBars($("seen"));
  }

  // ---- card 1: votes -------------------------------------------------------------------------
  async function pollResults() {
    try {
      const d = await getJSON("/api/results");
      if (d.question) $("question").textContent = d.question;
      const max = Math.max(1, ...d.results.map((r) => r.votes));
      $("options").innerHTML = d.results.map((r) =>
        `<div class="row"><b>${esc(r.option)}</b><div class="bar"><i data-w="${(100 * r.votes) / max}"></i></div>` +
        `<span>${r.votes}</span><button type="button" data-option="${esc(r.option)}">vote</button></div>`).join("");
      applyBars($("options"));
      $("total").textContent = "  total votes: " + d.total;
    } catch (e) {
      $("options").innerHTML = '<div class="empty">results unavailable right now</div>';
    }
  }

  async function vote(option) {
    const res = await fetch("/api/vote", { method: "POST", headers: { "Content-Type": "application/json" },
                                           body: JSON.stringify({ option }) }).catch(() => null);
    // The UI polls, so a failed vote self-corrects; but say so, so chaos is visible.
    $("vote-status").textContent = res && res.ok ? "" : `vote failed (${res ? "HTTP " + res.status : "network"})`;
    pollResults();
  }

  async function resetVotes() {
    const headers = {};
    if (resetProtected) {
      const token = window.prompt("Resetting votes is protected on this deployment. Reset token:");
      if (!token) return;
      headers["X-Reset-Token"] = token;
    }
    const res = await fetch("/api/reset", { method: "POST", headers }).catch(() => null);
    $("vote-status").textContent = res && res.ok ? "" : `reset failed (${res ? "HTTP " + res.status : "network"})`;
    pollResults();
  }

  // ---- card 3: nodes / host / tasks ------------------------------------------------------------
  async function pollNodes() {
    try {
      const d = await getJSON("/api/nodes");
      const h = L.hintsFor(platform) || L.HINTS.docker;
      if (!d.nodes.length) {
        $("nodes").innerHTML = `<div class="empty">${esc(h.nodesEmpty)}</div>`;
        return;
      }
      const ecs = platform === "ecs";
      const head = ecs
        ? "<th>task</th><th>az</th><th>launch type</th>"
        : "<th>node</th><th>agent " + esc(h.instance) + "</th>" + (h.showPodsOnNode ? "<th>pods on node</th>" : "");
      $("nodes").innerHTML =
        `<table><tr>${head}<th>load (1m)</th><th>mem used</th><th>kernel</th><th>last seen</th></tr>` +
        d.nodes.map((n) => {
          const first = ecs
            ? `<td><span class="dot"></span><b>${esc(n.node)}</b></td><td>${esc(n.az ?? "?")}</td><td>${esc(n.launch_type ?? "?")}</td>`
            : `<td><span class="dot"></span><b>${esc(n.node)}</b></td><td class="mono">${esc(n.agent_pod)}</td>` +
              (h.showPodsOnNode ? `<td>${esc(n.pods_on_node ?? "?")}</td>` : "");
          return `<tr>${first}<td>${esc(n.load1 ?? "?")}</td><td>${esc(n.mem_used_pct ?? "?")}%</td>` +
                 `<td class="mono">${esc(n.kernel)}</td><td>${esc(n.age_seconds)} s ago</td></tr>`;
        }).join("") + "</table>";
    } catch (e) {
      $("nodes").innerHTML = '<div class="empty">node list unavailable right now</div>';
    }
  }

  // ---- card 5: RBAC (Kubernetes only) ---------------------------------------------------------
  async function pollRbac() {
    if (platform !== "kubernetes") return;
    try {
      const d = await getJSON("/api/cluster/pods");
      $("rbac-identity").textContent = d.identity;
      const badge = $("rbac-badge");
      const body = $("rbac-body");
      if (d.allowed) {
        badge.textContent = "ALLOWED";
        badge.className = "rbac-badge allowed";
        body.innerHTML = d.pods.length
          ? "<table><tr><th>pod</th><th>phase</th><th>ready</th><th>node</th></tr>" +
            d.pods.map((p) => `<tr><td class="mono">${esc(p.name)}</td><td>${esc(p.phase)}</td>` +
              `<td>${esc(p.ready)}</td><td>${esc(p.node)}</td></tr>`).join("") + "</table>"
          : '<div class="empty">allowed, but no matching pods found</div>';
      } else {
        badge.textContent = d.status ? `FORBIDDEN (${d.status})` : "UNAVAILABLE";
        badge.className = "rbac-badge forbidden";
        body.innerHTML = '<div class="rbac-msg">' + esc(d.message) + "</div>" +
          '<div class="rbac-hint">That is RBAC saying no. Give the API its own ServiceAccount, a Role, and a RoleBinding.</div>';
      }
    } catch (e) {
      $("rbac-badge").textContent = "UNAVAILABLE";
      $("rbac-badge").className = "rbac-badge forbidden";
      $("rbac-body").innerHTML = '<div class="empty">RBAC status unavailable right now</div>';
    }
  }

  // ---- card 6: what's running? ------------------------------------------------------------------
  function buildCells(b) {
    if (!b) return ["…", "…", "…", "…", "…"];
    const sha = L.shortSha(b.git_sha);
    const build = b.build_id === "local" ? "local build" : "#" + b.build_id;
    return [
      esc(b.version),
      link(L.commitUrl(b.source_url, b.git_sha), sha),
      link(b.build_url, build),
      esc(b.ci_system),
      esc(L.ageText(b.build_time, Date.now())),
    ];
  }

  function renderBuild() {
    const fe = { version: FE.version, git_sha: FE.gitSha, build_id: FE.buildId, build_url: FE.buildUrl,
                 ci_system: FE.ciSystem, build_time: FE.buildTime, source_url: FE.sourceUrl };
    [["build-fe", fe], ["build-api", apiBuild]].forEach(([id, b]) => {
      const tds = $(id).querySelectorAll("td");
      buildCells(b).forEach((html, i) => { tds[i].innerHTML = html; });
    });
    $("mixed").hidden = !(apiBuild && L.isMixedRelease(FE.gitSha, apiBuild.git_sha));
    const refs = [`frontend ref: ${FE.gitRef}`];
    if (apiBuild) refs.push(`api ref: ${apiBuild.git_ref}`);
    $("build-ref").textContent = refs.join(" · ");
  }

  async function pollBuild() {
    try { apiBuild = await getJSON("/api/build"); } catch (e) { /* keep the last answer */ }
    renderBuild();
  }

  // ---- card 7: release security -----------------------------------------------------------------
  const SEVERITIES = ["critical", "high", "medium", "low"];

  async function pollSecurity() {
    let d;
    try { d = await getJSON("/api/release/security"); } catch (e) { return; }
    $("card-security").hidden = !d.available;
    if (!d.available) return;
    const s = d.summary || {};
    const totals = s.totals || {};
    const badge = $("security-badge");
    badge.textContent = (s.status || "unknown").toUpperCase() + (s.gate ? " · gate: " + s.gate : "");
    badge.className = "rbac-badge " + (s.status === "pass" ? "pass" : "fail");
    $("security-hint").textContent =
      `Scanned ${L.shortSha(s.git_sha)} (${s.version || "?"}), ${L.ageText(s.generated_at, Date.now())}. ` +
      `${totals.suppressed || 0} finding(s) accepted as risk.`;
    const rows = (s.tools || []).map((t) => {
      const f = t.findings || {};
      return `<tr><td>${esc(t.name)}</td><td class="muted">${esc(t.category || "")}</td>` +
        SEVERITIES.map((sev) => `<td class="num ${f[sev] ? "sev-" + sev : ""}">${esc(f[sev] ?? 0)}</td>`).join("") +
        `<td class="num">${esc(t.suppressed ?? 0)}</td><td class="status-${esc(t.status)}">${esc(t.status)}</td></tr>`;
    }).join("");
    $("security-body").innerHTML =
      "<table><tr><th>tool</th><th></th><th>crit</th><th>high</th><th>med</th><th>low</th><th>accepted</th><th>result</th></tr>" +
      rows + "</table>" + (s.report_url ? `<p class="small-print">${link(s.report_url, "full report ↗")}</p>` : "");
  }

  // ---- wiring (no inline onclick: the CSP forbids inline handlers) -----------------------------------
  $("options").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-option]");
    if (btn) vote(btn.dataset.option);
  });
  $("reset-btn").addEventListener("click", resetVotes);
  $("clear-btn").addEventListener("click", () => { seen = {}; renderSeen(); });

  renderSeen();
  renderBuild();
  pollInfo().then(() => { pollRbac(); pollNodes(); });
  pollResults(); pollBuild(); pollSecurity();
  setInterval(pollInfo, 1500);
  setInterval(pollResults, 3000);
  setInterval(pollNodes, 3000);
  setInterval(pollRbac, 3000);
  setInterval(pollBuild, 3000);
  setInterval(pollSecurity, 10000);
})();
