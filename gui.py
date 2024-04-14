import sys
import time
import signal

from PyQt5.QtWidgets import QApplication, QWidget, QSlider, QHBoxLayout, QVBoxLayout, QLabel, QMainWindow, QPushButton, QStackedLayout, QGraphicsOpacityEffect
from PyQt5.QtCore import Qt, QThread, QRunnable, pyqtSlot, QThreadPool, QObject, pyqtSignal, QRect
from PyQt5.QtGui import QPainter, QColor, QPen
from tango import AttributeProxy, DeviceProxy

# prefix for all Tango device names
TANGO_NAME_PREFIX = "epfl"

# definition of Tango attribute and command names
TANGO_ATTRIBUTE_LEVEL = "level"
TANGO_ATTRIBUTE_VALVE = "valve"
TANGO_ATTRIBUTE_FLOW = "flow"
TANGO_ATTRIBUTE_COLOR = "color"
TANGO_COMMAND_FILL = "Fill"
TANGO_COMMAND_FLUSH = "Flush"


class TankWidget(QWidget):
    """
    Widget that displays the paint tank and valve
    """
    MARGIN_BOTTOM = 50
    VALVE_WIDTH = 15

    def __init__(self, tank_width, tank_height=200, level=0):
        super().__init__()
        self.fill_color = QColor("grey")
        self.fill_level = level
        self.tank_height = tank_height
        self.tank_width = tank_width
        self.valve = 0
        self.flow = 0
        self.setMinimumSize(self.tank_width, self.tank_height + self.MARGIN_BOTTOM)

    def setValve(self, valve):
        """
        set the valve level between 0 and 100
        """
        self.valve = valve

    def setFlow(self, flow):
        """
        set the value of the flow label
        """
        self.flow = flow

    def setColor(self, color):
        """
        set the color of the paint in hex format (e.g. #000000)
        """
        self.fill_color = QColor(color)

    def paintEvent(self, event):
        """
        paint method called to draw the UI elements
        """
        # get a painter object
        painter = QPainter(self)
        # draw tank outline as solid black line
        painter.setPen(QPen(Qt.black, 2, Qt.SolidLine))
        painter.drawRect(1, 1, self.width() - 2, self.height() - self.MARGIN_BOTTOM - 2)
        # draw paint color
        painter.setPen(QColor(0, 0, 0, 0))
        painter.setBrush(self.fill_color)
        painter.drawRect(2, 2 + int((1.0 - self.fill_level) * (self.height() - self.MARGIN_BOTTOM - 4)),
                         self.width() - 4,
                         int(self.fill_level * (self.height() - self.MARGIN_BOTTOM - 4)))
        # draw valve symobl
        painter.setPen(QPen(Qt.black, 2, Qt.SolidLine))
        painter.drawLine(self.width() // 2, self.height() - self.MARGIN_BOTTOM, self.width() // 2,
                         self.height() - self.MARGIN_BOTTOM + 5)
        painter.drawLine(self.width() // 2, self.height(), self.width() // 2,
                         self.height() - 5)
        painter.drawLine(self.width() // 2 - self.VALVE_WIDTH, self.height() - self.MARGIN_BOTTOM + 5,
                         self.width() // 2 + self.VALVE_WIDTH,
                         self.height() - 5)
        painter.drawLine(self.width() // 2 - self.VALVE_WIDTH, self.height() - 5, self.width() // 2 + self.VALVE_WIDTH,
                         self.height() - self.MARGIN_BOTTOM + 5)
        painter.drawLine(self.width() // 2 - self.VALVE_WIDTH, self.height() - self.MARGIN_BOTTOM + 5,
                         self.width() // 2 + self.VALVE_WIDTH,
                         self.height() - self.MARGIN_BOTTOM + 5)
        painter.drawLine(self.width() // 2 - self.VALVE_WIDTH, self.height() - 5, self.width() // 2 + self.VALVE_WIDTH,
                         self.height() - 5)
        # draw labels
        painter.drawText(
            QRect(0, self.height() - self.MARGIN_BOTTOM, self.width() // 2 - self.VALVE_WIDTH, self.MARGIN_BOTTOM),
            Qt.AlignCenter, "%u%%" % self.valve)
        painter.drawText(
            QRect(self.width() // 2 + self.VALVE_WIDTH, self.height() - self.MARGIN_BOTTOM,
                  self.width() // 2 - self.VALVE_WIDTH, self.MARGIN_BOTTOM),
            Qt.AlignCenter, "%.1f l/s" % self.flow)


class PaintTankWidget(QWidget):
    """
    Widget to hold a single paint tank, valve slider and command buttons
    """

    def __init__(self, station_name, tank_name, width, setLevel, fill_button=False, flush_button=False):
        super().__init__()
        self.station_name = station_name
        self.tank_name = tank_name
        self.setGeometry(0, 0, width, 400)
        self.setMinimumSize(width, 400)
        self.layout = QVBoxLayout()
        self.threadpool = QThreadPool()
        self.worker = TangoBackgroundWorker(self.station_name, self.tank_name)
        self.worker.level.done.connect(lambda level : setLevel(level, self.tank_name))
        self.worker.flow.done.connect(self.setFlow)
        self.worker.color.done.connect(self.setColor)
        self.worker.valve.done.connect(self.setValve)
        

        if fill_button:
            button = QPushButton('Fill', self)
            button.setToolTip('Fill up the tank with paint')
            button.clicked.connect(self.on_fill)
            self.layout.addWidget(button)

        # label for level
        self.label_level = QLabel("Level: --")
        self.label_level.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.label_level)

        # tank widget
        self.tank = TankWidget(width)
        self.layout.addWidget(self.tank, 5)

        # slider for the valve
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setFocusPolicy(Qt.NoFocus)
        self.slider.setGeometry(0, 0, width, 10)
        self.slider.setRange(0, 100)
        self.slider.setValue(0)  # valve closed
        self.slider.setSingleStep(10)
        self.slider.setTickInterval(20)
        self.timer_slider = None
        self.slider.valueChanged[int].connect(self.changedValue)
        self.layout.addWidget(self.slider)

        if flush_button:
            button = QPushButton('Flush', self)
            button.setToolTip('Flush the tank')
            button.clicked.connect(self.on_flush)
            self.layout.addWidget(button)

        self.setLayout(self.layout)

        # set the valve attribute to fully closed
        worker = TangoWriteAttributeWorker(self.station_name, self.tank_name, TANGO_ATTRIBUTE_VALVE, self.slider.value() / 100.0)
        self.threadpool.start(worker)
        self.worker.start()
        # update the UI element
        self.tank.setValve(0)

    def changedValue(self):
        """
        callback when the value of the valve slider has changed
        """
        if self.timer_slider is not None:
            self.killTimer(self.timer_slider)
        # start a time that fires after 200 ms
        self.timer_slider = self.startTimer(200)

    def timerEvent(self, event):
        """
        callback when the timer has fired
        """
        self.killTimer(self.timer_slider)
        self.timer_slider = None

        # set valve attribute
        worker = TangoWriteAttributeWorker(self.station_name, self.tank_name, TANGO_ATTRIBUTE_VALVE, self.slider.value() / 100.0)
        worker.signal.done.connect(self.setValve)
        self.threadpool.start(worker)

    def setLevel(self, level):
        """
        set the level of the paint tank, range: 0-1
        """
        self.tank.fill_level = level
        self.label_level.setText("Level: %.1f %%" % (level * 100))
        self.tank.update()

    def setValve(self, valve):
        """
        set the value of the valve label
        """
        if self.timer_slider is None and not self.slider.isSliderDown():
            # user is not currently changing the slider
            self.slider.setValue(int(valve*100))
            self.tank.setValve(valve*100)

    def setFlow(self, flow):
        """
        set the value of the flow label
        """
        self.tank.setFlow(flow)

    def setColor(self, color):
        """
        set the color of the paint
        """
        self.tank.setColor(color)

    def on_fill(self):
        """
        callback method for the "Fill" button
        """
        worker = TangoRunCommandWorker(self.station_name, self.tank_name, TANGO_COMMAND_FILL)
        self.threadpool.start(worker)

    def on_flush(self):
        """
        callback method for the "Flush" button
        """
        worker = TangoRunCommandWorker(self.station_name, self.tank_name, TANGO_COMMAND_FLUSH)
        self.threadpool.start(worker)


class ColorMixingStationWidget(QWidget):
    def __init__(self, station_name, setLevel):
        super().__init__()
        self.station_name = station_name

        self.setMinimumSize(900, 800)

        # Create a vertical layout
        vbox = QVBoxLayout()

        # Create a horizontal layout
        hbox = QHBoxLayout()

        self.tanks = {"cyan": PaintTankWidget(self.station_name, "cyan", width=150, setLevel=setLevel, fill_button=True),
                      "magenta": PaintTankWidget(self.station_name, "magenta", width=150, setLevel=setLevel, fill_button=True),
                      "yellow": PaintTankWidget(self.station_name, "yellow", width=150, setLevel=setLevel, fill_button=True),
                      "black": PaintTankWidget(self.station_name, "black", width=150, setLevel=setLevel, fill_button=True),
                      "white": PaintTankWidget(self.station_name, "white", width=150, setLevel=setLevel, fill_button=True),
                      "mixer": PaintTankWidget(self.station_name, "mixer", width=860, setLevel=setLevel, flush_button=True)}

        hbox.addWidget(self.tanks["cyan"])
        hbox.addWidget(self.tanks["magenta"])
        hbox.addWidget(self.tanks["yellow"])
        hbox.addWidget(self.tanks["black"])
        hbox.addWidget(self.tanks["white"])

        vbox.addLayout(hbox)

        vbox.addWidget(self.tanks["mixer"])

        self.layout = vbox

        self.setLayout(self.layout)


class ColorMixingStationOverviewWidget(QWidget):
    def __init__(self, station_name, wrt_alarm):
        super().__init__()
        self.station_name = station_name
        self.wrt_alarm = wrt_alarm

        # self.setMinimumSize(300, 250)

        self.layout = QVBoxLayout()

        # add station label to station overview
        self.label_station_name = QLabel(f'Station {self.station_name[-1]}')
        self.label_station_name.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.label_station_name)

        # link station overview with its detailled one
        self.station = ColorMixingStationWidget(self.station_name, self.setLevel)

        # add 6 tank level indicator with tank names
        level_vbox = QVBoxLayout()

        self.tank_labels = {tank_name : (QLabel(tank_name), QLabel('--')) for tank_name in self.station.tanks.keys()}
        for tank_label in self.tank_labels.values():
            level_hbox = QHBoxLayout()
            tank_label[0].setAlignment(Qt.AlignCenter)
            tank_label[1].setAlignment(Qt.AlignCenter)
            level_hbox.addWidget(tank_label[0])
            level_hbox.addWidget(tank_label[1])
            # add tank line to level_vbox
            level_vbox.addLayout(level_hbox)

        self.layout.addLayout(level_vbox)
        
        self.setLayout(self.layout)

    def setLevel(self, level, tank_name):
        """
        set the level of the paint tank, range: 0-1
        """
        self.check_alarm_generation(self.station.tanks[tank_name].tank.fill_level, level, tank_name)
        self.station.tanks[tank_name].tank.fill_level = level
        self.station.tanks[tank_name].label_level.setText("Level: %.1f %%" % (level * 100))
        self.tank_labels[tank_name][1].setText('%.1f %%' % (level*100))

        self.tank_labels[tank_name][1].setStyleSheet("background-color: "+self.get_label_color(tank_name, level))
        self.station.tanks[tank_name].tank.update()  

    def check_alarm_generation(self, previous_level, level, tank_name):
        if tank_name == 'mixer':
            if previous_level<0.8 and level>=0.8 or previous_level<0.9 and level>=0.9:
                self.wrt_alarm(f'{self.station_name}/{tank_name} : {int(level*10)/10:.0%} full')
        else:
            if previous_level>0.2 and level<=0.2 or previous_level>0.1 and level<=0.1:
                self.wrt_alarm(f'{self.station_name}/{tank_name} : {int(level*10)/10:.0%} remaining')

    def get_label_color(self, tank_name, level):
        """
        get the color to raise concern on soon empty or full tanks
        """
        if tank_name == 'mixer':
            # if level>=0.9:
            #     return f'rgba(255, 0, 0, {(level-0.8)*5})' # red
            # elif level>=0.8:
            #     return f'rgba(255, 165, 0, {(level-0.8)*5})' # orange
            if level>=0.8:
                return f'rgba(255, {int(255 * (1 - 5*(level-0.8)))}, 0, {0.4+3*(level-0.8)})'
            else:
                return 'none'
        else:
            # if level=<0.1:
            #     return f'rgba(255, 0, 0, {1-5*level})' # red
            # elif level=<0.2:
            #     return f'rgba(255, 165, 0, {1-5*level})' # orange
            if level<=0.2:
                return f'rgba(255, {int(255 * 5 * level)}, 0, {1-3*level})'
            else:
                return 'none'


class PlantOverviewWidget(QWidget):
    def __init__(self, wrt_alarm):
        super().__init__()
        # self.setMinimumSize(900, 500)

        self.layout = QVBoxLayout()

        self.station_overviews = [ColorMixingStationOverviewWidget(f'station{i}', wrt_alarm) for i in range (1,7)]

        for i in range(3):
            hbox = QHBoxLayout()
            hbox.addWidget(self.station_overviews[2*i])
            hbox.addWidget(self.station_overviews[2*i+1])

            self.layout.addLayout(hbox)

            self.setLayout(self.layout)


class Gui(QMainWindow):
    """
    main UI window
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Color Mixing Plant Simulator - EPFL CS-487")
        # self.setMinimumSize(900, 1300)

        self.window = QWidget()
        self.setCentralWidget(self.window)

        # Create a layouts
        self.layout = QVBoxLayout()
        self.up = QHBoxLayout()
        self.down = QVBoxLayout()
        self.upleft_panel = QVBoxLayout()

        # Create upleft/plant overview panel
        plant_overview_label = QLabel('Plant Overview')
        plant_overview_label.setAlignment(Qt.AlignCenter)
        self.upleft_panel.addWidget(plant_overview_label)
        self.plant_overview = PlantOverviewWidget(self.write_new_alarm)
        self.upleft_panel.addWidget(self.plant_overview)
        
        # add inspect buttons
        button_layout = QHBoxLayout()
        # for i in range(1,7):
        #     button = QPushButton(f'Inspect {i}', self)
        #     button.setToolTip(f'Inspect station {i}')
        #     button.clicked.connect(lambda: self.on_inspect(i-1))
        #     button_layout.addWidget(button)

        button1 = QPushButton(f'Inspect {1}', self)
        button1.clicked.connect(lambda x: self.on_inspect(0))
        button1.setToolTip(f'Inspect station {1}')
        button2 = QPushButton(f'Inspect {2}', self)
        button2.clicked.connect(lambda x: self.on_inspect(1))
        button2.setToolTip(f'Inspect station {2}')
        button3 = QPushButton(f'Inspect {3}', self)
        button3.clicked.connect(lambda x: self.on_inspect(2))
        button3.setToolTip(f'Inspect station {3}')
        button4 = QPushButton(f'Inspect {4}', self)
        button4.clicked.connect(lambda x: self.on_inspect(3))
        button4.setToolTip(f'Inspect station {4}')
        button5 = QPushButton(f'Inspect {5}', self)
        button5.clicked.connect(lambda x: self.on_inspect(4))
        button5.setToolTip(f'Inspect station {5}')
        button6 = QPushButton(f'Inspect {6}', self)
        button6.clicked.connect(lambda x: self.on_inspect(5))
        button6.setToolTip(f'Inspect station {6}')

        button_layout.addWidget(button1)
        button_layout.addWidget(button2)
        button_layout.addWidget(button3)
        button_layout.addWidget(button4)
        button_layout.addWidget(button5)
        button_layout.addWidget(button6)
        

        self.upleft_panel.addLayout(button_layout)
        self.up.addLayout(self.upleft_panel)

        # upright/detailled view panel
        self.upright_panel = QVBoxLayout()
        self.detailled_view_label = QLabel('Detailled view : Station 1')
        self.detailled_view_label.setAlignment(Qt.AlignCenter)
        self.upright_panel.addWidget(self.detailled_view_label)
        self.detailled_view = QStackedLayout()
        for station_overview in self.plant_overview.station_overviews:
            self.detailled_view.addWidget(station_overview.station)
        self.detailled_view.setCurrentIndex(0)
        self.upright_panel.addLayout(self.detailled_view)

        self.up.addLayout(self.upright_panel)
        self.layout.addLayout(self.up)

        # down/alarms panel
        self.down.addWidget(QLabel('Alarms'))
        self.alarm_labels = [QLabel('') for _ in range(10)]
        for alarm_label in self.alarm_labels:
            self.down.addWidget(alarm_label)
        self.layout.addLayout(self.down)

        self.window.setLayout(self.layout)

    def on_inspect(self, station_i):
        self.detailled_view_label.setText(f'Detailled view : Station {station_i+1}')
        self.detailled_view.setCurrentIndex(station_i)

    def write_new_alarm(self, alarm_text):
        now = time.localtime()
        timestamp = f'{now.tm_mday:02}/{now.tm_mon:02}/{now.tm_year} {now.tm_hour:02}:{now.tm_min:02}:{now.tm_sec:02}'
        
        for i in reversed(range(1,len(self.alarm_labels))):
            self.alarm_labels[i].setText(self.alarm_labels[i-1].text())

        self.alarm_labels[0].setText(timestamp + ' : ' + alarm_text)



class WorkerSignal(QObject):
    """
    Implementation of a QT signal
    """
    done = pyqtSignal(object)


class TangoWriteAttributeWorker(QRunnable):
    """
    Worker class to write to a Tango attribute in the background.
    This is used to avoid blocking the main UI thread.
    """

    def __init__(self, station_name, device, attribute, value):
        super().__init__()
        self.signal = WorkerSignal()
        self.path = "%s/%s/%s/%s" % (TANGO_NAME_PREFIX, station_name, device, attribute)
        self.value = value

    @pyqtSlot()
    def run(self):
        """
        main method of the worker
        """
        print("setDeviceAttribute: %s = %f" % (self.path, self.value))
        attr = AttributeProxy(self.path)
        try:
            # write attribute
            attr.write(self.value)
            # read back attribute
            data = attr.read()
            # send callback signal to UI
            self.signal.done.emit(data.value)
        except Exception as e:
            print("Failed to write to the Attribute: %s. Is the Device Server running?" % self.path)


class TangoRunCommandWorker(QRunnable):
    """
    Worker class to call a Tango command in the background.
    This is used to avoid blocking the main UI thread.
    """

    def __init__(self, station_name, device, command, *args):
        """
        creates a new instance for the given device instance and command
        :param device: device name
        :param command: name of the command
        :param args: command arguments
        """
        super().__init__()
        self.signal = WorkerSignal()
        self.device = "%s/%s/%s" % (TANGO_NAME_PREFIX, station_name, device)
        self.command = command
        self.args = args

    @pyqtSlot()
    def run(self):
        """
        main method of the worker
        """
        print("device: %s command: %s args: %s" % (self.device, self.command, self.args))
        try:
            device = DeviceProxy(self.device)
            # get device server method
            func = getattr(device, self.command)
            # call command
            result = func(*self.args)
            # send callback signal to UI
            self.signal.done.emit(result)
        except Exception as e:
            print("Error calling device server command: device: %s command: %s" % (self.device, self.command))


class TangoBackgroundWorker(QThread):
    """
    This worker runs in the background and polls certain Tango device attributes (e.g. level, flow, color).
    It will signal to the UI when new data is available.
    """

    def __init__(self, station_name, tank_name, interval=0.5):
        """
        creates a new instance
        :param name: device name
        :param interval: polling interval in seconds
        """
        super().__init__()
        self.station_name = station_name
        self.tank_name = tank_name
        self.interval = interval
        self.level = WorkerSignal()
        self.flow = WorkerSignal()
        self.color = WorkerSignal()
        self.valve = WorkerSignal()

    def run(self):
        """
        main method of the worker
        """
        print("Starting TangoBackgroundWorker for '%s'/'%s' tank" % (self.station_name,self.tank_name))
        # define attributes
        try:
            level = AttributeProxy("%s/%s/%s/%s" % (TANGO_NAME_PREFIX, self.station_name, self.tank_name, TANGO_ATTRIBUTE_LEVEL))
            flow = AttributeProxy("%s/%s/%s/%s" % (TANGO_NAME_PREFIX, self.station_name, self.tank_name, TANGO_ATTRIBUTE_FLOW))
            color = AttributeProxy("%s/%s/%s/%s" % (TANGO_NAME_PREFIX, self.station_name, self.tank_name, TANGO_ATTRIBUTE_COLOR))
            valve = AttributeProxy("%s/%s/%s/%s" % (TANGO_NAME_PREFIX, self.station_name, self.tank_name, TANGO_ATTRIBUTE_VALVE))
        except Exception as e:
            print("Error creating AttributeProxy for %s" % self.tank_name)
            return

        while True:
            try:
                # read attributes
                data_color = color.read()
                data_level = level.read()
                data_flow = flow.read()
                data_valve = valve.read()
                # signal to UI
                self.color.done.emit(data_color.value)
                self.level.done.emit(data_level.value)
                self.flow.done.emit(data_flow.value)
                self.valve.done.emit(data_valve.value)
            except Exception as e:
                print("Error reading from the device: %s" % e)

            # wait for next round
            time.sleep(self.interval)


if __name__ == '__main__':
    # register signal handler for CTRL-C events
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # init the QT application and the main window
    app = QApplication(sys.argv)
    # ui = ColorMixingPlantWindow()

    ui = Gui()
    # show the UI
    ui.show()
    # start the QT application (blocking until UI exits)
    app.exec_()
