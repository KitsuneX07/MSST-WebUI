import sys
import os
from PySide6.QtWidgets import QApplication

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
sys.path.append(project_root)

from ComfyGUI.editor.editor import ComfyGUIEditor

if __name__ == "__main__":
    app = QApplication([])
    editor = ComfyGUIEditor()
    sys.exit(app.exec())