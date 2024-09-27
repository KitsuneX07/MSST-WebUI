from PySide6.QtCore import Qt
from PySide6.QtGui import QPen, QColor, QBrush, QFont
from PySide6.QtWidgets import QGraphicsItem, QGraphicsDropShadowEffect, QGraphicsTextItem

from ComfyGUI.editor.node_port import InputPort, OutputPort, ParamPort, BoolPort, NodePort
from ComfyGUI.editor.node import Node
from ComfyGUI.editor.config import EditorConfig, NodeConfig


class DataFlowNode(Node):
    def __init__(self, title = '', input_ports = None, param_ports = None, output_ports = None, bool_ports = None,
                 scene = None, parent = None, upstream_node = None):
        super().__init__(title, input_ports, param_ports, output_ports, bool_ports, scene, parent, upstream_node)
        self.init_node_color()
        self.init_title()
        self.update_ports()

    def init_node_color(self):
        self._pen_selected = QPen(QColor('#ddffee00'))
        self._brush_background = QBrush(QColor('#dd151515'))
        self._title_bak_color = '#39c5bb'
        title_color = QColor(self._title_bak_color)
        self._pen_default = QPen(title_color)
        title_color.setAlpha(200)
        self._brush_title_back = QBrush(title_color)

    def init_title(self):
        self._title_font_size = EditorConfig.editor_node_title_font_size
        self._title_font = QFont(EditorConfig.editor_node_title_font, self._title_font_size)
        self._title_color = Qt.white

        self._title_line = QGraphicsTextItem(self)
        self._title_line.setPlainText(self._title)
        self._title_line.setFont(self._title_font)
        self._title_line.setDefaultTextColor(self._title_color)
        self._title_line.setPos(self.title_padding, self.title_padding)
        title_width = self._title_font_size * len(self._title) + 4 * self.title_padding
        self._node_width = max(self._node_width, title_width)
        self.title_height = 4 * self.title_padding + self._title_font_size


class InputNode(DataFlowNode):
    def __init__(self, title = 'Input Folder', input_ports = None, param_ports = None, output_ports = None,
                 bool_ports = None, scene = None, parent = None, upstream_node = None):
        super().__init__(title, input_ports, param_ports, output_ports, bool_ports, scene, parent, upstream_node)
        self.input_path = None

    def update_ports(self):
        param_port = ParamPort("Path", default_value = "input/")
        self.param_ports.append(param_port)
        output_port = OutputPort("")
        self.output_ports.append(output_port)

        param_port.add_to_parent_node(self, self._scene)
        output_port.add_to_parent_node(self, self._scene)
        param_port.setPos(self.port_padding, self.title_height + self.port_padding * 2)
        output_port.setPos(self._node_width - output_port._port_width - self.port_padding,
                           self.title_height + self.port_padding * 2)

    def get_input_path(self):
        self.input_path = self.param_ports[0].port_value
        return self.input_path


class OutputNode(DataFlowNode):
    def __init__(self, title = 'Output Folder', input_ports = None, param_ports = None, output_ports = None,
                 bool_ports = None, scene = None, parent = None, upstream_node = None):
        super().__init__(title, input_ports, param_ports, output_ports, bool_ports, scene, parent, upstream_node)
        self.output_path = None

    def update_ports(self):
        input_port = InputPort("")
        self.input_ports.append(input_port)
        input_port.add_to_parent_node(self, self._scene)
        input_port.setPos(self.port_padding, self.title_height + self.port_padding * 2)

        param_port = ParamPort("Path", default_value = "output/")
        self.param_ports.append(param_port)
        param_port.add_to_parent_node(self, self._scene)
        param_port.setPos(self.port_padding * 2 + input_port._port_width, self.title_height + self.port_padding * 2)

    def get_output_path(self):
        self.output_path = self.param_ports[0].port_value
        return self.output_path
