"""Main application window."""
from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QTabWidget,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from market_watch.config import (
    APP_NAME,
    APP_VERSION,
    UI_FONT_FAMILY,
    UI_FONT_SIZE_DISCLAIMER,
    UI_FONT_SIZE_GUIDE,
    UI_FONT_SIZE_TITLE,
    UI_TABLE_FONT_SIZE,
    UI_TABLE_ROW_HEIGHT,
)
from market_watch.analysis.company_detail import build_company_detail
from market_watch.data.ingest import DataIngestor
from market_watch.db.store import Database
from market_watch.scoring.engine import ScoringEngine
from market_watch.ui.workers import run_refresh_all, run_screen

GUIDE_HTML = (
    "<ul style='margin-top:4px;margin-bottom:4px;padding-left:20px'>"
    "<li><b>What this is:</b> A ranked list of US stocks scored for a "
    "<b>6–12 month</b> holding window—not a price target or buy/sell signal.</li>"
    "<li><b>How ranking works:</b> Each stock gets a <b>Score</b> from momentum "
    "(12‑month return skipping the last month, plus 6‑month return), value "
    "(earnings & book yield), and quality (ROE, margins, lower debt).</li>"
    "<li><b>How to read the table:</b> Rank <b>1</b> = strongest combined factor "
    "profile in your universe; Z‑columns show how far above/below average each "
    "stock is on that factor.</li>"
    "<li><b>Data:</b> Prices from Yahoo/Stooq; fundamentals from Yahoo and SEC EDGAR. "
    "Use <b>Refresh Data</b> to download updates; <b>Refresh</b> to re-rank using "
    "data already on disk.</li>"
    "<li><b>Sectors:</b> Click any <b>Sector</b> cell to open <i>Sector Leaders</i> "
    "(re-ranked vs sector peers only).</li>"
    "<li><b>Company detail:</b> Click a <b>Ticker</b> or <b>Company</b> name for key metrics "
    "and a brief factor-based summary of strengths and risks.</li>"
    "</ul>"
)


class PicksTableModel(QAbstractTableModel):
    COLUMNS = [
        ("rank", "Rank"),
        ("ticker", "Ticker"),
        ("name", "Company"),
        ("sector", "Sector"),
        ("composite", "Score"),
        ("ret_12_1", "12-1M %"),
        ("ret_6m", "6M %"),
        ("momentum_12_1", "Mom Z"),
        ("value_score", "Value Z"),
        ("quality_score", "Quality Z"),
        ("vol_60d", "Vol 60d"),
        ("earnings_yield", "E/P"),
        ("roe", "ROE"),
        ("market_cap", "Mkt Cap"),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._df = pd.DataFrame()

    def set_dataframe(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self._df = df.copy() if df is not None else pd.DataFrame()
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._df)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.COLUMNS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.COLUMNS[section][1]
        return str(section + 1)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.TextAlignmentRole):
            return None
        if role == Qt.TextAlignmentRole:
            col_key = self.COLUMNS[index.column()][0]
            if col_key == "market_cap":
                return int(Qt.AlignHCenter | Qt.AlignVCenter)
            if col_key in ("rank", "ticker", "name", "sector"):
                return int(Qt.AlignLeft | Qt.AlignVCenter)
            return int(Qt.AlignRight | Qt.AlignVCenter)

        col_key = self.COLUMNS[index.column()][0]
        if col_key not in self._df.columns:
            return ""
        val = self._df.iloc[index.row()][col_key]
        if pd.isna(val):
            return ""
        if col_key in ("ret_12_1", "ret_6m", "earnings_yield", "roe"):
            return f"{float(val) * 100:.2f}%"
        if col_key == "market_cap":
            v = float(val)
            if v >= 1e12:
                return f"${v / 1e12:.2f}T"
            if v >= 1e9:
                return f"${v / 1e9:.2f}B"
            return f"${v / 1e6:.0f}M"
        if col_key in ("composite", "momentum_12_1", "momentum_6m", "value_score", "quality_score", "vol_60d"):
            return f"{float(val):.3f}"
        return str(val)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1280, 800)

        self.db = Database()
        self.ingestor = DataIngestor(self.db)
        self.engine = ScoringEngine(self.db)
        self._thread = None
        self._current_sector: str | None = None
        self._current_ticker: str | None = None
        self._tab_all = 0
        self._tab_sector = 1
        self._tab_company = 2

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        title_row = QHBoxLayout()
        title = QLabel("6–12 Month Factor Screener")
        title_font = QFont(UI_FONT_FAMILY, UI_FONT_SIZE_TITLE)
        title_font.setBold(True)
        title.setFont(title_font)
        title_row.addWidget(title)

        info_btn = QToolButton()
        info_btn.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
        info_btn.setToolTip("About Market Watch")
        info_btn.setAutoRaise(True)
        info_btn.clicked.connect(self._show_guide_dialog)
        title_row.addWidget(info_btn)
        title_row.addStretch()
        layout.addLayout(title_row)

        controls = QHBoxLayout()
        self.universe_spin = QSpinBox()
        self.universe_spin.setRange(20, 503)
        self.universe_spin.setValue(50)
        self.universe_spin.setPrefix("Universe: ")
        self.universe_spin.setSuffix(" stocks")
        controls.addWidget(self.universe_spin)

        self.cap_combo = QComboBox()
        self.cap_combo.addItems(
            [
                "Min cap: $2B+",
                "Min cap: $500M+",
                "Min cap: Any",
            ]
        )
        controls.addWidget(self.cap_combo)

        self.refresh_data_btn = QPushButton("Refresh Data")
        self.refresh_data_btn.setToolTip(
            "Download latest universe, prices, and fundamentals from the web"
        )
        self.refresh_data_btn.clicked.connect(self.on_refresh_data)
        controls.addWidget(self.refresh_data_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip(
            "Re-rank stocks using cached data (applies current market-cap filter)"
        )
        self.refresh_btn.clicked.connect(self.on_run_screen)
        controls.addWidget(self.refresh_btn)

        controls.addStretch()
        layout.addLayout(controls)

        self.status_label = QLabel("Ready. Use Refresh Data, then Refresh to rank stocks.")
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.tabs = QTabWidget()

        self.model = PicksTableModel()
        self.table = self._create_picks_table(self.model)
        self.table.setToolTip(
            "Click Sector, Ticker, or Company cells to drill down"
        )
        self.table.clicked.connect(
            lambda idx: self._on_picks_table_clicked(self.model, idx)
        )

        all_tab = QWidget()
        all_layout = QVBoxLayout(all_tab)
        all_layout.setContentsMargins(0, 0, 0, 0)
        all_layout.addWidget(self.table)
        self.tabs.addTab(all_tab, "All Stocks")

        self.sector_model = PicksTableModel()
        self.sector_table = self._create_picks_table(self.sector_model)
        self.sector_table.setToolTip(
            "Click Sector, Ticker, or Company cells to drill down"
        )
        self.sector_table.clicked.connect(
            lambda idx: self._on_picks_table_clicked(self.sector_model, idx)
        )
        self.sector_header = QLabel(
            "Click a Sector in All Stocks to see leading names in that sector."
        )
        self.sector_header.setWordWrap(True)
        sector_tab = QWidget()
        sector_layout = QVBoxLayout(sector_tab)
        sector_layout.setContentsMargins(0, 0, 0, 0)
        sector_layout.addWidget(self.sector_header)
        sector_layout.addWidget(self.sector_table)
        self.tabs.addTab(sector_tab, "Sector Leaders")

        self.company_title = QLabel("Click a Ticker or Company in any table to view details.")
        self.company_title.setWordWrap(True)
        self.company_metrics = QLabel()
        self.company_metrics.setWordWrap(True)
        self.company_metrics.setTextFormat(Qt.RichText)
        self.company_metrics.setAlignment(Qt.AlignTop)
        self.company_summary = QLabel()
        self.company_summary.setWordWrap(True)
        self.company_summary.setTextFormat(Qt.RichText)
        self.company_summary.setAlignment(Qt.AlignTop)

        company_inner = QWidget()
        company_inner_layout = QVBoxLayout(company_inner)
        company_inner_layout.addWidget(self.company_title)
        company_inner_layout.addWidget(self.company_metrics)
        company_inner_layout.addWidget(self.company_summary)
        company_inner_layout.addStretch()

        company_scroll = QScrollArea()
        company_scroll.setWidgetResizable(True)
        company_scroll.setWidget(company_inner)

        company_tab = QWidget()
        company_layout = QVBoxLayout(company_tab)
        company_layout.setContentsMargins(0, 0, 0, 0)
        company_layout.addWidget(company_scroll)
        self.tabs.addTab(company_tab, "Company Detail")

        layout.addWidget(self.tabs)

        disclaimer = QLabel(
            "Not investment advice. Rankings reflect historical factor scores only; "
            "past performance does not guarantee future results."
        )
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(
            f"color: #666; font-size: {UI_FONT_SIZE_DISCLAIMER}pt;"
        )
        layout.addWidget(disclaimer)

        self._load_cached_picks()

    def _show_guide_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("About Market Watch")
        dlg.setMinimumWidth(520)
        dlg_layout = QVBoxLayout(dlg)

        guide = QLabel(GUIDE_HTML)
        guide.setWordWrap(True)
        guide.setTextFormat(Qt.RichText)
        guide.setStyleSheet(f"font-size: {UI_FONT_SIZE_GUIDE}pt;")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(guide)
        dlg_layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(dlg.accept)
        dlg_layout.addWidget(buttons)
        dlg.exec()

    def _create_picks_table(self, model: PicksTableModel) -> QTableView:
        view = QTableView()
        view.setModel(model)
        view.setSelectionBehavior(QAbstractItemView.SelectRows)
        view.setAlternatingRowColors(True)
        header = view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)
        table_font = QFont(UI_FONT_FAMILY, UI_TABLE_FONT_SIZE)
        view.setFont(table_font)
        header_font = QFont(UI_FONT_FAMILY, UI_TABLE_FONT_SIZE)
        header_font.setBold(True)
        header.setFont(header_font)
        view.verticalHeader().setFont(table_font)
        view.verticalHeader().setDefaultSectionSize(UI_TABLE_ROW_HEIGHT)
        return view

    def _min_market_cap(self) -> float:
        idx = self.cap_combo.currentIndex()
        if idx == 0:
            return 2e9
        if idx == 1:
            return 5e8
        return 0.0

    def _set_busy(self, busy: bool) -> None:
        self.refresh_data_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy)
        self.universe_spin.setEnabled(not busy)
        self.cap_combo.setEnabled(not busy)
        if busy:
            self.progress.show()
        else:
            self.progress.hide()

    def _load_cached_picks(self) -> None:
        df = self.db.load_latest_picks()
        if not df.empty:
            self.model.set_dataframe(df)
            self.status_label.setText(
                f"Showing cached screen ({len(df)} stocks). Last data sync: "
                f"{self.db.last_sync_time() or 'unknown'}"
            )

    def _start_worker(self, thread) -> None:
        if self._thread and self._thread.isRunning():
            QMessageBox.warning(self, APP_NAME, "A task is already running.")
            return
        self._thread = thread
        self._set_busy(True)
        thread.signals.progress.connect(self.status_label.setText)
        thread.signals.error.connect(self._on_error)
        thread.signals.finished.connect(self._on_finished)
        thread.start()

    def on_refresh_data(self) -> None:
        limit = self.universe_spin.value()
        self._start_worker(run_refresh_all(self.ingestor, universe_limit=limit))

    def on_run_screen(self) -> None:
        cap = self._min_market_cap()
        self._start_worker(run_screen(self.engine, min_market_cap=cap))

    def _on_error(self, message: str) -> None:
        self._set_busy(False)
        QMessageBox.critical(self, APP_NAME, message)

    def _on_finished(self, result) -> None:
        self._set_busy(False)
        if isinstance(result, pd.DataFrame):
            self.model.set_dataframe(result)
            self.status_label.setText(
                f"Screen complete — top pick: {result.iloc[0]['ticker'] if len(result) else 'n/a'} "
                f"({len(result)} stocks ranked). "
                f"Data sync: {self.db.last_sync_time() or 'unknown'}"
            )
            if self._current_sector:
                self._show_sector(self._current_sector)
            if self._current_ticker:
                self._show_company(self._current_ticker)
        elif isinstance(result, str):
            self.status_label.setText(result)
            self._load_cached_picks()

    def _on_picks_table_clicked(self, model: PicksTableModel, index: QModelIndex) -> None:
        if model._df.empty:
            return
        col_key = PicksTableModel.COLUMNS[index.column()][0]
        row = model._df.iloc[index.row()]
        if col_key == "sector":
            sector = row.get("sector")
            if sector is None or (isinstance(sector, float) and pd.isna(sector)):
                return
            sector_str = str(sector).strip()
            if sector_str:
                self._show_sector(sector_str)
        elif col_key in ("ticker", "name"):
            ticker = row.get("ticker")
            if ticker is None or (isinstance(ticker, float) and pd.isna(ticker)):
                return
            ticker_str = str(ticker).strip().upper()
            if ticker_str:
                self._show_company(ticker_str)

    def _show_company(self, ticker: str) -> None:
        self._current_ticker = ticker
        try:
            detail = build_company_detail(
                ticker, self.db, self.engine, self._min_market_cap()
            )
        except ValueError as exc:
            QMessageBox.information(self, APP_NAME, str(exc))
            return
        title_font = QFont(UI_FONT_FAMILY, UI_FONT_SIZE_TITLE)
        title_font.setBold(True)
        self.company_title.setFont(title_font)
        self.company_title.setText(detail["title_html"])
        self.company_title.setTextFormat(Qt.RichText)
        self.company_metrics.setText(
            f"<p style='font-size:{UI_FONT_SIZE_GUIDE}pt'><b>Key data</b></p>"
            + detail["metrics_html"]
        )
        self.company_summary.setText(
            f"<p style='font-size:{UI_FONT_SIZE_GUIDE}pt'>{detail['summary_html']}</p>"
        )
        self.tabs.setCurrentIndex(self._tab_company)

    def _show_sector(self, sector: str) -> None:
        self._current_sector = sector
        try:
            ranked = self.engine.compute_for_sector(sector, self._min_market_cap())
        except ValueError as exc:
            QMessageBox.information(self, APP_NAME, str(exc))
            return
        self.sector_model.set_dataframe(ranked)
        top = ranked.iloc[0]["ticker"] if len(ranked) else "n/a"
        self.sector_header.setText(
            f"<b>{sector}</b> — {len(ranked)} stocks ranked within sector "
            f"(same 6–12 month factors, z-scores vs sector peers only). "
            f"Sector #1: <b>{top}</b>"
        )
        self.tabs.setCurrentIndex(self._tab_sector)
