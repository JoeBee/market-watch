"""Main application window."""
from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QRect
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
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

COLUMN_HINTS: dict[str, str] = {
    "rank": "Overall rank by combined factor score (1 = highest).",
    "ticker": "Stock trading symbol. Click for company detail.",
    "name": "Company name. Click for company detail.",
    "sector": "Industry sector. Click to view sector leaders.",
    "composite": "Weighted blend of momentum, value, quality, and low-volatility factors.",
    "ret_12_1": "12-month price return excluding the most recent month.",
    "ret_6m": "Price return over the past six months.",
    "momentum_12_1": "Momentum z-score from 12-1 month return vs. the universe.",
    "value_score": "Value z-score from earnings yield and book-to-market.",
    "quality_score": "Quality z-score from ROE, margins, and lower debt.",
    "vol_60d": "60-day annualized price volatility (lower is preferred).",
    "earnings_yield": "Earnings yield: earnings per dollar of share price (1 ÷ P/E).",
    "roe": "Return on equity: net income as a percent of shareholder equity.",
    "market_cap": "Total market value of outstanding shares.",
}


class ColumnInfoHeader(QHeaderView):
    """Horizontal header with a clickable info icon per column."""

    ICON_SIZE = 16
    ICON_MARGIN = 4

    def __init__(
        self,
        columns: list[tuple[str, str]],
        hints: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(Qt.Horizontal, parent)
        self._columns = columns
        self._hints = hints
        self.setSectionsClickable(True)
        self.setHighlightSections(True)
        self.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:
        super().paintSection(painter, rect, logical_index)
        if logical_index < 0 or logical_index >= len(self._columns):
            return
        icon_rect = self._icon_rect_for_section(rect)
        painter.save()
        painter.setPen(self.palette().color(self.palette().ColorRole.ButtonText))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(7, font.pointSize() - 2))
        painter.setFont(font)
        painter.drawText(icon_rect, int(Qt.AlignCenter), "i")
        painter.restore()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            idx = self.logicalIndexAt(event.pos())
            if idx >= 0 and self._icon_rect(idx).contains(event.pos()):
                self._show_hint(idx)
                event.accept()
                return
        super().mousePressEvent(event)

    def _icon_rect(self, logical_index: int) -> QRect:
        x = self.sectionViewportPosition(logical_index)
        w = self.sectionSize(logical_index)
        return self._icon_rect_for_section(QRect(x, 0, w, self.height()))

    def _icon_rect_for_section(self, rect: QRect) -> QRect:
        return QRect(
            rect.right() - self.ICON_SIZE - self.ICON_MARGIN,
            rect.center().y() - self.ICON_SIZE // 2,
            self.ICON_SIZE,
            self.ICON_SIZE,
        )

    def _show_hint(self, logical_index: int) -> None:
        key, label = self._columns[logical_index]
        hint = self._hints.get(key)
        if hint:
            QMessageBox.information(self.window(), label, hint)


GUIDE_HTML = (
    "<ul style='margin-top:4px;margin-bottom:4px;padding-left:20px'>"
    "<li><b>What this is:</b> A ranked list of US stocks scored for a "
    "<b>6–12 month</b> holding window—not a price target or buy/sell signal.</li>"
    "<li><b>How ranking works:</b> Each stock gets a <b>Score</b> from momentum "
    "(12‑month return skipping the last month, plus 6‑month return), value "
    "(earnings & book yield), and quality (ROE, margins, lower debt).</li>"
    "<li><b>How to read the table:</b> Rank <b>1</b> = strongest combined factor "
    "profile. Click any row to see all metrics in a detail tab.</li>"
    "<li><b>Data:</b> Prices from Yahoo/Stooq; fundamentals from Yahoo and SEC EDGAR. "
    "Use <b>Refresh Data</b> to download updates; <b>Refresh</b> to re-rank using "
    "data already on disk.</li>"
    "<li><b>Tabs:</b> <i>Stock Detail</i> shows all row metrics; <i>Sector Leaders</i> "
    "re-ranks vs sector peers; <i>Company Detail</i> adds a factor-based narrative.</li>"
    "<li><b>Column help:</b> Click the <b>i</b> icon in a column header or detail "
    "field for a short description.</li>"
    "</ul>"
)


class PicksTableModel(QAbstractTableModel):
    TABLE_COLUMNS = [
        ("rank", "Rank"),
        ("ticker", "Ticker"),
        ("name", "Company"),
        ("composite", "Score"),
        ("ret_12_1", "12-1M %"),
    ]
    ALL_COLUMNS = [
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
    COLUMNS = TABLE_COLUMNS

    @staticmethod
    def format_value(col_key: str, val) -> str:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return "—"
        if col_key in ("ret_12_1", "ret_6m", "earnings_yield", "roe"):
            return f"{float(val) * 100:.2f}%"
        if col_key == "market_cap":
            v = float(val)
            if v >= 1e12:
                return f"${v / 1e12:.2f}T"
            if v >= 1e9:
                return f"${v / 1e9:.2f}B"
            return f"${v / 1e6:.0f}M"
        if col_key in (
            "composite",
            "momentum_12_1",
            "momentum_6m",
            "value_score",
            "quality_score",
            "vol_60d",
        ):
            return f"{float(val):.3f}"
        if col_key == "rank":
            return str(int(val))
        return str(val)

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
            if col_key in ("rank", "ticker", "name"):
                return int(Qt.AlignLeft | Qt.AlignVCenter)
            return int(Qt.AlignRight | Qt.AlignVCenter)

        col_key = self.COLUMNS[index.column()][0]
        if col_key not in self._df.columns:
            return ""
        val = self._df.iloc[index.row()][col_key]
        if pd.isna(val):
            return ""
        return self.format_value(col_key, val)


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
        self._tab_stock = 1
        self._tab_sector = 2
        self._tab_company = 3

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
        self.table.setToolTip("Click any row to view full stock metrics")
        self.table.clicked.connect(
            lambda idx: self._on_picks_table_clicked(self.model, idx)
        )

        all_tab = QWidget()
        all_layout = QVBoxLayout(all_tab)
        all_layout.setContentsMargins(0, 0, 0, 0)
        all_layout.addWidget(self.table)
        self.tabs.addTab(all_tab, "All Stocks")

        self.stock_detail_title = QLabel("Click a row in All Stocks to view full metrics.")
        self.stock_detail_title.setWordWrap(True)
        title_font = QFont(UI_FONT_FAMILY, UI_FONT_SIZE_TITLE)
        title_font.setBold(True)
        self.stock_detail_title.setFont(title_font)

        self.stock_detail_metrics = QWidget()
        self.stock_detail_metrics_layout = QGridLayout(self.stock_detail_metrics)
        self.stock_detail_metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.stock_detail_metrics_layout.setHorizontalSpacing(8)
        self.stock_detail_metrics_layout.setVerticalSpacing(10)

        stock_inner = QWidget()
        stock_inner_layout = QVBoxLayout(stock_inner)
        stock_inner_layout.addWidget(self.stock_detail_title)
        stock_inner_layout.addWidget(self.stock_detail_metrics)
        stock_inner_layout.addStretch()

        stock_scroll = QScrollArea()
        stock_scroll.setWidgetResizable(True)
        stock_scroll.setWidget(stock_inner)

        stock_tab = QWidget()
        stock_tab.setStyleSheet("background-color: #121820;")
        stock_layout = QVBoxLayout(stock_tab)
        stock_layout.setContentsMargins(0, 0, 0, 0)
        stock_layout.addWidget(stock_scroll)
        self.tabs.addTab(stock_tab, "Stock Detail")

        self.sector_model = PicksTableModel()
        self.sector_table = self._create_picks_table(self.sector_model)
        self.sector_table.setToolTip("Click any row to view full stock metrics")
        self.sector_table.clicked.connect(
            lambda idx: self._on_picks_table_clicked(self.sector_model, idx)
        )
        self.sector_header = QLabel(
            "Sector leaders appear here when you select a stock."
        )
        self.sector_header.setWordWrap(True)
        sector_tab = QWidget()
        sector_tab.setStyleSheet("background-color: #121a16;")
        sector_layout = QVBoxLayout(sector_tab)
        sector_layout.setContentsMargins(0, 0, 0, 0)
        sector_layout.addWidget(self.sector_header)
        sector_layout.addWidget(self.sector_table)
        self.tabs.addTab(sector_tab, "Sector Leaders")

        self.company_title = QLabel("Factor-based company summary appears when you select a stock.")
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
        company_tab.setStyleSheet("background-color: #1a161c;")
        company_layout = QVBoxLayout(company_tab)
        company_layout.setContentsMargins(0, 0, 0, 0)
        company_layout.addWidget(company_scroll)
        self.tabs.addTab(company_tab, "Company Detail")

        self.tabs.setStyleSheet(
            "QTabBar::tab { padding: 8px 14px; margin-right: 2px; background: #21262d; }"
            "QTabBar::tab:selected { font-weight: 600; }"
            "QTabBar::tab:nth-child(2) { background-color: #1a2030; color: #8b949e; }"
            "QTabBar::tab:nth-child(2):selected { background-color: #1e2840; color: #58a6ff; }"
            "QTabBar::tab:nth-child(3) { background-color: #1a2820; color: #8b949e; }"
            "QTabBar::tab:nth-child(3):selected { background-color: #1e3224; color: #3fb950; }"
            "QTabBar::tab:nth-child(4) { background-color: #221a28; color: #8b949e; }"
            "QTabBar::tab:nth-child(4):selected { background-color: #2a2034; color: #d2a8ff; }"
        )

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
        header = ColumnInfoHeader(PicksTableModel.COLUMNS, COLUMN_HINTS, view)
        view.setHorizontalHeader(header)
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
                row = self.model._df[
                    self.model._df["ticker"].astype(str).str.upper() == self._current_ticker
                ]
                if not row.empty:
                    self._show_stock_detail(row.iloc[0])
                else:
                    self._show_company(self._current_ticker)
        elif isinstance(result, str):
            self.status_label.setText(result)
            self._load_cached_picks()

    def _clear_stock_detail_metrics(self) -> None:
        while self.stock_detail_metrics_layout.count():
            item = self.stock_detail_metrics_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _show_stock_detail(self, row: pd.Series) -> None:
        ticker = row.get("ticker")
        if ticker is None or (isinstance(ticker, float) and pd.isna(ticker)):
            return
        ticker_str = str(ticker).strip().upper()
        if not ticker_str:
            return

        self._current_ticker = ticker_str
        name = row.get("name")
        title = f"{name} ({ticker_str})" if name and not pd.isna(name) else ticker_str
        self.stock_detail_title.setText(title)
        self.tabs.setTabText(self._tab_stock, ticker_str)

        self._clear_stock_detail_metrics()
        for row_idx, (col_key, label) in enumerate(PicksTableModel.ALL_COLUMNS):
            label_widget = QLabel(label)
            label_font = QFont(UI_FONT_FAMILY, UI_FONT_SIZE)
            label_font.setBold(True)
            label_widget.setFont(label_font)

            info_btn = QToolButton()
            info_btn.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
            info_btn.setAutoRaise(True)
            hint = COLUMN_HINTS.get(col_key, "")
            info_btn.setToolTip("About this field")
            info_btn.clicked.connect(
                lambda _checked=False, field_label=label, field_hint=hint: QMessageBox.information(
                    self, field_label, field_hint
                )
            )

            val = row.get(col_key) if col_key in row.index else None
            value_widget = QLabel(PicksTableModel.format_value(col_key, val))
            value_widget.setTextInteractionFlags(Qt.TextSelectableByMouse)

            self.stock_detail_metrics_layout.addWidget(label_widget, row_idx, 0)
            self.stock_detail_metrics_layout.addWidget(info_btn, row_idx, 1)
            self.stock_detail_metrics_layout.addWidget(value_widget, row_idx, 2)

        self.tabs.setCurrentIndex(self._tab_stock)
        self.status_label.setText(f"Showing full metrics for {ticker_str}.")

        sector = row.get("sector")
        if sector is not None and not (isinstance(sector, float) and pd.isna(sector)):
            sector_str = str(sector).strip()
            if sector_str:
                self._show_sector(sector_str)
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

    def _on_picks_table_clicked(self, model: PicksTableModel, index: QModelIndex) -> None:
        if model._df.empty:
            return
        row = model._df.iloc[index.row()]
        self._show_stock_detail(row)
