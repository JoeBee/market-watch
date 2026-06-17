/**
 * Market Watch web client
 */
(function () {
  "use strict";

  const COLUMNS = [
    { key: "rank", label: "Rank", type: "int" },
    { key: "ticker", label: "Ticker", type: "link-ticker" },
    { key: "name", label: "Company", type: "link-name" },
    { key: "sector", label: "Sector", type: "link-sector" },
    { key: "composite", label: "Score", type: "float3" },
    { key: "ret_12_1", label: "12-1M %", type: "pct" },
    { key: "ret_6m", label: "6M %", type: "pct" },
    { key: "momentum_12_1", label: "Mom Z", type: "float3" },
    { key: "value_score", label: "Value Z", type: "float3" },
    { key: "quality_score", label: "Quality Z", type: "float3" },
    { key: "vol_60d", label: "Vol 60d", type: "float3" },
    { key: "earnings_yield", label: "E/P", type: "pct" },
    { key: "roe", label: "ROE", type: "pct" },
    { key: "market_cap", label: "Mkt Cap", type: "money" },
  ];

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const els = {
    version: $("#app-version"),
    universe: $("#universe-limit"),
    minCap: $("#min-cap"),
    btnRefreshData: $("#btn-refresh-data"),
    btnRefresh: $("#btn-refresh"),
    status: $("#status"),
    progress: $("#progress"),
    sectorHeader: $("#sector-header"),
    companyDetail: $("#company-detail"),
    tableAll: $("#table-all"),
    tableSector: $("#table-sector"),
  };

  let busy = false;
  let pollTimer = null;

  function minMarketCap() {
    return parseFloat(els.minCap.value, 10);
  }

  function setBusy(value) {
    busy = value;
    els.btnRefreshData.disabled = value;
    els.btnRefresh.disabled = value;
    els.universe.disabled = value;
    els.minCap.disabled = value;
    els.progress.classList.toggle("hidden", !value);
  }

  function setStatus(msg) {
    els.status.textContent = msg;
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      let msg = data.detail || data.message || `Request failed (${res.status})`;
      if (Array.isArray(msg)) msg = msg.map((e) => e.msg || JSON.stringify(e)).join("; ");
      throw new Error(msg);
    }
    return data;
  }

  function fmtPct(val) {
    if (val == null || Number.isNaN(val)) return "";
    return (val * 100).toFixed(2) + "%";
  }

  function fmtFloat(val, d) {
    if (val == null || Number.isNaN(val)) return "";
    return Number(val).toFixed(d);
  }

  function fmtMoney(val) {
    if (val == null || Number.isNaN(val)) return "";
    const v = Number(val);
    if (v >= 1e12) return "$" + (v / 1e12).toFixed(2) + "T";
    if (v >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
    return "$" + Math.round(v / 1e6) + "M";
  }

  function formatCell(col, val) {
    if (val == null || (typeof val === "number" && Number.isNaN(val))) return "";
    switch (col.type) {
      case "pct": return fmtPct(val);
      case "float3": return fmtFloat(val, 3);
      case "money": return fmtMoney(val);
      case "int": return String(val);
      default: return String(val);
    }
  }

  const NUMERIC_TYPES = new Set(["int", "float3", "pct", "money"]);
  const tableState = new WeakMap();

  function getColumn(key) {
    return COLUMNS.find((c) => c.key === key) || COLUMNS[0];
  }

  function getSortValue(row, col) {
    const val = row[col.key];
    if (val == null || (typeof val === "number" && Number.isNaN(val))) return null;
    if (NUMERIC_TYPES.has(col.type)) return Number(val);
    return String(val).toLowerCase();
  }

  function sortRows(rows, sortKey, sortDir) {
    const col = getColumn(sortKey);
    const mult = sortDir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const av = getSortValue(a, col);
      const bv = getSortValue(b, col);
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      if (typeof av === "number" && typeof bv === "number") {
        return (av - bv) * mult;
      }
      return String(av).localeCompare(String(bv), undefined, { sensitivity: "base" }) * mult;
    });
  }

  function initTableState(table, rows, onClick) {
    const existing = tableState.get(table);
    tableState.set(table, {
      rows: rows || [],
      sortKey: existing?.sortKey || "rank",
      sortDir: existing?.sortDir || "asc",
      onClick,
    });
  }

  function buildTableHead(table) {
    const state = tableState.get(table);
    const thead = table.querySelector("thead");
    thead.innerHTML =
      "<tr>" +
      COLUMNS.map((c) => {
        const numCls = NUMERIC_TYPES.has(c.type) ? " num" : "";
        const active = state.sortKey === c.key ? " sort-active" : "";
        const ariaSort =
          state.sortKey === c.key
            ? state.sortDir === "asc"
              ? "ascending"
              : "descending"
            : "none";
        const icon =
          state.sortKey === c.key ? (state.sortDir === "asc" ? "↑" : "↓") : "↕";
        return (
          `<th class="sortable${numCls}${active}" data-sort-key="${c.key}" ` +
          `scope="col" aria-sort="${ariaSort}" title="Sort by ${escapeAttr(c.label)}">` +
          `${escapeHtml(c.label)}<span class="sort-icon" aria-hidden="true">${icon}</span></th>`
        );
      }).join("") +
      "</tr>";

    thead.onclick = (e) => {
      const th = e.target.closest("[data-sort-key]");
      if (!th) return;
      onHeaderClick(table, th.dataset.sortKey);
    };
  }

  function onHeaderClick(table, key) {
    const state = tableState.get(table);
    if (!state) return;
    if (state.sortKey === key) {
      state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
    } else {
      state.sortKey = key;
      state.sortDir = "asc";
    }
    buildTableHead(table);
    renderTableBody(table);
  }

  function renderTableBody(table) {
    const state = tableState.get(table);
    const tbody = table.querySelector("tbody");
    const rows = sortRows(state.rows, state.sortKey, state.sortDir);
    const onClick = state.onClick;

    if (!rows.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="${COLUMNS.length}">No data</td></tr>`;
      return;
    }

    tbody.innerHTML = rows
      .map((row) => {
        const cells = COLUMNS.map((col) => {
          const val = row[col.key];
          const formatted = formatCell(col, val);
          const numCls = NUMERIC_TYPES.has(col.type) ? " num" : "";
          if (col.type === "link-sector" && val) {
            return `<td class="clickable${numCls}" data-action="sector" data-value="${escapeAttr(val)}">${escapeHtml(val)}</td>`;
          }
          if ((col.type === "link-ticker" || col.type === "link-name") && row.ticker) {
            return `<td class="clickable${numCls}" data-action="company" data-value="${escapeAttr(row.ticker)}">${escapeHtml(formatted || val)}</td>`;
          }
          return `<td class="${numCls.trim()}">${escapeHtml(formatted)}</td>`;
        }).join("");
        return `<tr>${cells}</tr>`;
      })
      .join("");

    tbody.onclick = (e) => {
      const cell = e.target.closest("[data-action]");
      if (!cell || !onClick) return;
      onClick(cell.dataset.action, cell.dataset.value);
    };
  }

  function renderTable(table, rows, onClick, resetSort) {
    if (resetSort) {
      tableState.set(table, { rows: rows || [], sortKey: "rank", sortDir: "asc", onClick });
    } else {
      initTableState(table, rows, onClick);
    }
    buildTableHead(table);
    renderTableBody(table);
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, "&#39;");
  }

  function switchTab(name) {
    $$(".tab").forEach((t) => {
      const active = t.dataset.tab === name;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", active ? "true" : "false");
    });
    $$(".tab-panel").forEach((p) => {
      const id = p.id.replace("panel-", "");
      const active = id === name;
      p.classList.toggle("active", active);
      p.hidden = !active;
    });
  }

  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });

  async function loadPicks() {
    const data = await api("/api/picks");
    renderTable(els.tableAll, data.rows, handleTableClick, true);
    if (data.count) {
      setStatus(
        `Showing cached screen (${data.count} stocks). Last data sync: ${data.last_sync || "unknown"}`
      );
    }
    return data;
  }

  async function runScreen() {
    setBusy(true);
    setStatus("Computing factor scores…");
    try {
      const data = await api("/api/screen", {
        method: "POST",
        body: JSON.stringify({ min_market_cap: minMarketCap() }),
      });
      renderTable(els.tableAll, data.rows, handleTableClick, true);
      setStatus(
        `Screen complete — top pick: ${data.top_pick || "n/a"} (${data.count} stocks ranked). ` +
        `Data sync: ${data.last_sync || "unknown"}`
      );
    } finally {
      setBusy(false);
    }
  }

  async function startRefresh() {
    if (busy) return;
    setBusy(true);
    setStatus("Starting data refresh…");
    try {
      const { job_id } = await api("/api/refresh", {
        method: "POST",
        body: JSON.stringify({ universe_limit: parseInt(els.universe.value, 10) }),
      });
      pollJob(job_id);
    } catch (err) {
      setBusy(false);
      setStatus("Error: " + err.message);
    }
  }

  function pollJob(jobId) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const job = await api(`/api/jobs/${jobId}`);
        setStatus(job.message || job.status);
        if (job.status === "completed") {
          clearInterval(pollTimer);
          pollTimer = null;
          setBusy(false);
          await loadPicks();
          setStatus(job.result || "Data refresh complete.");
        } else if (job.status === "failed") {
          clearInterval(pollTimer);
          pollTimer = null;
          setBusy(false);
          setStatus("Error: " + (job.error || "Refresh failed"));
        }
      } catch (err) {
        clearInterval(pollTimer);
        pollTimer = null;
        setBusy(false);
        setStatus("Error: " + err.message);
      }
    }, 1000);
  }

  async function showSector(sector) {
    setStatus(`Loading sector: ${sector}…`);
    try {
      const data = await api(
        `/api/sectors/${encodeURIComponent(sector)}?min_market_cap=${minMarketCap()}`
      );
      renderTable(els.tableSector, data.rows, handleTableClick, true);
      els.sectorHeader.innerHTML =
        `<strong>${escapeHtml(sector)}</strong> — ${data.count} stocks ranked within sector ` +
        `(same 6–12 month factors, z-scores vs sector peers only). Sector #1: <strong>${escapeHtml(data.top_pick || "n/a")}</strong>`;
      switchTab("sector");
      setStatus(`Showing ${data.count} stocks in ${sector}.`);
    } catch (err) {
      setStatus("Error: " + err.message);
    }
  }

  async function showCompany(ticker) {
    setStatus(`Loading ${ticker}…`);
    try {
      const data = await api(
        `/api/companies/${encodeURIComponent(ticker)}?min_market_cap=${minMarketCap()}`
      );
      els.companyDetail.innerHTML =
        data.title_html +
        `<div class="company-metrics"><p><strong>Key data</strong></p>${data.metrics_html}</div>` +
        `<div class="company-summary">${data.summary_html}</div>`;
      switchTab("company");
      setStatus(`Showing details for ${ticker}.`);
    } catch (err) {
      setStatus("Error: " + err.message);
    }
  }

  function handleTableClick(action, value) {
    if (action === "sector") showSector(value);
    else if (action === "company") showCompany(value.toUpperCase());
  }

  els.btnRefreshData.addEventListener("click", startRefresh);
  els.btnRefresh.addEventListener("click", runScreen);

  async function init() {
    try {
      const health = await api("/api/health");
      els.version.textContent = `${health.app} v${health.version}`;
    } catch {
      els.version.textContent = "API unavailable";
      setStatus("Cannot reach API. Is the server running?");
      return;
    }
    try {
      await loadPicks();
    } catch (err) {
      setStatus("Error loading picks: " + err.message);
    }
  }

  init();
})();
