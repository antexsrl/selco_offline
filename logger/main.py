import logging
import sys

from configuration import Configuration
from PySide2.QtWidgets import QApplication, QWidget, QPushButton, QLabel, QLineEdit,QFormLayout, QSystemTrayIcon, QMenu,QDialogButtonBox
from PySide2.QtGui import QIcon, QIntValidator
from PySide2.QtCore import QTimer
from selco import Selco

POLL_MS = 2000  # the log is read every 2 seconds, Odoo is synced every config.interval

class MainWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Selco Logger App")
        self.setGeometry(100, 100, 300, 200)

        # Create label and button widgets
        self.tbfile = QLineEdit()
        self.tbserver = QLineEdit()
        self.tbport = QLineEdit()
        v0 = QIntValidator(0, 65536, self)
        self.tbport = QLineEdit()
        self.tbport.setValidator(v0) # TODO limitare intercettando stato

        self.tbdbname = QLineEdit()
        self.tbdbuser = QLineEdit()
        self.tbdbpassword = QLineEdit()
        self.tbdbpassword.setEchoMode(QLineEdit.Password)

        self.tbwccode = QLineEdit()
        self.tbinterval = QLineEdit()
        v1 = QIntValidator(30,180,self)
        self.tbinterval.setValidator(v1) # TODO limitare intercettando stato

        self.tbfilebkp = QLineEdit()

        buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttonBox.accepted.connect(self.on_ok_triggered)
        buttonBox.rejected.connect(self.on_cancel_triggered)

        layout = QFormLayout()
        layout.addRow(QLabel('Event file:'),self.tbfile)
        layout.addRow(QLabel('Backup file:'),self.tbfilebkp)
        layout.addRow(QLabel('Server:'),self.tbserver)
        layout.addRow(QLabel('Port:'),self.tbport)
        layout.addRow(QLabel('Database name:'),self.tbdbname)
        layout.addRow(QLabel('User:'),self.tbdbuser)
        layout.addRow(QLabel('Password:'),self.tbdbpassword)
        layout.addRow(QLabel('Workcenter code:'),self.tbwccode)
        layout.addRow(QLabel('Update interval (secs):'),self.tbinterval)

        layout.addWidget(buttonBox)



        # Set the window's layout
        self.setLayout(layout)

        # Create system tray icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon('crono000.svg'))
        self.tray_icon.setToolTip('Selco Logger')

        # Create system tray menu
        self.tray_menu = QMenu(self)

        # Create system tray menu actions
        self.pause_action = self.tray_menu.addAction('Pause')
        self.restart_action = self.tray_menu.addAction('Restart')
        self.show_config = self.tray_menu.addAction('Show Configuration')
        self.quit_action = self.tray_menu.addAction('Quit')

        # Connect system tray menu actions to slots
        self.pause_action.triggered.connect(self.on_pause_triggered)
        self.restart_action.triggered.connect(self.on_restart_triggered)
        self.show_config.triggered.connect(self.on_show_config_triggered)
        self.quit_action.triggered.connect(self.on_quit_triggered)

        # Set the system tray menu
        self.tray_icon.setContextMenu(self.tray_menu)

        # Show the system tray icon
        self.tray_icon.show()

        # Read the log and send what is pending
        selco_obj.update()
        try:
            selco_obj.sync_odoo()
        except Exception:
            logging.exception('Odoo sync failed')

        # Create timer to read the new lines of the log
        self.timer_poll = QTimer()
        self.timer_poll.setInterval(POLL_MS)
        self.timer_poll.timeout.connect(self.poll)
        self.timer_poll.start()

        # Create timer to execute upload_data function
        self.timer_upload_data = QTimer()
        self.timer_upload_data_ms = config.interval * 1000
        self.timer_upload_data.setInterval(self.timer_upload_data_ms)
        self.timer_upload_data.timeout.connect(self.upload_data)
        self.timer_upload_data.start()

        # Create timer to update system tray icon every second

        self.timer_icon = QTimer()
        self.timer_icon.setInterval(1000)  # 1 second
        self.timer_icon.timeout.connect(self.update_icon)
        self.timer_icon.start()

    # def on_button_clicked(self):
    #     self.label.setText("Button clicked!")

    def on_ok_triggered(self):
        config.file = self.tbfile.text()
        config.server = self.tbserver.text()
        config.port = int(self.tbport.text())
        config.db_name = self.tbdbname.text()
        config.user = self.tbdbuser.text()
        config.password = self.tbdbpassword.text()
        config.workcenter_code = self.tbwccode.text()
        config.interval = int(self.tbinterval.text())
        config.filebkp = self.tbfilebkp.text()
        config.save()
        self.hide()

    def on_cancel_triggered(self):
        self.hide()

    def on_pause_triggered(self):
        self.timer_poll.stop()
        self.timer_upload_data.stop()

    def on_restart_triggered(self):
        self.timer_poll.start()
        self.timer_upload_data.start()

    def on_show_config_triggered(self):

        self.tbfile.setText(config.file)
        self.tbserver.setText(config.server)
        self.tbport.setText(f'{config.port}')
        self.tbdbname.setText(config.db_name)
        self.tbdbuser.setText(config.user)
        self.tbdbpassword.setText(config.password)
        self.tbwccode.setText(config.workcenter_code)
        self.tbinterval.setText(f'{config.interval}')
        self.tbfilebkp.setText(config.filebkp)
        self.show()

    def on_quit_triggered(self):
        QApplication.quit()

    def poll(self):
        # label requests are sent at once, the rest waits for upload_data
        selco_obj.update()

    def upload_data(self):
        self.timer_icon.stop()
        self.timer_upload_data.stop()
        try:
            selco_obj.sync_odoo()
        except Exception:
            logging.exception('Odoo sync failed')
        self.timer_icon.start()
        self.timer_upload_data.start()

    def update_icon(self):
        # Get the elapsed time in seconds
        remaining_time = self.timer_upload_data.remainingTime() / 1000

        # Set the system tray icon based on the elapsed time
        coeff_timer_upload_data_seconds = self.timer_upload_data_ms / 1000 /8
        if remaining_time >= coeff_timer_upload_data_seconds * 7  and remaining_time <= coeff_timer_upload_data_seconds * 8:
            self.tray_icon.setIcon(QIcon('crono000.svg'))

        elif remaining_time >= coeff_timer_upload_data_seconds * 6  and remaining_time < coeff_timer_upload_data_seconds * 7 :
            self.tray_icon.setIcon(QIcon('crono045.svg'))

        elif remaining_time >= coeff_timer_upload_data_seconds * 5  and remaining_time < coeff_timer_upload_data_seconds * 6 :
            self.tray_icon.setIcon(QIcon('crono090.svg'))

        elif remaining_time >= coeff_timer_upload_data_seconds * 4  and remaining_time < coeff_timer_upload_data_seconds * 5 :
            self.tray_icon.setIcon(QIcon('crono135.svg'))

        elif remaining_time >= coeff_timer_upload_data_seconds * 3  and remaining_time < coeff_timer_upload_data_seconds * 4 :
            self.tray_icon.setIcon(QIcon('crono180.svg'))

        elif remaining_time >= coeff_timer_upload_data_seconds * 2  and remaining_time < coeff_timer_upload_data_seconds * 3 :
            self.tray_icon.setIcon(QIcon('crono225.svg'))

        elif remaining_time >= coeff_timer_upload_data_seconds * 1  and remaining_time < coeff_timer_upload_data_seconds * 2 :
            self.tray_icon.setIcon(QIcon('crono270.svg'))
        elif remaining_time >= coeff_timer_upload_data_seconds * 0.1  and remaining_time < coeff_timer_upload_data_seconds * 1 :
            self.tray_icon.setIcon(QIcon('crono315.svg'))
        else:
            self.tray_icon.setIcon(QIcon('crono360.svg'))


if __name__ == '__main__':
    app = QApplication(sys.argv)
    config = Configuration()
    selco_obj = Selco(config)
    window = MainWindow()
    sys.exit(app.exec_())

# TODO: errore se non trova il file log