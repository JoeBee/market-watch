"""Application bootstrap."""
import logging
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from market_watch.config import APP_NAME, UI_FONT_FAMILY, UI_FONT_SIZE
from market_watch.ui.main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont(UI_FONT_FAMILY, UI_FONT_SIZE))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
