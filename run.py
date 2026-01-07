import sys
from PyQt5.QtWidgets import QApplication
from ui.main_window import PlotWindow

app = QApplication(sys.argv)
win = PlotWindow()
win.show()
sys.exit(app.exec_())
