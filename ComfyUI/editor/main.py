import sys
import os
from PySide6.QtWidgets import QApplication

from editor import ComfyUIEditor

if __name__ == "__main__":
    app = QApplication([])
    os.chdir(os.path.join(os.path.dirname(__file__), "..", ".."))
    editor = ComfyUIEditor()
    sys.exit(app.exec())