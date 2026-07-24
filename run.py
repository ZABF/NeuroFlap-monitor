import sys
from PyQt5.QtWidgets import QApplication
from ui.main_window import PlotWindow
from ui.theme import apply_dark_theme

app = QApplication(sys.argv)
apply_dark_theme(app)
win = PlotWindow()
win.show()
sys.exit(app.exec_())
