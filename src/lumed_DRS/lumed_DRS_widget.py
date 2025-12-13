"""User Interface (UI) for the control of ocean optics HL_2000_HP_232R halogen lamp with the HL2000() class 
imported from the HL_2000_HP_232R_control module"""

# Tutorial on worker threads. https://www.youtube.com/watch?v=M2vg6Ky6M1U https://www.youtube.com/watch?v=G7ffF0U36b0&t=58s https://www.linkedin.com/pulse/enhancing-pyqt5-applications-using-worker-classes-qthread-garcia-a3ylc/

import logging
import sys
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from time import strftime
import datetime as dt
import time as tt
import joblib
import tomli
import glob
import os
from scipy.signal import find_peaks, savgol_filter
import matplotlib.pyplot as plt

import pyqt5_fugueicons as fugue
from PyQt5.QtCore import QTimer, pyqtSignal, pyqtSlot
from PyQt5 import QtWidgets, QtGui
from PyQt5.QtWidgets import QDialog, QApplication, QLabel, QWidget, QMainWindow,QCheckBox, QVBoxLayout, QMessageBox
from PyQt5.QtCore import Qt, QUrl, QThreadPool 
from PyQt5.QtGui import QDoubleValidator, QIntValidator, QCloseEvent

import orpl as op
from maya_control import MayaSpectrometer, SpectroInfo # Maya spectrometer control functions
from HL_2000_HP_232R_control import HL2000Lamp, LampInfo #Lamp control functions.
from ui.Lumed_DRS_ui import Ui_Form
from display_widget import DataDisplayWidget
from worker import WorkerThread, LoopWorkerThread, CustomThread
from arduino import Arduino
import lumed_algos as la
try:
    import oras.backend.external_trigger as ext
except ModuleNotFoundError:
    print("ORAS package not found")

logger = logging.getLogger(__name__)

LOGS_DIR = Path.home() / "logs/lumed_DRS"
LOG_PATH = LOGS_DIR / f"{strftime('%Y_%m_%d_%H_%M_%S')}.log"
print(Path.home())
LAMP_STATE = {0: "Idle", 1: "ON", 2: "Not connected"}
STATE_COLORS = {
    0: "QLabel { background-color : blue; }",
    1: "QLabel { background-color : red; }",
    2: "QLabel { background-color : grey; }",
}

LOG_FORMAT = (
    "%(asctime)s - %(levelname)s"
    "(%(filename)s:%(funcName)s)"
    "(%(filename)s:%(lineno)d) - "
    "%(message)s"
)

def configure_logger():
    """Configures the logger if lumed_DRS_widget is launched as a module"""

    if not LOGS_DIR.parent.exists():
        LOGS_DIR.parent.mkdir()
    if not LOGS_DIR.exists():
        LOGS_DIR.mkdir()

    formatter = logging.Formatter(LOG_FORMAT)

    terminal_handler = logging.StreamHandler()
    terminal_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(LOG_PATH)
    file_handler.setFormatter(formatter)

    logger.addHandler(terminal_handler)
    logger.addHandler(file_handler)
    #logger.setLevel(logging.DEBUG)
    # Prevent messages from being propagated to the root logger (and printed again)
    logger.propagate = False

class LumedDRSWidget(QMainWindow, Ui_Form):
    """User Interface for HL_2000_HP_232R white light lamp control.
    Subclass HL2000Widget to customize the Ui_HL2000Widget widget"""

    def __init__(self, parent=None):
        super().__init__()
        self.setupUi(self)

        # logger
        self.setWindowTitle("DRS OVERTAKE, by Najib Nassiri")
        logger.info("Widget intialization")
        self.lamp: HL2000Lamp = HL2000Lamp()
        self.lamp_info: LampInfo = self.lamp.info
        self.last_enabled_state: bool = False
        self.is_spectro_connected: bool = False
        self.is_oras_linked: bool = False
        self.is_measuring: bool = False
        self.mayaspectro: MayaSpectrometer = MayaSpectrometer()
        self.spectro_info: SpectroInfo = self.mayaspectro.info
        self.xaxis_file: str|None = None
        self.yaxis_file: str|None = None
        self.xaxis_data: dict|None = None
        self.yaxis_data: dict|None = None
        self.xaxis_raman =  None
        self.irf_raman = None
        self.spectralon_file: str|None = None
        self.save_dir:  str|None = None
        self.acqname: str|None = None
        self.acqnames_list: list = []
        self.comments_list: list = []
        self.saved_data_list: list = []
        self.main_oras_dir: str = "C:/Users/nerfi/oras/" #"/home/lumed/oras/" #
        #Setup display
        self.display_raman = DataDisplayWidget()
        self.verticalLayout_raman = QtWidgets.QVBoxLayout()
        self.verticalLayout_raman.addWidget(self.display_raman.canvas)
        self.verticalLayout_raman.addWidget(self.display_raman.toolbar)
        self.RamanTab.setLayout(self.verticalLayout_raman)
        self.display_DRS = DataDisplayWidget()
        self.verticalLayout_DRS = QtWidgets.QVBoxLayout()
        self.verticalLayout_DRS.addWidget(self.display_DRS.canvas)
        self.verticalLayout_DRS.addWidget(self.display_DRS.toolbar)
        self.DRSTab.setLayout(self.verticalLayout_DRS)
        #Thread management
        self.threadpool = QThreadPool()
        logger.info(f"Widget initialization complete. Multithreading with max {self.threadpool.maxThreadCount()} threads.")
        # Setup ui 
        self.setup_default_ui()
        self.connect_ui_signals()
        self.set_oras_status_loopworker() # oras status is continuously being probed by a dedicated thread
        #self.setup_update_timer()
        self.setup_pulse_timer()
        self.update_ui()
        #Tylenol peaks for xaxis
        self.tylenol_peaks = np.array([390.9,  651.6,  797.2,  857.9, 1168.5, 1236.8,
                          1278.5, 1323.9, 1371.5, 1561.6, 1609, 1648.4])

    def setup_default_ui(self):
        self.pushbtnFindLamp.setIcon(fugue.icon("magnifier-left"))
        self.pushbtnFindSpectro.setIcon(fugue.icon("magnifier-left"))
        self.checkBoxSave.setChecked(True)
        self.checkBoxSpectralon.setCheckable(False) # Make the normalization check unavailable until a spectralon file is selected 
        #self.spinboxShutterPosition.setMaximum(400)  # max position of lamp shutter
    
    def connect_ui_signals(self):
        self.pushbtnFindLamp.clicked.connect(self.find_lamp_worker) #find_lamp
        self.pushbtnConnectLamp.clicked.connect(self.connect_lamp_worker) #self.connect_lamp
        self.pushbtnDisconnectLamp.clicked.connect(self.disconnect_lamp_worker)
        self.pushbtnFindSpectro.clicked.connect(self.find_spectro_worker)
        self.pushbtnConnectSpectro.clicked.connect(self.connect_mayaspectro_worker)
        self.pushbtnDisconnectSpectro.clicked.connect(self.disconnect_mayaspectro_worker)
        self.toolButtonSpectralonFileSelect.clicked.connect(self.select_spectralon) 
        self.toolButtonXaxisFileSelect.clicked.connect(self.select_xaxis)
        self.toolButtonYaxisFileSelect.clicked.connect(self.select_yaxis)
        self.toolButtonSaveDir.clicked.connect(self.select_save_folder_dir)
        self.pushButtonMeasureDRS.clicked.connect(self.button_DRS_acquisition)
        self.pushButtonMeasureRaman.clicked.connect(self.button_raman_acquisition)
        self.pushButtonMeasureRamanDRS.clicked.connect(self.display_test_data) # originaly self.button_raman_DRS_acquisition
        self.checkBoxSave.stateChanged.connect(self.update_ui)
        self.comboBoxAcqName.currentTextChanged.connect(self.display_saved_data)  #lambda _: self.display_saved_data()
        self.comboBoxRamanProfile.currentTextChanged.connect(self.set_oras_profile) # automatically sets the new oras profile for raman acquisition when combobox selection is changed

    def display_test_data(self):
        x = np.arange(100)
        mu = 0
        sigma = 0.5
        n = np.random.randint(1,10)
        print('n:',n)
        y = np.zeros((100,n))
        for i in range(n):
            y[:,i] = np.random.normal(mu, sigma, 100) + i
        print('y shape:', y.shape)
        self.display_raman.update_plot(x, y)
        self.display_DRS.update_plot(x, -y) 

    def find_lamp(self):
        try:
            lamps = self.lamp.find_lamp_device()
            logger.info("Found lamps : %s", lamps)
            self.comboBoxAvailableLamp.clear()
            for lamp in lamps:
                self.comboBoxAvailableLamp.addItem(lamp)
            self.pushbtnFindLamp.setEnabled(True)
            self.pushbtnFindLamp.setIcon(fugue.icon("magnifier-left"))
        except Exception as e:
            logger.error(e, exc_info=True)
        
    def find_lamp_worker(self):
        logger.info("Looking for connected lamps")
        self.pushbtnFindLamp.setEnabled(False)
        self.pushbtnFindLamp.setIcon(fugue.icon("hourglass"))
        self.repaint()
        try:   
            worker = WorkerThread(self.find_lamp)
            self.threadpool.start(worker)
            worker.signals.finished.connect(self.update_ui)
        except Exception as e:
            logger.error(e, exc_info=True)
    
    def find_spectro(self):
        try:
            spectros = self.mayaspectro.find_spectros()
            logger.info("Found spectrometers : %s", spectros)
            self.comboBoxAvailableSpectro.clear()
            for spectro in spectros:
                self.comboBoxAvailableSpectro.addItem(
                    f"{spectro.model}:{spectro.serial_number}"
                )
            self.pushbtnFindSpectro.setEnabled(True)
            self.pushbtnFindSpectro.setIcon(fugue.icon("magnifier-left"))
        except Exception as e:
            logger.error(e, exc_info=True)

    def find_spectro_worker(self):
        logger.info("Looking for connected spectros") 
        self.pushbtnFindSpectro.setEnabled(False) 
        self.pushbtnFindSpectro.setIcon(fugue.icon("hourglass"))
        self.repaint()
        try:   
            worker = WorkerThread(self.find_spectro)
            self.threadpool.start(worker)
            worker.signals.finished.connect(self.update_ui)
        except Exception as e:
            logger.error(e, exc_info=True)

    def connect_lamp(self):
        self.lamp.comport = self.comboBoxAvailableLamp.currentText()
        print("self.lamp.comport:", self.lamp.comport)
        self.lamp.connect()
        logger.info("Connected lamp : %s", self.lamp.comport)
        self.set_initial_lamp_configurations()

    def connect_lamp_worker(self):
        logger.info("Connecting lamp")
        self.pushbtnConnectLamp.setEnabled(False)
        try:   
            worker = WorkerThread(self.connect_lamp)
            self.threadpool.start(worker)
            worker.signals.finished.connect(self.update_ui)
        except Exception as e:
            logger.info("Lamp not available")
            logger.error(e, exc_info=True)

    def disconnect_lamp(self):
        try:
            self.set_initial_lamp_configurations()
            self.lamp.disconnect()
            logger.info("Disconnected lamp")
        except Exception as e:
            logger.error(e, exc_info=True)

    def disconnect_lamp_worker(self):
        logger.info("Disonnecting lamp")
        self.pushbtnDisconnectLamp.setEnabled(False)
        try:   
            worker = WorkerThread(self.disconnect_lamp)
            self.threadpool.start(worker)
            worker.signals.finished.connect(self.update_ui)
        except Exception as e:
            logger.error(e, exc_info=True)
    
    def connect_mayaspectro(self):
        if self.mayaspectro.is_spectro_available():
            try:
                combobox_spectro_name = self.comboBoxAvailableSpectro.currentText()
                devices = self.mayaspectro.find_spectros()
                
                for device in devices:
                    if device.serial_number == combobox_spectro_name.split(":")[-1]:
                        self.mayaspectro.device = device
                self.mayaspectro.connect()
                
                #Set exposure time limits on line edits
                min_exp, max_exp = self.mayaspectro.get_exposure_time_lims()
                print(min_exp, max_exp)
                exp_validator = QDoubleValidator()  # min exposure, max exposure, 3 for number of decimal places
                exp_validator.setRange(min_exp, max_exp,2)
                exp_validator.setNotation(QDoubleValidator.StandardNotation)
                self.lineEditMinAutoExposure.setValidator(exp_validator)
                self.lineEditMaxAutoExposure.setValidator(exp_validator)
                self.lineEditMinExposure.setValidator(exp_validator)
                self.lineEditMaxExposure.setValidator(exp_validator)

                #Set max count on line edit
                max_count = self.mayaspectro.get_max_intensity()
                print("max count:", self.mayaspectro.get_max_intensity())
                count_validator = QIntValidator()
                count_validator.setRange(0, int(max_count))
                self.lineEditMaxCount.setValidator(count_validator)
                self.lineEditMaxCount.setPlaceholderText(f"0-{int(max_count)}")
                self.is_spectro_connected = True
            except Exception as e:
                logger.error(e, exc_info=True)
        else:
            logger.info("Maya spectrometer not available")
            print("Maya spectrometer not available")

    def connect_mayaspectro_worker(self):
        logger.info("Connecting spectrometer")
        self.pushbtnConnectSpectro.setEnabled(False)
        try:   
            worker = WorkerThread(self.connect_mayaspectro)
            self.threadpool.start(worker)
            worker.signals.finished.connect(self.update_ui)
        except Exception as e:
            logger.error(e, exc_info=True)

    def disconnect_mayaspectro(self):
        try:
            self.mayaspectro.disconnect()
            logger.info("Disconnected spectrometer")
        except:
            if self.mayaspectro.is_spectro_available() == False:
                print("Maya spectrometer not available")
                logger.info("Maya spectrometer not available")
            raise Exception("No spectrometer available")
        
    def disconnect_mayaspectro_worker(self):
        logger.info("Disconnecting spectrometer")
        self.pushbtnDisconnectSpectro.setEnabled(False)
        try:   
            worker = WorkerThread(self.disconnect_mayaspectro)
            self.threadpool.start(worker)
            worker.signals.finished.connect(self.update_ui)
        except Exception as e:
            logger.error(e, exc_info=True)

    #Calibration files selection
    def select_xaxis(self):
        try:
            self.xaxis_file = QtWidgets.QFileDialog.getOpenFileName(self, caption = "Select a file to set xaxis", filter=("Text files (*.joblib)"))[0] #CHANGE FILTER PARAMETER
            print('self.xaxis_files: ', self.xaxis_file, 'type: ', type(self.xaxis_file))
            with open(self.xaxis_file, 'rb') as f:
                self.xaxis_data = joblib.load(f)
                print('data_file:', self.xaxis_data)
                url = QUrl.fromLocalFile(self.xaxis_file)
            print('url: ', url ) 
            self.lineEditXaxisFile.setText(url.fileName()) # Display the selected xaxis file
            logger.info("xaxis file to be used: %s", url.fileName())
            raw_spectra = self.xaxis_data['accumulations'] # 'raman_data'
            bkg = self.xaxis_data['background']  #'raman_background'
            print("raw_spectrum shape:", raw_spectra.shape)
            print("bkg shape:", bkg.shape)
            raw_mean = np.mean(raw_spectra-bkg, axis=0)
            raman_tyl, baseline_tyl = op.baseline_removal.bubblefill(raw_mean, min_bubble_widths=40) # raman spectra, baseline
            raman_snv = savgol_filter(la.snv(raman_tyl) - np.min(la.snv(raman_tyl)), 11, 3) # snv + shift to have signal start at 0 + smoothing
            h = 1.5
            peaks, props = find_peaks(raman_snv, prominence=h)
            while peaks.size != self.tylenol_peaks.size:
                if peaks.size < self.tylenol_peaks.size:
                    h-=0.01
                    peaks, props = find_peaks(raman_snv, prominence=h)
                else:
                    h+=0.01
                    peaks, props = find_peaks(raman_snv, prominence=h)
            self.xaxis_raman = np.polyval(np.polyfit(peaks, self.tylenol_peaks, 2), np.arange(raman_snv.size))
            self.display_raman.update_plot(self.xaxis_raman, raman_tyl.reshape(raman_tyl.shape[0],1))
            return self.xaxis_raman
        except Exception as e: 
            if type(self.xaxis_file) is str and (len(self.xaxis_file) == 0): # If True, file selection was canceled
                logger.info("Canceled: No Raman xaxis file was selected")
            logger.error(e, exc_info=True)
            
    def select_yaxis(self):
        try:
            if self.xaxis_raman is None:
                logger.info("Canceled: No Raman xaxis file was selected before selecting yaxis file. Exception error will be raised")
                raise Exception("No xaxis file selected. Select a xaxis file first")
            self.yaxis_file = QtWidgets.QFileDialog.getOpenFileName(self, caption = "Select a file to set yaxis", filter=("Text files (*.joblib)"))[0]
            print('self.yaxis_files: ', self.yaxis_file, 'type: ', type(self.yaxis_file))
            with open(self.yaxis_file, 'rb') as f:
                self.yaxis_data = joblib.load(f)
                print('data_file:', self.yaxis_data)
            url = QUrl.fromLocalFile(self.yaxis_file)
            print('url: ', url )
            self.lineEditYaxisFile.setText(url.fileName()) # Display the selected yaxis file
            logger.info("Selected yaxis file: %s", url.fileName())
            raw_spectrum = self.yaxis_data['accumulations'] #'raman_data'
            print("raw_spectrum shape:", raw_spectrum.shape)
            bkg = self.yaxis_data['background']  #'raman_background'
            print("bkg shape:", bkg.shape)
            raw_mean = np.mean(raw_spectrum - bkg, axis=0) 
            self.irf_raman = la.get_correction_curve(self.xaxis_raman, raw_mean) # get instrument response function (IRF) from xaxis (cm-1) and measured nist (raw_mean)
            self.display_DRS.update_plot(self.xaxis_raman, self.irf_raman.reshape(self.irf_raman.shape[0],1))
            return self.irf_raman
        except Exception as e: 
            if type(self.yaxis_file) is str and (len(self.yaxis_file) == 0): # If True, file selection was canceled
                logger.info("Canceled: No Raman yaxis file was selected")
            logger.error(e, exc_info=True)

    def select_spectralon(self):
        try:
            self.spectralon_file = QtWidgets.QFileDialog.getOpenFileName(self, caption = "Select a spectralon file", filter=("Joblib files (*.joblib)"))[0] #CHANGE FILTER PARAMETER
            print('self.spectralon_file: ', self.spectralon_file, 'type: ', type(self.spectralon_file))
            with open(self.spectralon_file, 'rb') as f:
                self.spectralon_data = joblib.load(f)
                print('Spectralon data:', self.spectralon_data)
            url = QUrl.fromLocalFile(self.spectralon_file)
            print('url: ', url )
            self.lineEditSpectralonFile.setText(url.fileName()) # Display the selected spectralon file
            self.checkBoxSpectralon.setCheckable(True) # Make the normalization check available
            logger.info("Selected spectralon file: %s", url.fileName())
            return self.spectralon_data
        except Exception as e: 
            if type(self.spectralon_file) is str and (len(self.spectralon_file) == 0): # If True, file selection was canceled
                logger.info("Canceled: No Spectralon file was selected")
            logger.error(e, exc_info=True)
        
        
        
        # self.spectralon_file = QtWidgets.QFileDialog.getOpenFileName(self, caption = "Select a spectralon file", filter=("Text files (*.txt)"))[0] #CHANGE FILTER PARAMETER
        # url = QUrl.fromLocalFile(self.spectralon_file)
        # print("spectralon file to be used:", url.fileName())
        # self.lineEditSpectralonFile.setText(url.fileName()) # Display the selected Spectralon file 
        # self.checkBoxSpectralon.setCheckable(True) # Make the normalization check available 

    #TODO
    #Add Raman profile and model selection HERE
    #Add acquisition function
    #Add comments and acq names retrieval into a list according to current save folder directory
    #Display comments following acq names present in combobox
    #Data saving directory selection 
    def select_save_folder_dir(self):
        """Opens a window to select a folder directory"""
        print("SELECTING FOLDER")
        self.save_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Directory to save data")
        print("Save directory:", self.save_dir)
        self.labelSaveDirectory.setText(self.save_dir) #Display the selected directory
        print("Getting saved acquisitions data")
        self.saved_data_list = self.get_saved_acquisitions_data(directory=self.save_dir)
        print("Got saved acquisitions data")
        self.construct_acq_name_combobox(data_list= self.saved_data_list)
        self.update_ui()

    def save_acquisition(self, directory, acq_name, acq_comment, 
                         DRS_background = None, xaxis_DRS = None, DRS_data = None, 
                         DRS_exposure = None, raman_background = None,  xaxis_raman = None, raman_data = None, raman_exposure = None):
        """
        Structures data into a dictionnary and saved into .joblib file.
        inputs

        outputs 
        saved_data: dictionnary with measured data 
        """
        saved_data =  {}
        saved_data['acquisition_name'] = acq_name
        saved_data['comment'] = acq_comment
        saved_data['drs_background'] = DRS_background
        saved_data['xaxis_DRS'] = xaxis_DRS
        saved_data['drs_data'] = DRS_data
        saved_data['drs_exposure'] = DRS_exposure
        saved_data['raman_background'] = raman_background
        saved_data['xaxis_raman'] = xaxis_raman
        saved_data['raman_data'] = raman_data
        saved_data['raman_exposure'] = raman_exposure
        self.saved_data_list.append(saved_data) #add newer data to list of saved data to be displayed on ui
        if self.checkBoxSave.isChecked() == True:
            filename = acq_name.replace(" ", "_")+".joblib" #make name into snakecase
            with open(directory+'\\'+filename, 'w') as f:# Save data in .joblib file
                print(f"Saving at {directory}\\{filename}")
                joblib.dump(saved_data, directory +'\\'+ filename)
            logger.info(f"Saved at {directory}\\{filename}")
        return saved_data

    def update_acq_combobox(self, acq_name: str, current_data: dict) -> None:
        self.comboBoxAcqName.insertItem(0, acq_name, current_data)
        self.comboBoxAcqName.setCurrentIndex(0)
        #self.textEditComment.setPlainText(self.comboBoxAcqName.currentData()["comment"])

    def display_saved_data(self):
        try:
            print("self.comboBoxAcqName.currentData(): ", self.comboBoxAcqName.currentData())
            current_data = self.comboBoxAcqName.currentData()
            self.textEditComment.setPlainText(current_data["comment"]) #access the data linked to the combobox item
            if current_data["drs_data"] is not None:
                DRS_background = current_data['drs_background']
                DRS_spectrum = np.hstack((np.atleast_2d(DRS_background).T, current_data['drs_data']))
                xaxis_DRS = current_data['xaxis_DRS']
                labels = []
                for i in range(DRS_spectrum.shape[1]):
                    if i == 0:
                        labels.append('background')
                    else:
                        labels.append(f"acquisition {i-1}")
                self.display_DRS.update_plot(xaxis_DRS, DRS_spectrum, labels)
            if current_data["raman_data"] is not None:
                raman_spectrum = (current_data['raman_data'] - current_data['raman_background'])
                xaxis_raman = current_data['xaxis_raman']
                self.irf = self.yaxis_data['raman_data']
                raman_corr_irf = raman_spectrum/self.irf
                self.display_raman.update_plot(xaxis_raman, raman_spectrum)
                
        except Exception as e:
            logger.error(e, exc_info=True) 
        
        # TODO 
        # add display of spectra

    # def display_saved_data(self, data_list: list | None = None):
    #     print('data_list in display_data:', data_list)
    #     if data_list is None:
    #         data_list = self.saved_data_list
    #     if not data_list:
    #         return # do nothing if self.data_file_list is None 
    #     acq_name = self.comboBoxAcqName.currentText()
    #     for data in data_list:
    #         if data['acquisition_name'] == acq_name:
    #             self.textEditComment.setPlainText(self.comboBoxAcqName.currentData()["comment"])
    #             break #stop if the right acquisition name has been found
    
    def construct_raman_profile_combobox(self):
        try:        
            self.raman_profiles = self.get_raman_profiles()
            if type(self.raman_profiles) == ConnectionRefusedError:
                raise ConnectionRefusedError(f"self.raman_profiles")
            self.comboBoxRamanProfile.clear()
            for profile in self.raman_profiles:
                self.comboBoxRamanProfile.addItem(profile)
        except Exception as e:
            logger.error(e, exc_info=True) 
            

    def construct_acq_name_combobox(self, data_list: list | None = None):
        try:
            if data_list is None:
                data_list = self.saved_data_list
            if not data_list:
                return # do nothing if self.data_file_list is None 
            print("Before self.comboBoxAcqName.currentIndex(): ",self.comboBoxAcqName.currentIndex(), 'self.comboBoxAcqName.currentText():', self.comboBoxAcqName.currentText())
            self.comboBoxAcqName.blockSignals(True)
            self.comboBoxAcqName.clear()
            print("Constructing combobox...")
            for data in data_list:
                try:
                    self.comboBoxAcqName.addItem(data['acquisition_name'], data) # the data is linked to each combobox
                except Exception as e:
                    logger.error(e, exc_info=True) 
                     
            self.comboBoxAcqName.blockSignals(False)
            self.comboBoxAcqName.setCurrentIndex(0) # Select the first index when combobox is constructed#########################################################
            print("After self.comboBoxAcqName.currentIndex(): ",self.comboBoxAcqName.currentIndex(), 'self.comboBoxAcqName.currentText():', self.comboBoxAcqName.currentText())
        except Exception as e:
            logger.error(e, exc_info=True) 
        self.update_ui()

    def get_saved_acquisitions_data(self, directory: str | None = None):
        try: 
            if directory is None:
                directory = self.save_dir
            data_list = []
            if not directory:
                return data_list
            search_path = os.path.join(directory, "*.joblib") # Only .joblib files will be looked at
            print("search_path:", search_path)
            print("glob.glob(path):", glob.glob(search_path))
            for i,file in enumerate(glob.glob(search_path)):
                print(f"file {i}:", file)
                if not os.path.exists(file): #See if path exists
                    print("path doesn't exist")
                    continue
                with open(file, 'rb') as f:
                    data_file = joblib.load(f)
                    print(data_file)
                    data_list.append(data_file) # load data)
                    # self.acqnames_list.append(data_file['acquisition_name'])
                    # self.comments_list.append(data_file['comment'])
                    # TODO
                    # Add DRS and Raman Data to be extracted from file
            return data_list
        except Exception as e:
            logger.error(e, exc_info=True) 

    def get_acquisition_name(self) -> str:
        self.acqname = self.lineEditAcqName.text().replace(" ", "_")
        self.acqnames_list.append(self.acqname)
        return self.acqname
    
    def get_acquisition_comment(self) -> str:
        comment = self.textEditComment.toPlainText()
        print("self.comment: ",comment," self.textEditComment.toPlainText(): ", self.textEditComment.toPlainText())
        self.comments_list.append(comment)
        return comment

    def get_DRS_acq_params(self):
        try:
            min_aec_exp = float(self.lineEditMinAutoExposure.text()) 
            max_aec_exp = float(self.lineEditMaxAutoExposure.text())  
            min_acq_exp = float(self.lineEditMinExposure.text()) 
            max_acq_exp = float(self.lineEditMaxExposure.text()) 
            max_count = int(self.lineEditMaxCount.text())
            N_accumulations = int(self.lineEditNumDRSAcq.text()) 
        except Exception as _:
            return None
        return min_aec_exp, max_aec_exp, min_acq_exp, max_acq_exp, max_count, N_accumulations

    def get_raman_profiles(self) -> list:
        # Get a list of currently available profiles in oras
        try:
            self.raman_profiles = ext.get_profiles()
            if type(self.raman_profiles) == ConnectionRefusedError:
                raise ConnectionRefusedError(self.raman_profiles)
        except Exception as e:
            self.raman_profiles = [
                    '1 x MPE - 50 mW.toml', 
                    '1 x MPE - 100 mW.toml', 
                    '2 x MPE - 100 mW.toml', 
                    '2 x MPE - 150 mW.toml', 
                    '5 x MPE - 150 mW.toml',
                    'tylenol.toml']
            logger.error(e, exc_info=True)            
        return self.raman_profiles
    
    def get_exposure(self):
        logger.info("Setting Exposure time to : %s", self.doubleSpinBoxExposure.value())
        return self.doubleSpinBoxExposure.value()

    def get_spectrum(self):
        self.pushButtonMeasureRamanDRS.setEnabled(False)
        logger.info("Acquiring spectrum")
        if self.mayaspectro.isconnected:
            wavelengths, intensities = self.mayaspectro.spectrum_acquisition(
                self.get_exposure()
            )
            self.disp.ax.cla()  # Clears axis
            self.disp.plot_basic_line(wavelengths, intensities, label=f"acquisition")
            logger.info("Spectrum acquired")
        self.update_ui()

    def get_latest_raman_files(self):
        folders_dir = self.main_oras_dir + 'data'
        logger.info(f"Looking into following folder for Raman data: {folders_dir}")
        walk = os.walk(folders_dir) #top down walk of directory content in tuples of (root,dirs,files)
        data_paths = []
        for (root,dirs,files) in walk:
            file_dirs  = [root+ f"/{f}" for f in files if (f.endswith('.joblib') or f.endswith('.toml'))]
            data_paths+= file_dirs
        def extension_key(data):
            if data.endswith('.joblib'):
                return 0
            elif data.endswith('.toml'):
                return 1
        most_recent_data = sorted(data_paths, key=os.path.getmtime, reverse = True) # Sort all files according to their timestamp 
        extension_sorted_files = sorted(most_recent_data[0:2], key=extension_key)  # Sort files according to their extension (.joblib first then .toml)
        joblib_file, toml_file = extension_sorted_files[0], extension_sorted_files[1]
        logger.info(f"Most recent .joblib file found: {joblib_file}")
        logger.info(f"Most recent .toml file found: {toml_file}")
        return joblib_file, toml_file
    
    def get_latest_raman_data(self):
        joblib_file, toml_file = self.get_latest_raman_files()
        data_file = joblib.load(joblib_file)
        toml_dict = tomli.load(toml_file)
        raman_xaxis= data_file['xaxis']
        raman_bkg = data_file['background']
        raman_accumulations= data_file['accumulations']
        raman_exposure= toml_dict['acquisition_profile']['exposure_time'] # ms
        return raman_xaxis, raman_bkg, raman_accumulations, raman_exposure
    
    def AEC_extrapolation(self, shutter_position: int, min_aec_exp: float, max_aec_exp: float, min_acq_exp: float, max_acq_exp: float, target_count: int) -> float:
        """
        This automatic exposure control algorithm tries to measure two values of max count with their associated 
        exposure times. It then extrapolates, with a linear curve, the exposure that maximizes dynamic range while being within max_acq_exp and min_acq_exp.
        """
        try:
            hardware_min_exposure, hardware_max_exposure = self.mayaspectro.get_exposure_time_lims() #minimal exposure time in ms (/1000 to convert from micro seconds to ms)
            hardware_max_count = self.mayaspectro.get_max_intensity()
            if max_acq_exp > hardware_max_exposure:
                max_acq_exp = hardware_max_exposure
                logger.warning("The given maximum exposure is higher then the spectrometer's maximum,\nMax exposure set to hardware maximum: %f ms", hardware_max_exposure)            
            elif max_acq_exp <= hardware_min_exposure:
                logger.error("The given maximum exposure is lower then the spectrometer's minimum of %f ms.", hardware_min_exposure)
                return None
            
            if (min_acq_exp <= hardware_min_exposure):
                min_acq_exp = hardware_min_exposure
                logger.warning("The given minimum exposure is lower then the spectrometer's minimum.\nMin exposure set to hardware minimum: %f ms", hardware_min_exposure)
            elif (min_acq_exp > hardware_max_exposure):
                logger.error("Minimimum exposure exceeds hardware maximum of %f ms", hardware_max_exposure)
                return None
            
            if target_count > hardware_max_count:
                target_count = hardware_max_count
                logger.warning("The given maximum count is higher than the maximum count measurable by the spectrometer.\nThe target count will be set to the hardware's highest measurable count: %f", hardware_max_count)

        except Exception as e:
            logger.error("AEC failed: %s", str(e))
            self.disable_lamp() 
            return None
        
        exposures = np.array([min_aec_exp, max_aec_exp]) # ms 
        
        self.lamp.set_shutter_position(shutter_position)
        self.enable_lamp() #Start illumination
        print(f'Exposures used for count determination: min exposure = {exposures[0]} ms, max exposure = {exposures[1]} ms')
        count_min_exposure = self.mayaspectro.spectrum_acquisition(exposures[0])[1] 
        count_max_exposure = self.mayaspectro.spectrum_acquisition(exposures[1])[1]
        plt.figure()
        plt.plot(count_min_exposure, label = f'count_min_exposure = {exposures[0]}ms')
        plt.plot(count_max_exposure, label = f'count_max_exposure = {exposures[1]}ms')
        max_counts = np.array([np.max(count_min_exposure), np.max(count_max_exposure)]) # counts
        print(f"Determined counts = {max_counts[0]}, {max_counts[1]}")
        while max_counts[1] > hardware_max_count:
            exposures -= 10
            if exposures[0] <= hardware_min_exposure:
                exposures[0] = hardware_min_exposure
                max_counts = np.array([np.max(self.mayaspectro.spectrum_acquisition(exposures[0])[1]), 
                                       np.max(self.mayaspectro.spectrum_acquisition(exposures[1])[1])])
                break
            max_counts = np.array([np.max(self.mayaspectro.spectrum_acquisition(exposures[0])[1]), 
                                   np.max(self.mayaspectro.spectrum_acquisition(exposures[1])[1])])
        
        a = (max_counts[1]-max_counts[0])/(exposures[1]-exposures[0])
        b = max_counts[1]-(a*exposures[1])
        optimal_exp = (target_count - b)/a
        
        if optimal_exp > hardware_max_exposure:
            optimal_exp = hardware_max_exposure
            logger.warning("The optimal exposure is higher than the hardware maximum. Exposure set to hardware maximum: %f ms", hardware_max_exposure)

        elif optimal_exp <= hardware_min_exposure:
            optimal_exp = hardware_min_exposure
            logger.warning("The optimal exposure is lower than the hardware minimum. Exposure set to hardware minimum: %f ms", hardware_min_exposure)

        if optimal_exp > max_acq_exp:
            optimal_exp = max_acq_exp
            logger.warning("The optimal exposure is higher than the maximum set by user. Exposure set to user maximum: %f ms", max_acq_exp)

        elif optimal_exp <= min_acq_exp:
            optimal_exp = min_acq_exp
            logger.warning("The optimal exposure is higher than the minimum set by user. Exposure set to user minimum: %f ms", min_acq_exp)

        opt_exp_measured_count = self.mayaspectro.spectrum_acquisition(optimal_exp)[1]

        real_max_count = np.max(opt_exp_measured_count)
        plt.plot(opt_exp_measured_count, label = f'opt_exp_measured_count = {optimal_exp}ms')

        plt.legend()
        plt.show()
        self.disable_lamp() #Stop illumination
        print(f"After verification: exposures = {exposures} ms with counts = {max_counts}")
        print(f"AEC extrapolation parameters: a = {a}, b = {b}")
        print(f"Target count of {target_count} used to find optimal exposure: {optimal_exp} ms, but got max count of {real_max_count}")
        logger.info(f"Target count of {target_count} used to find optimal exposure: {optimal_exp} ms, but got max count of {real_max_count}")
        return optimal_exp

    def DRS_background_acquisition(self, exposure): 
        self.disable_lamp() # Stop illumination
        wavelengths, bkg_intensity = self.mayaspectro.spectrum_acquisition(exposure)
        return wavelengths, bkg_intensity

    def DRS_acquisition(self):
        # If some AEC parameters are missing, nothing is returned
        print("DRS acquisition parameters:", self.get_DRS_acq_params())
        if self.get_DRS_acq_params() == None:
            return None
        # Get optimal exposure
        min_aec_exp, max_aec_exp, min_acq_exp, max_acq_exp, target_count, N_accumulations = self.get_DRS_acq_params()
        shutter_position = 400 #value of max shutter opening to make sure that it is completely open
        aec_exposure = self.AEC_extrapolation(shutter_position, min_aec_exp, max_aec_exp, min_acq_exp, max_acq_exp, target_count)    
        print("aec_exposure", aec_exposure) 
        
        self.lineEditSetExposure.setText(str(int(aec_exposure)))
        # Proceed with the measurement including background signal substraction
        xaxis_DRS, DRS_background = self.DRS_background_acquisition(aec_exposure) #background to be substracted from normal acquisition
        self.enable_lamp()
        for i in range(N_accumulations):
            xaxis_DRS, intensity = self.mayaspectro.spectrum_acquisition(aec_exposure)
            if i == 0:
                DRS_data = np.atleast_2d(intensity-DRS_background).T
            else:
                DRS_data = np.hstack((DRS_data, np.atleast_2d(intensity-DRS_background).T))
        print(f"DRS_data.shape: {DRS_data.shape}")
        self.disable_lamp()
        return DRS_background, xaxis_DRS, DRS_data, aec_exposure

    def button_DRS_acquisition(self):
        # Turn on measuring and tell user it is measuring
        print("comment from the start: ",self.get_acquisition_comment())
        self.is_measuring = True
        self.pushButtonMeasureDRS.setDisabled(self.is_measuring) 
        self.pushButtonMeasureDRS.setText("Measuring...")
        QApplication.processEvents()
        self.update_ui()
        acq_name = self.get_acquisition_name()
        acq_comment = self.get_acquisition_comment()
        DRS_background, xaxis_DRS, DRS_data, DRS_exposure  = self.DRS_acquisition()
        print("comment after self.DRS_acquisition(): ",self.get_acquisition_comment())
        # Get info
        
        print('acq_comment: ', acq_comment)
        
        saved_data = self.save_acquisition(self.save_dir, acq_name, acq_comment, 
                                            DRS_background = DRS_background, xaxis_DRS = xaxis_DRS, 
                                            DRS_data = DRS_data, DRS_exposure = DRS_exposure)
        self.update_acq_combobox(acq_name, saved_data)
        self.is_measuring = False
        #self.pushButtonMeasureDRS.setEnabled(not self.is_measuring)
        self.pushButtonMeasureDRS.setText("DRS")
        
        self.update_ui()
    
    def raman_acquisition(self):
        try:
            acq_name = self.get_acquisition_name()
            comment = self.get_acquisition_comment()
            ext.set_file_name(acq_name) #Sets the file name in ORAS
            ext.set_comment(comment) #Sets the comment in ORAS
            ext.start_acquisition(blocking = True) #Tells ORAS to start acquisition
            
            # TODO add a function to get raman data in file saved by oras. save it to own directory
        except Exception as e:
            logger.error(f"Error during Raman acquisition: {e}")
            
    def button_raman_acquisition(self):
        try:
            self.pushButtonMeasureRaman.setEnabled(False)
            self.pushButtonMeasureRaman.setText("Measuring...")
            self.raman_acquisition(self)
            acq_name = self.get_acquisition_name()
            acq_comment = self.get_acquisition_comment()
            raman_xaxis, raman_bkg, raman_accumulations, raman_exposure = self.get_latest_raman_data()
            saved_data = self.save_acquisition(self.save_dir, acq_name, acq_comment,
                                            raman_background = raman_bkg,  xaxis_raman = raman_xaxis, 
                                            raman_data = raman_accumulations, raman_exposure=raman_exposure)
            self.update_acq_combobox(acq_name, saved_data)
            logger.info(f"Raman acquisition done")
        except Exception as e:
            logger.error(f"Error during Raman acquisition: {e}")
        self.pushButtonMeasureRaman.setEnabled(True)
        self.pushButtonMeasureRaman.setText("Raman")
        self.update_ui()

    def button_raman_DRS_acquisition():
        pass
    
    def get_acquisition_comments(self):
        return None

    def enable_lamp(self):
        logger.info("Enabling lamp")
        self.lamp.set_enable(True)
        self.last_enabled_state = True
        self.update_ui()

    def disable_lamp(self):
        logger.info("Disabling lamp")
        self.lamp.set_enable(False)
        tt.sleep(0.5) #wait for lamp to turn off
        self.last_enabled_state = False
        self.pulse_timer.stop() #If a pulse is running and disable button is pressed, the pulse will be stopped
        self.update_ui()

    def set_timed_pulse(self):
        """A timed pulse controlled by the user"""
        pulse_time = self.spinboxPulseDuration.value() #in milliseconds
        self.enable_lamp()
        self.pulse_timer.start(pulse_time) #wait the pulse time and then disable lamp     

    # def set_shutter_position(self):
    #     shutter_position = self.spinboxShutterPosition.value()
    #     logger.info("Setting lamp shutter position : %s", shutter_position)
    #     self.lamp.set_shutter_position(shutter_position)
    #     self.update_ui()

    def set_initial_lamp_configurations(self):
        if self.lamp_info.is_connected:
            logger.info("Setting initial lamp configurations")
            logger.info("Setting lamp to disable")
            self.lamp.set_enable(False)
            logger.info("Setting lamp shutter position to a closed position")
            self.lamp.set_shutter_position(-400)
            logger.info("Setting lamp shutter closed position as home position")
            self.lamp.set_home_position()

    def setup_update_timer(self):
        """Creates the PyQt Timer and connects it to the function that updates
        the UI and gets the lamp infos."""
        self.update_timer = QTimer()
        self.update_timer.setInterval(100)
        self.update_timer.timeout.connect(self.update_ui)
    
    def setup_pulse_timer(self):
        self.pulse_timer = QTimer()
        self.pulse_timer.timeout.connect(self.disable_lamp)
        self.pulse_timer.setSingleShot(True)
        
    def set_labels_connected(self, lamp_isconnected: bool, spectro_isconnected: bool) -> None:
        if spectro_isconnected:
            self.labelSpectroConnected.setText("Connected")
            self.labelSpectroConnected.setStyleSheet("color:green")
        else:
            self.labelSpectroConnected.setText("Not Connected")
            self.labelSpectroConnected.setStyleSheet("color:red")
        if lamp_isconnected:
            self.labelLampConnected.setText("Connected")
            self.labelLampConnected.setStyleSheet("color:green")
        else:
            self.labelLampConnected.setText("Not Connected")
            self.labelLampConnected.setStyleSheet("color:red")
    
    def set_label_lamp_enabled(self, isenabled: bool) -> None:
        if isenabled:
            self.labelLampConnected.setText("ENABLED") #labelLampEnabled
            self.labelLampConnected.setStyleSheet("color:red")
        else:
            self.labelLampConnected.setText("Disabled")
            self.labelLampConnected.setStyleSheet("color:green")
    
    def set_oras_profile(self):
        try:
            set_oras_profile_message = ext.set_profile(self.comboBoxRamanProfile.currentText())
            if type(set_oras_profile_message) == ConnectionRefusedError:
                raise ConnectionRefusedError(set_oras_profile_message)
        except Exception as e:
            logger.error(e, exc_info=True)

    def _on_set_oras_status_result(self, status):
        self.last_oras_status = status # get the last oras status that was found

    def set_oras_status_loopworker(self):
        logger.info("Setting loop thread for oras status fetching")
        try:   
            self.oras_loop_worker = LoopWorkerThread(ext.get_system_status)  # create a long-running LoopWorkerThread instance, test method: self.test_oras_status_change
            self.threadpool.start(self.oras_loop_worker)
            self.oras_loop_worker.signals.result.connect(self.set_oras_status)
        except Exception as e:
            logger.error(e, exc_info=True)

    def test_oras_status_change(self,n:int):
        if n % 2 == 0:
            self.oras_status = 'READY'
            #self.lineEditOrasStatus.setStyleSheet("color:red")
        else: 
            self.oras_status = 'ACQUIRING' 
            #self.lineEditOrasStatus.setStyleSheet("color:green")
        #self.lineEditOrasStatus.setText(self.oras_status)
        return self.oras_status
    def set_oras_status(self, oras_status):
        try:
            possible_oras_status = ['READY', 'NOT READY', 'ACQUIRING']
            colors = ["color:green", "color:red","color:orange"]
            if type(oras_status) == ConnectionRefusedError:
                raise ConnectionRefusedError(oras_status)
            elif oras_status in possible_oras_status:
                self.is_oras_linked = True
                self.lineEditOrasStatus.setText(f'CONNECTED: {oras_status}')
                self.lineEditOrasStatus.setStyleSheet(colors[possible_oras_status.index(oras_status)])
            else:
                self.is_oras_linked = False
                oras_status = 'NOT CONNECTED'
                self.lineEditOrasStatus.setText(oras_status)
                self.lineEditOrasStatus.setStyleSheet("color:red")
        except ConnectionRefusedError as e:
            logger.error(e, exc_info=True)
            self.is_oras_linked = False
            oras_status = 'NOT CONNECTED'
            self.lineEditOrasStatus.setText(oras_status)
            self.lineEditOrasStatus.setStyleSheet("color:red")
        finally:
            return self.is_oras_linked, oras_status 
                        
    def update_ui(self):
        self.update_info() #Used to be for the lamp control widget
        # Enable/disable controls if lamp is connected or not
        is_lamp_connected = self.lamp_info.is_connected
        is_spectro_connected = self.spectro_info.is_connected
        is_oras_linked = self.is_oras_linked
        self.pushbtnConnectLamp.setEnabled(not is_lamp_connected)
        self.comboBoxAvailableLamp.setEnabled(not is_lamp_connected)
        self.pushbtnFindLamp.setEnabled(not is_lamp_connected)
        self.pushbtnDisconnectLamp.setEnabled(is_lamp_connected)
        
        self.pushbtnConnectSpectro.setEnabled(not is_spectro_connected)
        self.comboBoxAvailableSpectro.setEnabled(not is_spectro_connected)
        self.pushbtnFindSpectro.setEnabled(not is_spectro_connected)
        self.pushbtnDisconnectSpectro.setEnabled(is_spectro_connected)
        
        self.pushButtonMeasureDRS.setEnabled(is_spectro_connected and is_lamp_connected and (not self.is_measuring))
        self.pushButtonMeasureRaman.setEnabled(is_oras_linked)
        #self.pushButtonMeasureRamanDRS.setEnabled(is_spectro_connected and is_lamp_connected and is_oras_linked)
        self.set_labels_connected(is_lamp_connected,is_spectro_connected)
        #self.construct_raman_profile_combobox()
        #self.set_oras_status()
        if (self.saved_data_list is not None) and (len(self.saved_data_list) > 0)  and (not self.is_measuring):
            self.display_saved_data()

        if self.checkBoxSave.isChecked() == True:
            print("Acquisition will be saved.") 
            self.labelSaveMessage.setStyleSheet("color: green;") #
            self.labelSaveMessage.setText("Acquisition will be saved")

        elif self.checkBoxSave.isChecked() == False:
            print("Acquisition will not be saved.") 
            self.labelSaveMessage.setStyleSheet("color: red;") #background-color: black;
            self.labelSaveMessage.setText("Acquisition will not be saved")
        
        
    def lamp_safety_check(self):
        is_enabled = self.lamp_info.is_enabled
        if is_enabled != self.last_enabled_state:
            logger.warning(
                "Lamp safety trip setting lamp to %s",
                ["Disabled", "Enabled"][is_enabled],
            )
            self.lamp.set_enable(is_enabled)
            self.last_enabled_state = is_enabled

    def update_info(self):
         self.lamp_info = self.lamp.get_info()
         self.spectro_info = self.mayaspectro.get_info()
         self.lamp_safety_check()

    #     # update UI based on LampInfo
         self.set_label_lamp_enabled(self.lamp_info.is_enabled)

    def closeEvent(self, event: QCloseEvent):
        """
        This method is called when a close request is received for the window.
        """
        reply = QMessageBox.question(self, 'Message',
                                     "Are you sure you want to quit\nDRS OVERTAKE?",
                                     QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)

        if reply == QMessageBox.No:
            print("Application is closing...")
            event.ignore()  #Ignore the close event, keeps the window open
            return
        if hasattr(self, "oras_loop_worker") and self.oras_loop_worker is not None:
            #close long-running LoopWorkerThread instance
            try:
                self.oras_loop_worker.stop()
            except Exception:
                logger.exception("Failed to stop oras loop worker")
        
        #Disconnect lamp and spectrometer
        try:
            if hasattr(self, "lamp") and getattr(self, "lamp", None) is not None:
                try:
                    self.disconnect_lamp_worker()
                except Exception:
                    logger.exception("Error disconnecting lamp")
            if hasattr(self, "mayaspectro") and getattr(self, "mayaspectro", None) is not None:
                try:
                    self.disconnect_mayaspectro_worker()
                except Exception:
                    logger.exception("Error disconnecting spectrometer")
        except Exception:
            logger.exception("Error during hardware cleanup")
        
        #Wait 2 second for threadpool tasks to finish
        try:
            #waitForDone expects milliseconds
            self.threadpool.waitForDone(2000)  # waits for 2 second for threadpool to finish
        except Exception:
            logger.exception("Error while waiting for threadpool to finish")
        
        
              

    # def closeEvent(self, event: QCloseEvent):
    #     # request worker to stop, wait a short time for clean exit
    #     try:
    #         if hasattr(self, "threadpool"):
    #             print('in hasattr')
    #             self.threadpool.waitForDone(-1)  # ms
    #     except Exception:
    #         pass
    #     event.accept()

if __name__ == "__main__":

    # Set up logging
    configure_logger()

    try:    
        # Create app window
        app = QApplication(sys.argv)
        window = LumedDRSWidget()#QMainWindow()
        window.show()
        
        #window.setCentralWidget(LumedDRSWidget())

        app.exec_()
    except:
        window.LumedDRSWidget.threadpool.stop()