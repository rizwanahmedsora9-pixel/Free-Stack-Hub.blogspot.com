/* Indexing Console — progressive enhancement: inline actions, job polling, selection, theme. */
(function () {
  "use strict";

  // ---------- theme
  var toggle = document.getElementById("themeToggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", cur);
      try { localStorage.setItem("theme", cur); } catch (e) {}
    });
  }

  // ---------- toasts
  var wrap = document.createElement("div");
  wrap.className = "toast-wrap";
  document.body.appendChild(wrap);
  function toast(msg, kind) {
    var t = document.createElement("div");
    t.className = "toast " + (kind || "");
    t.textContent = msg;
    wrap.appendChild(t);
    setTimeout(function () { t.style.opacity = "0"; t.style.transition = "opacity .4s"; }, 4200);
    setTimeout(function () { t.remove(); }, 4800);
  }

  // ---------- inline inspect / push buttons (no full reload)
  function pillFor(row) {
    var v = row.verdict, cls = "muted", txt = "Unchecked";
    if (v === "PASS") { cls = "ok"; txt = "Indexed"; }
    else if (v === "FAIL") { cls = "danger"; txt = "Blocked"; }
    else if (v === "NEUTRAL") { cls = "warn"; txt = "Not indexed"; }
    else if (v === "ERROR") { cls = "danger"; txt = "Error"; }
    return '<span class="pill ' + cls + '" title="' + (row.coverage || "") + '">' + txt + "</span>" +
      (row.coverage ? '<div class="small muted cov">' + escapeHtml(row.coverage) + "</div>" : "");
  }
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]; }); }
  function ago(iso) {
    if (!iso) return "—";
    var s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return "just now";
    var u = [["y", 31536000], ["mo", 2592000], ["d", 86400], ["h", 3600], ["m", 60]];
    for (var i = 0; i < u.length; i++) if (s >= u[i][1]) return Math.floor(s / u[i][1]) + u[i][0] + " ago";
    return "just now";
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest(".js-act");
    if (!btn) return;
    ev.preventDefault();
    var id = btn.getAttribute("data-id"), act = btn.getAttribute("data-act");
    var tr = btn.closest("tr");
    btn.classList.add("loading");
    var old = btn.textContent;
    btn.textContent = act === "push" ? "Pushing…" : "Checking…";
    fetch("/url/" + id + "/" + act, { method: "POST", headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        btn.classList.remove("loading");
        btn.textContent = old;
        if (d.ok) {
          toast(act === "push" ? "Pushed — Google accepted the notification." : ("Inspected: " + d.verdict + " — " + (d.coverage || "")), "ok");
        } else {
          toast((act === "push" ? "Push failed: " : "Inspection failed: ") + (d.error || "") + (d.hint ? " · " + d.hint : ""), "err");
        }
        if (tr && d.row) updateRow(tr, d.row);
      })
      .catch(function (e) { btn.classList.remove("loading"); btn.textContent = old; toast("Request failed: " + e, "err"); });
  });

  function updateRow(tr, row) {
    var st = tr.querySelector(".cell-status"); if (st) st.innerHTML = pillFor(row);
    var cr = tr.querySelector(".cell-crawl"); if (cr) cr.innerHTML = row.last_crawl ? '<span title="' + row.last_crawl + '">' + ago(row.last_crawl) + "</span>" : (row.verdict && row.verdict !== "ERROR" ? '<span class="warn-text">never</span>' : '<span class="muted">—</span>');
    var bt = tr.querySelector(".cell-bot"); if (bt) bt.innerHTML = row.crawled_as ? '<span class="bot">' + (row.crawled_as === "MOBILE" ? "📱" : "🖥") + " " + row.crawled_as.toLowerCase() + "</span>" : '<span class="muted">—</span>';
    var ins = tr.querySelector(".cell-insp"); if (ins) ins.innerHTML = row.inspected_at ? "<span>" + ago(row.inspected_at) + "</span>" : '<span class="muted">—</span>';
    var pu = tr.querySelector(".cell-push"); if (pu) pu.innerHTML = row.pushed_at ? '<span class="' + (row.push_status === "ok" ? "ok-text" : "err-text") + '">' + (row.push_status === "ok" ? "✓" : "✕") + " " + ago(row.pushed_at) + "</span>" + (row.push_count > 1 ? ' <span class="muted small">×' + row.push_count + "</span>" : "") : '<span class="muted">—</span>';
    // dashboard compact table uses different cells: fall back to the 2nd/3rd/4th columns
    if (!st) {
      var tds = tr.querySelectorAll("td");
      if (tds.length >= 4) {
        tds[1].innerHTML = pillFor(row);
        tds[2].innerHTML = row.last_crawl ? ago(row.last_crawl) : '<span class="muted">never</span>';
        tds[3].innerHTML = row.pushed_at ? '<span class="' + (row.push_status === "ok" ? "ok-text" : "err-text") + '">' + ago(row.pushed_at) + "</span>" : '<span class="muted">—</span>';
      }
    }
    var pushBtn = tr.querySelector('.js-act[data-act="push"]');
    if (pushBtn) pushBtn.disabled = row.verdict === "PASS";
    tr.classList.remove("flash-row"); void tr.offsetWidth; tr.classList.add("flash-row");
  }

  // ---------- selection (URLs table)
  var selAll = document.getElementById("selAll"), bulkbar = document.getElementById("bulkbar"), selCount = document.getElementById("selCount");
  function refreshSel() {
    var boxes = document.querySelectorAll("input.sel");
    var n = 0; boxes.forEach(function (b) { if (b.checked) n++; });
    if (selCount) selCount.textContent = n;
    if (bulkbar) bulkbar.classList.toggle("show", n > 0);
    if (selAll) { selAll.checked = n > 0 && n === boxes.length; selAll.indeterminate = n > 0 && n < boxes.length; }
  }
  if (selAll) selAll.addEventListener("change", function () { document.querySelectorAll("input.sel").forEach(function (b) { b.checked = selAll.checked; }); refreshSel(); });
  document.addEventListener("change", function (e) { if (e.target.classList && e.target.classList.contains("sel")) refreshSel(); });
  var selNone = document.getElementById("selNone");
  if (selNone) selNone.addEventListener("click", function () { document.querySelectorAll("input.sel").forEach(function (b) { b.checked = false; }); refreshSel(); });
  var bulkForm = document.getElementById("bulkForm");
  if (bulkForm) bulkForm.addEventListener("submit", function (e) {
    var kind = e.submitter && e.submitter.value;
    if (kind === "push_selected") {
      var n = document.querySelectorAll("input.sel:checked").length;
      if (!confirm("Push " + n + " URL(s) to the Indexing API? Each uses 1 of the 200 daily calls.")) e.preventDefault();
    }
  });

  // ---------- file drop label
  var fd = document.getElementById("filedrop");
  if (fd) {
    var inp = fd.querySelector("input[type=file]"), txt = fd.querySelector(".filedrop-text");
    inp.addEventListener("change", function () { if (inp.files[0]) { fd.classList.add("has"); txt.innerHTML = "<b>" + escapeHtml(inp.files[0].name) + "</b><br><small>ready to upload</small>"; } });
    ["dragenter", "dragover"].forEach(function (n) { fd.addEventListener(n, function (e) { e.preventDefault(); fd.classList.add("drag"); }); });
    ["dragleave", "drop"].forEach(function (n) { fd.addEventListener(n, function (e) { e.preventDefault(); fd.classList.remove("drag"); }); });
    fd.addEventListener("drop", function (e) { if (e.dataTransfer.files.length) { inp.files = e.dataTransfer.files; inp.dispatchEvent(new Event("change")); } });
  }

  // ---------- job polling: update the progress bar, reload when a job finishes
  var jobbar = document.getElementById("jobbar"), jobText = document.getElementById("jobText"), jobFill = document.getElementById("jobFill");
  var wasActive = window.__JOB_ACTIVE__;
  function poll() {
    fetch("/api/job", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (j) {
      var active = j && (j.status === "running" || j.status === "queued");
      if (active) {
        jobbar.classList.add("show");
        var pct = j.total ? Math.round(j.done * 100 / j.total) : 0;
        jobText.textContent = (j.kind || "").replace(/_/g, " ") + " · " + j.done + "/" + j.total + (j.err_count ? " · " + j.err_count + " failed" : "");
        jobFill.style.width = pct + "%";
        wasActive = true;
        setTimeout(poll, 1500);
      } else {
        jobbar.classList.remove("show");
        if (wasActive) {
          wasActive = false;
          toast("Job finished: " + ((j && j.message) || "done"), j && j.status === "failed" ? "err" : "ok");
          setTimeout(function () { location.reload(); }, 900);
        } else {
          setTimeout(poll, 6000);
        }
      }
    }).catch(function () { setTimeout(poll, 5000); });
  }
  if (jobbar) setTimeout(poll, wasActive ? 800 : 6000);
})();
