/**
 * Market Watch web client
 */
(function () {
  "use strict";

  const ALL_COLUMNS = [
    { key: "rank", label: "Rank", type: "int", hint: "Overall rank by combined factor score (1 = highest)." },
    { key: "ticker", label: "Ticker", type: "text", hint: "Stock trading symbol." },
    { key: "name", label: "Company", type: "text", hint: "Company name." },
    { key: "sector", label: "Sector", type: "text", hint: "Industry sector." },
    { key: "composite", label: "Score", type: "float3", hint: "Weighted blend of momentum, value, quality, and low-volatility factors." },
    { key: "ret_12_1", label: "12-1M %", type: "pct", hint: "12-month price return excluding the most recent month." },
    { key: "ret_6m", label: "6M %", type: "pct", hint: "Price return over the past six months." },
    { key: "momentum_12_1", label: "Mom Z", type: "float3", hint: "Momentum z-score from 12-1 month return vs. the universe." },
    { key: "value_score", label: "Value Z", type: "float3", hint: "Value z-score from earnings yield and book-to-market." },
    { key: "quality_score", label: "Quality Z", type: "float3", hint: "Quality z-score from ROE, margins, and lower debt." },
    { key: "vol_60d", label: "Vol 60d", type: "float3", hint: "60-day annualized price volatility (lower is preferred)." },
    { key: "earnings_yield", label: "E/P", type: "pct", hint: "Earnings yield: earnings per dollar of share price (1 ÷ P/E)." },
    { key: "roe", label: "ROE", type: "pct", hint: "Return on equity: net income as a percent of shareholder equity." },
    { key: "market_cap", label: "Mkt Cap", type: "money", hint: "Total market value of outstanding shares." },
  ];

  const TABLE_COLUMN_KEYS = ["rank", "ticker", "name", "composite", "ret_12_1"];
  const TABLE_COLUMNS = TABLE_COLUMN_KEYS.map((key) => ALL_COLUMNS.find((c) => c.key === key));

  const COL_INFO_ICON =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<circle cx="12" cy="12" r="10"></circle><path d="M12 16v-4"></path><path d="M12 8h.01"></path></svg>';

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const els = {
    version: $("#app-version"),
    universe: $("#universe-limit"),
    minCap: $("#min-cap"),
    btnAction: $("#btn-action"),
    btnInfo: $("#btn-info"),
    btnInfoClose: $("#btn-info-close"),
    infoModal: $("#info-modal"),
    columnInfoModal: $("#column-info-modal"),
    columnInfoTitle: $("#column-info-title"),
    columnInfoBody: $("#column-info-body"),
    btnColumnInfoClose: $("#btn-column-info-close"),
    status: $("#status"),
    progress: $("#progress"),
    stockDetail: $("#stock-detail"),
    stockTab: $('.tab[data-tab="stock"]'),
    sectorHeader: $("#sector-header"),
    companyDetail: $("#company-detail"),
    tableAll: $("#table-all"),
    tableSector: $("#table-sector"),
    ptrIndicator: $("#ptr-indicator"),
    ptrLabel: $("#ptr-label"),
  };

  let busy = false;
  let pollTimer = null;
  let hasData = false;
  let selectedTicker = null;

  const DETAIL_TABS = new Set(["stock", "sector", "company"]);

  function minMarketCap() {
    return parseFloat(els.minCap.value, 10);
  }

  function updateActionButton() {
    const label = hasData ? "Refresh" : "Fetch Data";
    els.btnAction.textContent = label;
    els.btnAction.title = hasData
      ? "Re-rank stocks using cached data (applies current market-cap filter)"
      : "Download universe, prices, and fundamentals, then rank stocks";
  }

  function setHasData(value) {
    hasData = Boolean(value);
    updateActionButton();
  }

  function setBusy(value) {
    busy = value;
    els.btnAction.disabled = value;
    els.universe.disabled = value;
    els.minCap.disabled = value;
    els.progress.classList.toggle("hidden", !value);
    if (!value && els.ptrIndicator) setPtrState("hidden");
  }

  function setStatus(msg, isError) {
    els.status.textContent = msg;
    els.status.classList.toggle("error", Boolean(isError));
  }

  function reportError(context, err) {
    const msg = err && err.message ? err.message : String(err);
    console.error(`[Market Watch] ${context}:`, err);
    setStatus(`Error: ${msg}`, true);
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
      const err = new Error(msg);
      console.error(`[Market Watch] API ${path} failed (${res.status}):`, msg, data);
      throw err;
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
    return ALL_COLUMNS.find((c) => c.key === key) || ALL_COLUMNS[0];
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
      TABLE_COLUMNS.map((c) => {
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
          `<span class="th-inner">` +
          `<span class="th-label">${escapeHtml(c.label)}</span>` +
          `<button type="button" class="col-info-btn" data-col-key="${escapeAttr(c.key)}" ` +
          `aria-label="About ${escapeAttr(c.label)} column">${COL_INFO_ICON}</button>` +
          `<span class="sort-icon" aria-hidden="true">${icon}</span>` +
          `</span></th>`
        );
      }).join("") +
      "</tr>";

    thead.onclick = (e) => {
      const infoBtn = e.target.closest(".col-info-btn");
      if (infoBtn) {
        e.stopPropagation();
        const col = getColumn(infoBtn.dataset.colKey);
        if (col) openColumnInfoModal(col.label, col.hint);
        return;
      }
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
      tbody.innerHTML = `<tr class="empty-row"><td colspan="${TABLE_COLUMNS.length}">No data</td></tr>`;
      return;
    }

    tbody.innerHTML = rows
      .map((row) => {
        const cells = TABLE_COLUMNS.map((col) => {
          const val = row[col.key];
          const formatted = formatCell(col, val);
          const numCls = NUMERIC_TYPES.has(col.type) ? " num" : "";
          return `<td class="${numCls.trim()}">${escapeHtml(formatted)}</td>`;
        }).join("");
        return `<tr data-ticker="${escapeAttr(row.ticker)}"` +
          `${row.ticker === selectedTicker ? ' class="selected"' : ""}>${cells}</tr>`;
      })
      .join("");

    tbody.onclick = (e) => {
      const tr = e.target.closest("tr[data-ticker]");
      if (!tr || !onClick) return;
      onClick(tr.dataset.ticker);
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

  function findRow(ticker) {
    const sym = String(ticker || "").toUpperCase();
    for (const table of [els.tableAll, els.tableSector]) {
      const state = tableState.get(table);
      const row = state?.rows?.find((r) => String(r.ticker).toUpperCase() === sym);
      if (row) return row;
    }
    return null;
  }

  function showDetailTabs(ticker) {
    if (els.stockTab) {
      els.stockTab.hidden = false;
      els.stockTab.textContent = ticker || "Stock Detail";
    }
    $$(".tab").forEach((t) => {
      if (DETAIL_TABS.has(t.dataset.tab)) t.hidden = false;
    });
  }

  function renderStockDetail(row) {
    const ticker = row.ticker || "";
    const title = row.name ? `${row.name} (${ticker})` : ticker;
    els.stockDetail.innerHTML =
      `<h2 class="stock-detail-title">${escapeHtml(title)}</h2>` +
      `<p class="stock-detail-hint">Full factor metrics for this stock. Click <span class="info-inline" aria-hidden="true">ⓘ</span> for field descriptions.</p>` +
      `<div class="metric-grid">` +
      ALL_COLUMNS.map((col) => {
        const formatted = formatCell(col, row[col.key]);
        const numCls = NUMERIC_TYPES.has(col.type) ? " num" : "";
        let valueHtml = escapeHtml(formatted) || "—";
        if (col.key === "sector" && row.sector) {
          valueHtml +=
            ` <button type="button" class="link-btn sector-link" data-sector="${escapeAttr(row.sector)}">` +
            `View sector leaders</button>`;
        }
        return (
          `<div class="metric-row">` +
          `<div class="metric-label">` +
          `<span>${escapeHtml(col.label)}</span>` +
          `<button type="button" class="col-info-btn metric-info-btn" data-col-key="${escapeAttr(col.key)}" ` +
          `aria-label="About ${escapeAttr(col.label)}">${COL_INFO_ICON}</button>` +
          `</div>` +
          `<div class="metric-value${numCls}">${valueHtml}</div>` +
          `</div>`
        );
      }).join("") +
      `</div>`;

    els.stockDetail.querySelectorAll(".metric-info-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const col = getColumn(btn.dataset.colKey);
        if (col) openColumnInfoModal(col.label, col.hint);
      });
    });

    els.stockDetail.querySelectorAll(".sector-link").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const sector = btn.dataset.sector;
        if (sector) switchTab("sector");
      });
    });
  }

  function renderSectorPanel(sector, data) {
    renderTable(els.tableSector, data.rows, handleRowSelect, true);
    els.sectorHeader.innerHTML =
      `<strong>${escapeHtml(sector)}</strong> — ${data.count} stocks ranked within sector ` +
      `(same 6–12 month factors, z-scores vs sector peers only). Sector #1: <strong>${escapeHtml(data.top_pick || "n/a")}</strong>`;
  }

  function renderCompanyPanel(data) {
    els.companyDetail.innerHTML =
      data.title_html +
      `<div class="company-metrics"><p><strong>Key data</strong></p>${data.metrics_html}</div>` +
      `<div class="company-summary">${data.summary_html}</div>`;
  }

  async function selectRow(ticker, activeTab = "stock") {
    const row = findRow(ticker);
    if (!row) return;
    const sym = String(row.ticker).toUpperCase();
    const sector = row.sector ? String(row.sector).trim() : "";

    selectedTicker = sym;
    showDetailTabs(sym);
    renderStockDetail(row);
    renderTableBody(els.tableAll);
    if (tableState.get(els.tableSector)) renderTableBody(els.tableSector);

    setStatus(`Loading ${sym}…`);
    try {
      const requests = [
        api(`/api/companies/${encodeURIComponent(sym)}?min_market_cap=${minMarketCap()}`),
      ];
      if (sector) {
        requests.unshift(
          api(`/api/sectors/${encodeURIComponent(sector)}?min_market_cap=${minMarketCap()}`)
        );
      }
      const results = await Promise.all(requests);
      const sectorData = sector ? results[0] : null;
      const companyData = sector ? results[1] : results[0];
      if (sectorData) renderSectorPanel(sector, sectorData);
      renderCompanyPanel(companyData);
      if (sectorData) renderTableBody(els.tableSector);
      switchTab(activeTab);
      setStatus(`Showing ${sym}${sector ? ` and ${sector} sector leaders` : ""}.`);
    } catch (err) {
      reportError(`Row load failed (${sym})`, err);
    }
  }

  function openStockDetail(ticker) {
    selectRow(ticker, "stock");
  }

  function hideDetailTabs() {
    selectedTicker = null;
    $$(".tab").forEach((t) => {
      if (DETAIL_TABS.has(t.dataset.tab)) t.hidden = true;
    });
    const active = $(".tab.active");
    if (active && DETAIL_TABS.has(active.dataset.tab)) switchTab("all");
  }

  function switchTab(name) {
    const tab = $(`.tab[data-tab="${name}"]`);
    if (tab?.hidden) return;
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
    tab.addEventListener("click", () => {
      if (tab.hidden) return;
      switchTab(tab.dataset.tab);
    });
  });

  function clearSelection() {
    hideDetailTabs();
    if (tableState.get(els.tableAll)) renderTableBody(els.tableAll);
    if (tableState.get(els.tableSector)) renderTableBody(els.tableSector);
  }

  async function loadPicks() {
    clearSelection();
    const data = await api("/api/picks");
    renderTable(els.tableAll, data.rows, handleRowSelect, true);
    if (data.count) {
      setHasData(true);
      setStatus(
        `Showing cached screen (${data.count} stocks). Last data sync: ${data.last_sync || "unknown"}`
      );
    } else if (data.hint) {
      setHasData(data.universe_size > 0);
      setStatus(data.hint);
    } else {
      setHasData(false);
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
      clearSelection();
      renderTable(els.tableAll, data.rows, handleRowSelect, true);
      setHasData(true);
      setStatus(
        `Screen complete — top pick: ${data.top_pick || "n/a"} (${data.count} stocks ranked). ` +
        `Data sync: ${data.last_sync || "unknown"}`
      );
    } catch (err) {
      reportError("Screen failed", err);
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
      reportError("Data refresh failed to start", err);
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
          setStatus("Data refresh complete. Ranking stocks…");
          try {
            await runScreen();
          } catch (err) {
            reportError("Ranking after data refresh failed", err);
            setBusy(false);
          }
        } else if (job.status === "failed") {
          clearInterval(pollTimer);
          pollTimer = null;
          setBusy(false);
          reportError("Data refresh failed", new Error(job.error || "Refresh failed"));
        }
      } catch (err) {
        clearInterval(pollTimer);
        pollTimer = null;
        setBusy(false);
        reportError("Data refresh status check failed", err);
      }
    }, 1000);
  }

  function handleRowSelect(ticker) {
    if (!ticker) return;
    openStockDetail(ticker);
  }

  function openInfoModal() {
    if (els.infoModal && typeof els.infoModal.showModal === "function") {
      els.infoModal.showModal();
    }
  }

  function closeInfoModal() {
    if (els.infoModal && els.infoModal.open) {
      els.infoModal.close();
    }
  }

  function openColumnInfoModal(label, hint) {
    if (!els.columnInfoModal || typeof els.columnInfoModal.showModal !== "function") return;
    if (els.columnInfoTitle) els.columnInfoTitle.textContent = label;
    if (els.columnInfoBody) els.columnInfoBody.textContent = hint || "";
    els.columnInfoModal.showModal();
  }

  function closeColumnInfoModal() {
    if (els.columnInfoModal && els.columnInfoModal.open) {
      els.columnInfoModal.close();
    }
  }

  function onActionClick() {
    if (hasData) runScreen();
    else startRefresh();
  }

  const PTR_THRESHOLD = 72;
  const PTR_MAX = 110;
  const isCoarsePointer = () => window.matchMedia("(pointer: coarse)").matches;

  function activeScrollOffset() {
    const panel = $(".tab-panel.active");
    if (!panel) return { top: 0, left: 0 };
    const scrollables = panel.querySelectorAll(".table-wrap, .stock-detail, .company-detail");
    for (const el of scrollables) {
      const canScrollY = el.scrollHeight > el.clientHeight;
      const canScrollX = el.scrollWidth > el.clientWidth;
      if (canScrollY || canScrollX) {
        return { top: el.scrollTop, left: el.scrollLeft };
      }
    }
    return { top: 0, left: 0 };
  }

  function setPtrState(state, pullHeight) {
    const el = els.ptrIndicator;
    if (!el) return;
    el.classList.remove("hidden", "ready", "refreshing");
    if (state === "hidden") {
      el.classList.add("hidden");
      el.style.height = "0";
      el.setAttribute("aria-hidden", "true");
      return;
    }
    el.setAttribute("aria-hidden", "false");
    if (state === "pulling") {
      el.style.height = `${pullHeight}px`;
      el.classList.toggle("ready", pullHeight >= PTR_THRESHOLD);
      if (els.ptrLabel) {
        els.ptrLabel.textContent =
          pullHeight >= PTR_THRESHOLD ? "Release to refresh" : "Pull to refresh";
      }
    } else if (state === "refreshing") {
      el.classList.add("refreshing");
      el.style.height = "2.5rem";
      if (els.ptrLabel) els.ptrLabel.textContent = "Refreshing…";
    }
  }

  function initPullToRefresh() {
    if (!isCoarsePointer() || !els.ptrIndicator) return;

    let startX = 0;
    let startY = 0;
    let startScrollTop = 0;
    let startScrollLeft = 0;
    let ptrDisabled = false;
    let pulling = false;
    let pullDistance = 0;

    function resetPull() {
      pulling = false;
      pullDistance = 0;
      if (!busy) setPtrState("hidden");
    }

    document.addEventListener(
      "touchstart",
      (e) => {
        if (busy || els.infoModal?.open || els.columnInfoModal?.open) return;
        ptrDisabled = Boolean(e.target.closest(".table-wrap"));
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
        const scroll = activeScrollOffset();
        startScrollTop = scroll.top;
        startScrollLeft = scroll.left;
        pulling = false;
        pullDistance = 0;
      },
      { passive: true }
    );

    document.addEventListener(
      "touchmove",
      (e) => {
        if (
          ptrDisabled ||
          busy ||
          els.infoModal?.open ||
          els.columnInfoModal?.open ||
          startScrollTop > 0 ||
          startScrollLeft > 0
        ) {
          return;
        }
        const deltaX = e.touches[0].clientX - startX;
        const deltaY = e.touches[0].clientY - startY;
        if (Math.abs(deltaX) > Math.abs(deltaY)) {
          if (pulling) resetPull();
          return;
        }
        if (deltaY <= 0) {
          if (pulling) resetPull();
          return;
        }
        pulling = true;
        pullDistance = Math.min(deltaY * 0.45, PTR_MAX);
        setPtrState("pulling", pullDistance);
        if (pullDistance > 8) e.preventDefault();
      },
      { passive: false }
    );

    document.addEventListener(
      "touchend",
      () => {
        if (!pulling || busy || els.infoModal?.open || els.columnInfoModal?.open) {
          resetPull();
          return;
        }
        const shouldRefresh = pullDistance >= PTR_THRESHOLD;
        pulling = false;
        pullDistance = 0;
        if (shouldRefresh) {
          setPtrState("refreshing");
          onActionClick();
        } else {
          setPtrState("hidden");
        }
      },
      { passive: true }
    );
  }

  els.btnAction.addEventListener("click", onActionClick);
  els.btnInfo?.addEventListener("click", openInfoModal);
  els.btnInfoClose?.addEventListener("click", closeInfoModal);
  els.infoModal?.addEventListener("click", (e) => {
    if (e.target === els.infoModal) closeInfoModal();
  });
  els.infoModal?.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeInfoModal();
  });

  els.btnColumnInfoClose?.addEventListener("click", closeColumnInfoModal);
  els.columnInfoModal?.addEventListener("click", (e) => {
    if (e.target === els.columnInfoModal) closeColumnInfoModal();
  });
  els.columnInfoModal?.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeColumnInfoModal();
  });

  async function init() {
    try {
      const health = await api("/api/health");
      els.version.textContent = `${health.app} v${health.version}`;
    } catch (err) {
      els.version.textContent = "API unavailable";
      reportError("Cannot reach API", err);
      return;
    }
    try {
      const picks = await loadPicks();
      if (!picks.count) {
        const status = await api("/api/status");
        if (!status.universe_size) {
          setStatus("No market data yet. Click Fetch Data to download and rank stocks.");
        } else if (!status.cached_picks) {
          setHasData(true);
          setStatus(
            `Data loaded (${status.universe_size} stocks) but not ranked yet. Click Refresh to compute scores.`
          );
        }
      }
    } catch (err) {
      reportError("Error loading picks", err);
    }
  }

  initPullToRefresh();
  init();
})();
