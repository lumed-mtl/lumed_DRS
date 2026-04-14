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
from arduino_control import Arduino
import lumed_algos as la
try:
    import oras.backend.external_trigger as ext
except ModuleNotFoundError:
    print("ORAS package not found")

logger = logging.getLogger(__name__)

LOGS_DIR = Path.home() / "logs/lumed_DRS"
LOG_PATH = LOGS_DIR / f"{strftime('%Y_%m_%d_%H_%M_%S')}.log"

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
    # Reduce noisy output from pyvisa/pyserial internals
    logger.setLevel(logging.DEBUG)
    logging.getLogger("pyvisa").setLevel(logging.WARNING)
    logging.getLogger("pyvisa.messagebased").setLevel(logging.WARNING)
    logging.getLogger("pyvisa-py").setLevel(logging.WARNING)
    logging.getLogger("serial").setLevel(logging.WARNING)
    
    # Prevent messages from being propagated to the root logger (and printed again)
    logger.propagate = False

class LumedDRSWidget(QMainWindow, Ui_Form):
    """Main GUI for controlling the Lumed DRS system and perfoming acquisitions.

    Provides a graphical interface to control an HL-2000-HP-232R lamp and Maya2000pro
    spectrometer. Performs diffuse reflectance spectroscopy (DRS) and Raman acquisitions (including combined
    Raman+DRS), load calibration files (x/y axes and spectralon), display
    and save spectra. Long-lived operations are run in background worker threads.

    Attributes:
    lamp (HL2000Lamp): Lamp controller instance.
    lamp_info (LampInfo): Current lamp status and metadata.
    last_enabled_state (bool): Last known enabled state of the lamp.
    is_spectro_connected (bool): True when spectrometer is connected.
    is_oras_linked (bool): True when ORAS integration is available.
    is_measuring (bool): True while an acquisition is running.
    mayaspectro (MayaSpectrometer): Spectrometer controller instance.
    spectro_info (SpectroInfo): Current spectrometer status and metadata.
    xaxis_file (str | None): Path to loaded Raman x-axis calibration file.
    yaxis_file (str | None): Path to loaded Raman y-axis calibration file.
    xaxis_data (dict | None): Parsed contents of the x-axis calibration file.
    yaxis_data (dict | None): Parsed contents of the y-axis calibration file.
    xaxis_raman (numpy.ndarray | None): Calibrated Raman x-axis values.
    irf_raman (numpy.ndarray | None): Instrument response function of Raman acquisitions.
    spectralon_file (str | None): Path to loaded spectralon file.
    spectralon_data (dict | None): Parsed spectralon file contents.
    spectralon_spectrum (numpy.ndarray | None): Processed spectralon spectrum.
    save_dir (str | None): Directory where acquisition acquisition files are saved.
    acqname (str | None): Current acquisition name.
    saved_data_list (list): Loaded/saved acquisition records.
    main_oras_dir (str): Directory for ORAS data.
    display_raman (DataDisplayWidget): Plot widget for Raman spectra.
    display_DRS (DataDisplayWidget): Plot widget for DRS spectra.
    verticalLayout_raman (QVBoxLayout): Layout containing Raman plot widgets.
    verticalLayout_DRS (QVBoxLayout): Layout containing DRS plot widgets.
    threadpool (QThreadPool): Thread pool used for background workers.
    oras_loop_worker (LoopWorkerThread | None): Background worker polling ORAS.
    raman_profiles (list): Cached ORAS Raman profiles.
    tylenol_peaks (numpy.ndarray): Reference Tylenol Raman peak positions.
    oras_status

    Methods:
    # ============= Instrument control methods =============
    find_lamp() -> None: Discover connected HL-2000 lamp devices.
    find_spectro() -> None: Discover connected Maya spectrometers.
    connect_lamp() -> None: Connect to selected lamp and apply initial config.
    disconnect_lamp() -> None: Disconnect the lamp safely.
    connect_mayaspectro() -> None: Connect to selected Maya spectrometer.
    disconnect_mayaspectro() -> None: Disconnect the Maya spectrometer.
    enable_lamp() -> None: Enable lamp output.
    disable_lamp() -> None: Disable lamp output and stop pulses.
    set_initial_lamp_configurations() -> None: Sets the lamp's initial configurations
    lamp_safety_check() -> None: Checks if lamp is in the currently expected state.
    update_info() -> None: Updates the info related to the lamp and spectrometer state and metadata.

    # ============= User file and folder selection methods =============
    select_xaxis() -> None: Load Raman x-axis calibration from a joblib file.
    select_yaxis() -> None: Load Raman y-axis (IRF) calibration from a joblib file.
    select_spectralon() -> None: Load spectralon calibration spectra from a joblib file.
    select_save_folder_dir() -> None: Set directory to save acquisition files.

    # ============= DRS and Raman acquisition methods =============
    AEC_extrapolation(...) -> float: Estimate exposure time via automatic exposure control.
    save_acquisition(...) -> dict: Structure and optionally localy save acquisition data.
    DRS_background_acquisition(...) -> Tuple[numpy.ndarray, numpy.ndarray]: Permforms a background measurement of a DRS acquisition.
    DRS_acquisition(progress_callback) -> Tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray, float]: Perform a DRS acquisition sequence.
    button_DRS_acquisition(...) -> Tuple[str, dict]: Trigger a DRS acquisition sequence and saves the acquired data when DRS button is pressed by user.
    raman_acquisition(acq_name, acq_comment) -> None: Trigger ORAS Raman acquisition.
    button_raman_acquisition() -> Tuple[str, dict]: Trigger ORAS Raman acquisition and save acquired data when Raman button is pressed by user.
    button_raman_DRS_acquisition() -> Tuple[str, dict]: Trigger DRS acquisition followed by ORAS Raman acquisition and save acquired data when Raman/DRS button is pressed by user.
    
    # ============= UI control methods =============
    setup_default_ui() -> None: Setup UI elements' default state
    connect_ui_signals() -> None: Connect interactive UI elements to methods
    set_labels_connected() -> None: Sets UI labels for lamp and spectrometer connection status.
    set_label_lamp_enabled() -> None: Sets UI labels for lamp light enabling status (enabled or not).
    update_ui() -> None: Refresh UI elements based on current system state.
    update_acq_combobox(...) -> None: Stores data in the UI's comboBoxAcqName object.
    display_saved_data() -> None: Plots data on the display_DRS and display_raman widgets. 
    construct_raman_profile_combobox() -> None: Constructs the contents of the UI's comboBoxRamanProfile object.
    construct_acq_name_combobox(...) -> None: Constructs the contents of the UI's comboBoxAcqName object.
    set_oras_profile(...) -> None: Triggers ORAS to set the user selected profile.
    set_oras_status_loopworker() -> None: Start background polling of ORAS status.
    set_oras_status(...) -> None: Update UI / link state from ORAS status.
    closeEvent(event) -> None: Handle application close, cleanup hardware and workers.

    # ============= Getter methods =============
    get_saved_acquisitions_data(...) -> list: Gets data from joblib files in the folder selected by user.
    get_acquisition_name() -> str: Gets acquisition name entered by user.
    get_acquisition_comment() -> str: Gets acquisition comment entered by user.
    get_DRS_acq_params() -> tuple(float, float, float, float, int, int): Gets DRS acquisition parameter values entered by user.
    get_raman_profiles() -> list[str]: Gets a list of oras acquisition profile names currently available in ORAS.
    get_latest_raman_files() -> str: Retrieves the last .joblib and .toml files generated by ORAS.
    get_latest_raman_data() -> Tuple[numpy.ndarray]: Retrieves raman spectra data from the joblib and toml files returned by get_latest_raman_files().
    
    # ============= Threading methods =============
    *_worker() -> None: Run methods in background workers and update UI when done.

    Example:
    ```python
    import sys
    app = QApplication(sys.argv)
    w = LumedDRSWidget()
    w.show()
    app.exec_()
    ```
    """

    def __init__(self, parent=None):
        super().__init__()
        self.setupUi(self)

        # logger
        self.setWindowTitle("DRS OVERTAKE")
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
        self.spectralon_data: dict|None = None
        self.spectralon_spectrum: np.ndarray|None = None 
        self.save_dir:  str|None = None
        self.acqname: str|None = None
        self.saved_data_list: list = []
        self.main_oras_dir: str =  "/home/lumed/oras/data/" #"C:/Users/nerfi/oras/data/" #
        self.oras_status: str|None = None
        self.aec_exposure: str = ""
        
        #Tylenol peaks for x-axis calibration
        self.tylenol_peaks = np.array([390.9,  651.6,  797.2,  857.9, 1168.5, 1236.8,
                          1278.5, 1323.9, 1371.5, 1561.6, 1609, 1648.4])
        #Setup display
        self.display_raman = DataDisplayWidget()
        self.verticalLayout_raman = QtWidgets.QVBoxLayout()
        self.verticalLayout_raman.addWidget(self.display_raman.canvas)
        self.verticalLayout_raman.addWidget(self.display_raman.toolbar)
        self.RamanTab.setLayout(self.verticalLayout_raman)
        self.display_raman.set_axis_labels("Raman shift (cm$^{-1}$)", "a.u.")
        self.display_DRS = DataDisplayWidget()
        self.verticalLayout_DRS = QtWidgets.QVBoxLayout()
        self.verticalLayout_DRS.addWidget(self.display_DRS.canvas)
        self.verticalLayout_DRS.addWidget(self.display_DRS.toolbar)
        self.DRSTab.setLayout(self.verticalLayout_DRS)
        self.display_DRS.set_axis_labels("wavelength (nm)", "count")
        
        #Thread management
        self.threadpool = QThreadPool()
        logger.info(f"Widget initialization complete. Multithreading with max {self.threadpool.maxThreadCount()} threads.")
        
        # Setup ui 
        self.setup_default_ui()
        self.connect_ui_signals()
        #self.set_oras_status_loopworker() # oras status is continuously probed by a dedicated thread
        self.update_ui()
        
    def setup_default_ui(self):
        """
        Setup UI elements' default state and initial appearance
        """
        self.pushbtnFindLamp.setIcon(fugue.icon("magnifier-left"))
        self.pushbtnFindSpectro.setIcon(fugue.icon("magnifier-left"))
        self.checkBoxSave.setChecked(True)
        # Make the normalization check unavailable until a spectralon file is selected 
        self.groupBoxSpectralonNormalization.setChecked(False) 
        self.groupBoxSpectralonNormalization.setEnabled(False) 
        self.radioButtonSelectedSpectralon.setChecked(True)
        self.lineEditSetExposure.setReadOnly(True)
        
    def connect_ui_signals(self):
        """
        Connects UI signals for interactive elements
        """
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
        self.pushButtonMeasureDRS.clicked.connect(self.button_DRS_acquisition_worker)
        self.pushButtonMeasureRaman.clicked.connect(self.button_raman_acquisition_worker)
        self.pushButtonMeasureRamanDRS.clicked.connect(self.button_raman_DRS_acquisition_worker) # originaly self.button_raman_DRS_acquisition
        self.checkBoxSave.stateChanged.connect(self.update_ui)
        self.radioButtonSelectedSpectralon.toggled.connect(self.display_saved_data)
        self.radioButtonNativeSpectralon.toggled.connect(self.display_saved_data)
        self.comboBoxAcqName.currentTextChanged.connect(self.display_saved_data)  #lambda _: self.display_saved_data()
        self.comboBoxRamanProfile.currentTextChanged.connect(self.set_oras_profile) # automatically sets the new oras profile for raman acquisition when combobox selection is changed
        self.groupBoxSpectralonNormalization.clicked.connect(self.display_saved_data)
        
    def display_test_data(self):
        """Display randomly generated test data in both Raman and DRS plot widgets."""
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
        """Discover connected HL-2000 lamp devices and populate the lamp combo box."""
        try:
            lamps = self.lamp.find_lamp_device()
            logger.info("Found lamps : %s", lamps)
            self.comboBoxAvailableLamp.clear()
            for lamp in lamps:
                self.comboBoxAvailableLamp.addItem(lamp)
            self.pushbtnFindLamp.setEnabled(True)
            self.pushbtnFindLamp.setIcon(fugue.icon("magnifier-left"))
        except Exception as e:
            self.pushbtnFindLamp.setEnabled(True)
            self.pushbtnFindLamp.setIcon(fugue.icon("magnifier-left"))
            logger.error(e, exc_info=True)
        
    def find_lamp_worker(self):
        """Run lamp discovery in background worker thread."""
        logger.info("Looking for connected lamps")
        self.pushbtnFindLamp.setEnabled(False)
        self.pushbtnFindLamp.setIcon(fugue.icon("hourglass"))
        try:   
            worker = WorkerThread(self.find_lamp)
            self.threadpool.start(worker)
            worker.signals.finished.connect(self.update_ui)
        except Exception as e:
            logger.error(e, exc_info=True)
    
    def find_spectro(self):
        """Discover connected Maya spectrometers and populate the spectrometer combo box."""
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
            self.pushbtnFindLamp.setEnabled(True)
            self.pushbtnFindLamp.setIcon(fugue.icon("magnifier-left"))
            logger.error(e, exc_info=True)

    def find_spectro_worker(self):
        """Run spectrometer discovery in background worker thread."""
        logger.info("Looking for connected spectros") 
        self.pushbtnFindSpectro.setEnabled(False) 
        self.pushbtnFindSpectro.setIcon(fugue.icon("hourglass"))
        try:   
            worker = WorkerThread(self.find_spectro)
            self.threadpool.start(worker)
            worker.signals.finished.connect(self.update_ui)
        except Exception as e:
            logger.error(e, exc_info=True)
            
    def connect_lamp(self):
        """Connect to selected lamp and apply initial configurations."""
        try:
            self.lamp.comport = self.comboBoxAvailableLamp.currentText()
            print("self.lamp.comport:", self.lamp.comport)
            self.lamp.connect()
            logger.info("Connected lamp : %s", self.lamp.comport)
            self.set_initial_lamp_configurations()
        except Exception as e:
            logger.error(e, exc_info=True)

    def connect_lamp_worker(self):
        """Run lamp connection in background worker thread."""
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
        """Disconnect the lamp safely and reset its state."""
        try:
            self.set_initial_lamp_configurations()
            self.lamp.disconnect()
            logger.info("Disconnected lamp")
        except Exception as e:
            logger.error(e, exc_info=True)

    def disconnect_lamp_worker(self):
        """Run lamp disconnect in background worker thread."""
        logger.info("Disonnecting lamp")
        self.pushbtnDisconnectLamp.setEnabled(False)
        try:   
            worker = WorkerThread(self.disconnect_lamp)
            self.threadpool.start(worker)
            worker.signals.finished.connect(self.update_ui)
        except Exception as e:
            logger.error(e, exc_info=True)
    
    def connect_mayaspectro(self):
        """Connect to selected Maya spectrometer and configure exposure/intensity validators."""
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

                #Set the value type of min and max limits of the display settings
                wavelengths = self.mayaspectro.spectro.wavelengths()
                min_w, max_w =  np.min(wavelengths), np.max(wavelengths)
                DRS_wavelength_validator = QDoubleValidator()  
                DRS_wavelength_validator.setRange(min_w, max_w,2) # min wavelength, max wavelength, 2 for number of decimal places
                DRS_wavelength_validator.setNotation(QDoubleValidator.StandardNotation)
                self.lineEditMinXLim.setValidator(DRS_wavelength_validator)
                self.lineEditMaxXLim.setValidator(DRS_wavelength_validator)

                self.is_spectro_connected = True
            except Exception as e:
                logger.error(e, exc_info=True)
        else:
            logger.info("Maya spectrometer not available")
            print("Maya spectrometer not available")

    def connect_mayaspectro_worker(self):
        """Run spectrometer connection in background worker thread."""
        logger.info("Connecting spectrometer")
        self.pushbtnConnectSpectro.setEnabled(False)
        try:   
            worker = WorkerThread(self.connect_mayaspectro)
            self.threadpool.start(worker)
            worker.signals.finished.connect(self.update_ui)
        except Exception as e:
            logger.error(e, exc_info=True)

    def disconnect_mayaspectro(self):
        """Disconnect the Maya spectrometer."""
        try:
            self.mayaspectro.disconnect()
            logger.info("Disconnected spectrometer")
        except:
            if self.mayaspectro.is_spectro_available() == False:
                print("Maya spectrometer not available")
                logger.info("Maya spectrometer not available")
            raise Exception("No spectrometer available")
        
    def disconnect_mayaspectro_worker(self):
        """Run spectrometer disconnection in background worker thread."""
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
        """
        Lets the user select and load a tylenol x-axis calibration file. 
        Then calculates the x-axis using known tylenol peak positions
        """
        try:
            self.xaxis_file = QtWidgets.QFileDialog.getOpenFileName(self, caption = "Select a file to set xaxis", filter=("Text files (*.joblib)"))[0] #CHANGE FILTER PARAMETER
            print('self.xaxis_files: ', self.xaxis_file, 'type: ', type(self.xaxis_file))
            with open(self.xaxis_file, 'rb') as f:
                self.xaxis_data = joblib.load(f)
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
            self.display_raman.update_plot(self.xaxis_raman, raman_tyl.reshape(raman_tyl.shape[0],1), labels = ["tylenol"])
        except Exception as e: 
            if type(self.xaxis_file) is str and (len(self.xaxis_file) == 0): # If True, file selection was canceled
                logger.info("Canceled: No Raman xaxis file was selected")
            logger.error(e, exc_info=True)
        finally:
            self.update_ui()
            
    def select_yaxis(self) -> None:
        """
        Lets the user select and load a y-axis calibration file. 
        The instrument response function (IRF) is then calculated.
        """

        try:
            if self.xaxis_raman is None:
                logger.info("Canceled y axis selection: No Raman x axis file was selected before selecting y axis file")
                raise Exception("No yaxis file selected. Select a yaxis file first")
            self.yaxis_file = QtWidgets.QFileDialog.getOpenFileName(self, caption = "Select a file to set y axis", filter=("Text files (*.joblib)"))[0]
            print('self.yaxis_files: ', self.yaxis_file, 'type: ', type(self.yaxis_file))
            with open(self.yaxis_file, 'rb') as f:
                self.yaxis_data = joblib.load(f)
            url = QUrl.fromLocalFile(self.yaxis_file)
            print('url: ', url )
            self.lineEditYaxisFile.setText(url.fileName()) # Display the selected yaxis file name
            logger.info("Selected y axis file: %s", url.fileName())
            raw_irf_spectrum = self.yaxis_data['accumulations'] #'raman_data'
            print("raw_spectrum shape:", raw_irf_spectrum.shape)
            bkg = self.yaxis_data['background']  #'raman_background'
            print("bkg shape:", bkg.shape)
            raw_mean = np.mean(raw_irf_spectrum - bkg, axis=0) 
            self.irf_raman = la.get_correction_curve(self.xaxis_raman, raw_mean) # get instrument response function (IRF) from xaxis (cm-1) and measured nist (raw_mean)
            self.irf_raman = self.irf_raman.reshape(self.irf_raman.shape[0],1)
            self.display_DRS.update_plot(self.xaxis_raman, self.irf_raman, labels = ["IRF"])
        except Exception as e: 
            if type(self.yaxis_file) is str and (len(self.yaxis_file) == 0): # If True, file selection was canceled
                logger.info("Canceled: No Raman y axis file was selected")
            logger.error(e, exc_info=True)
        finally:
            self.update_ui()

    def select_spectralon(self) -> None:
        """Lets the user select and load a file containing DRS spectra of a spectralon calibration standard."""
        try:
            self.spectralon_file = QtWidgets.QFileDialog.getOpenFileName(self, caption = "Select a spectralon file", filter=("Joblib files (*.joblib)"))[0] #CHANGE FILTER PARAMETER
            print('self.spectralon_file: ', self.spectralon_file, 'type: ', type(self.spectralon_file))
            with open(self.spectralon_file, 'rb') as f:
                self.spectralon_data = joblib.load(f)
                print('Spectralon data:', self.spectralon_data)
            url = QUrl.fromLocalFile(self.spectralon_file)
            print('url: ', url )
            self.lineEditSpectralonFile.setText(url.fileName()) # Display the selected spectralon file name
            self.groupBoxSpectralonNormalization.setEnabled(True) # Make the normalization check available
            logger.info("Selected spectralon file: %s", url.fileName())
            self.spectralon_spectrum = np.mean(self.spectralon_data['drs_data'], axis=1) - self.spectralon_data['drs_background']
            print("spectralon data keys:", self.spectralon_data.keys(), self.spectralon_spectrum)
        except Exception as e: 
            if type(self.spectralon_file) is str and (len(self.spectralon_file) == 0): # If True, file selection was canceled
                logger.info("Canceled: No Spectralon file was selected")
            logger.error(e, exc_info=True)

    def select_save_folder_dir(self) -> None:
        """Opens folder browser to set a directory for saving acquisition files"""
        print("SELECTING FOLDER")
        self.save_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Directory to save data")
        print("Save directory:", self.save_dir)
        self.labelSaveDirectory.setText(self.save_dir) #Display the selected directory
        print("Getting saved acquisitions data")
        self.saved_data_list = self.get_saved_acquisitions_data(directory=self.save_dir)
        print("Got saved acquisitions data")
        self.construct_acq_name_combobox(data_list=self.saved_data_list)
        self.update_ui()

    def save_acquisition(self, directory, acq_name, acq_comment, 
                         DRS_background = None, xaxis_DRS = None, DRS_data = None, 
                         DRS_spectralon = None, DRS_exposure = None, raman_background = None,  
                         xaxis_raman = None, raman_accumulations = None, raman_exposure = None) -> dict:
        """
        Structures data into a dictionary and optionally saves to a .joblib file.
        
        Args:
            directory (str): Directory where joblib acquisition file is to be saved.
            acq_name (str): Acquisition name, used as file name.
            acq_comment (str): Acquisition comment.
            DRS_background (np.ndarray, optional): DRS spectrometer's background measurement.
            xaxis_DRS (np.ndarray, optional): DRS measurement x-axis, in wavelengths (nm).
            DRS_data (np.ndarray, optional): DRS measurement y-axis accumulations in photon counts.
            DRS_spectralon (np.ndarray, optional): Loaded spectralon calibration standard measurement.
            DRS_exposure (float, optional): Exposure time of a single DRS accumulation.
            raman_background (np.ndarray, optional): ORAS Raman background measurement.
            xaxis_raman (np.ndarray, optional): Currently loaded raman x-axis.
            raman_accumulations (np.ndarray, optional): ORAS measured Raman accumulations.
            raman_exposure (float, optional): Exposure time of a single raman accumulation.

        Returns:
            dict: Dictionary of measured data and currently loaded calibration data.

        """
        saved_data =  {}
        saved_data['acquisition_name'] = acq_name
        saved_data['comment'] = acq_comment
        saved_data['drs_background'] = DRS_background
        saved_data['drs_spectralon'] = DRS_spectralon
        saved_data['xaxis_DRS'] = xaxis_DRS
        saved_data['drs_data'] = DRS_data
        saved_data['drs_exposure'] = DRS_exposure
        saved_data['raman_background'] = raman_background
        saved_data['xaxis_raman'] = xaxis_raman
        saved_data['raman_accumulations'] = raman_accumulations
        saved_data['raman_exposure'] = raman_exposure
        saved_data['yaxis_raman'] = self.irf_raman
        self.saved_data_list.append(saved_data) #add newer data to list of saved data to be displayed on ui
        # Save on local memory if requested by user from ui checkbox
        if (self.checkBoxSave.isChecked() == True) and (self.save_dir is not None):
            filename = acq_name.replace(" ", "_")+".joblib" #make name into snakecase
            with open(directory+'/'+filename, 'w') as f:# Save data in .joblib file
                print(f"Saving at {directory}\\{filename}")
                joblib.dump(saved_data, directory +'/'+ filename)
            logger.info(f"Saved acquisition at {directory}\\{filename}")
            print("finished saving")
        return saved_data

    def update_acq_combobox(self, current_data: dict) -> None:
        """
        Insert acquisition data into the combo box and set as current selection.

        Args:
            acq_name (str): Acquisition name used as file name
            current_data (dict): Data to be inserted into combo box

        Returns:
            None
        """
        combobox_slot_name = current_data['acquisition_name']+': '+current_data['comment']
        self.comboBoxAcqName.insertItem(0, combobox_slot_name, current_data)
        self.comboBoxAcqName.setCurrentIndex(0)

    def display_saved_data(self):
        """Plot most recenly measured or currently selected acquisition data on DRS and Raman display widgets."""
        try:
            current_data = self.comboBoxAcqName.currentData()
            self.textEditComment.setPlainText(current_data["comment"]) #access the data linked to the combobox item
            self.lineEditSetExposure.setText(str(round(current_data["drs_exposure"]))) #Display the saved DRS exposure time used for acquisition
            print("-----------DISPLAYING DATA-----------")
            # print("current data:", current_data)
            # print("name:", current_data['acquisition_name'])
            # print("DRS:", current_data["drs_data"])
            # print("RAMAN:", current_data["raman_accumulations"])
            if current_data["drs_data"] is not None: #if current_data["drs_data"] is not None
                try:
                    DRS_background = current_data['drs_background']
                    xaxis_DRS = current_data['xaxis_DRS']
                    labels_DRS = []
                    try:
                        x_lims = (float(self.lineEditMinXLim.text()), float(self.lineEditMaxXLim.text()))
                    except Exception as e:
                        logger.warning(f"Given x axis limits for DRS plot may not be a float: {e}")
                        x_lims = None
                    if self.groupBoxSpectralonNormalization.isChecked() : # plot the normalized DRS data
                        try:
                            if self.radioButtonNativeSpectralon.isChecked() and (current_data['drs_spectralon'] is not None):
                                normalized_DRS = (current_data['drs_data'] - current_data['drs_background'])/current_data['drs_spectralon'] #Use the current joblib file's spectralon data
                            elif self.radioButtonSelectedSpectralon.isChecked() and self.spectralon_spectrum is not None:
                                print("HEEEEEEEEEEEEEEERE self.spectralon_spectrum:", self.spectralon_spectrum.shape)
                                normalized_DRS = (current_data['drs_data'] - current_data['drs_background'][:, np.newaxis])/self.spectralon_spectrum[:, np.newaxis]  #Use the currently selected spectralon joblib file data
                        except Exception as e:
                            print("Error: No native spectralon spectrum in this file using loaded spectralon - ", e)
                            normalized_DRS = (current_data['drs_data'] - current_data['drs_background'][:, np.newaxis])/self.spectralon_spectrum[:, np.newaxis]  #Use the currently selected spectralon joblib file data
                        finally:
                            mean_normalized_DRS = np.mean(normalized_DRS, axis=1)
                            DRS_spectrum = np.hstack((normalized_DRS, np.atleast_2d(mean_normalized_DRS).T))
                            for i in range(DRS_spectrum.shape[1]):
                                if i == 1:
                                    labels_DRS.append('first acquisition')
                                elif i == DRS_spectrum.shape[1]-2:
                                    labels_DRS.append(f"last acquisition")
                                elif i == DRS_spectrum.shape[1]-1:
                                    labels_DRS.append('mean')
                    else:
                        DRS_spectrum = np.hstack((np.atleast_2d(DRS_background).T, current_data['drs_data']))
                        for i in range(DRS_spectrum.shape[1]):
                            if i == 0:
                                labels_DRS.append('background')
                            elif i == 1:
                                labels_DRS.append('first acquisition')
                            elif i == DRS_spectrum.shape[1]-1:
                                labels_DRS.append(f"last acquisition")
                    self.display_DRS.update_plot(xaxis_DRS, DRS_spectrum, labels_DRS, x_lims = x_lims)
                except Exception as e:
                    logger.warning(f"DRS was not plotted {e}")
                    self.display_DRS.clear() # if no DRS data to be displayed, clear axis
            else:
                print("CLEARING DRS DISPLAY")
                self.display_DRS.clear() # if no DRS data to be displayed, clear axis

            if current_data["raman_accumulations"] is not None:
                raman_spectrum = (current_data['raman_accumulations'] - current_data['raman_background'])
                raman_background = current_data['raman_background']
                xaxis_raman = current_data['xaxis_raman'] 
                raman_spectrum = np.hstack((raman_background, raman_spectrum))
                labels_raman = []
                for i in range(raman_spectrum.shape[1]):
                        if i == 0:
                            labels_raman.append("background")
                        elif i == 1:
                            labels_raman.append('first acquisition')
                        elif i == raman_spectrum.shape[1]-1:
                            labels_raman.append(f"last acquisition")
                if (current_data['xaxis_raman'] is not None) and (current_data['yaxis_raman'] is not None):
                    #prioritize displaying data with the files native x axis and y axis calibration
                    irf_raman = current_data['yaxis_raman']
                    raman_corr_irf = raman_spectrum/irf_raman
                    self.display_raman.update_plot(current_data['xaxis_raman'], raman_corr_irf, labels = labels_raman)
                elif (self.xaxis_raman is not None) and (self.irf_raman is not None):
                    #If no native x and y axis data in the current file, plot with currently loaded calibration files
                    raman_corr_irf = raman_spectrum/self.irf_raman
                    self.display_raman.update_plot(xaxis_raman, raman_corr_irf, labels = labels_raman)
                elif current_data['xaxis_raman'] is not None:
                    #if only the x axis calibration data is native to the data file, use it 
                    self.display_raman.set_axis_labels("Raman shift (cm$^{-1}$)", "count")
                    self.display_raman.update_plot(xaxis_raman, raman_spectrum, labels = labels_raman)
                else:
                    # else just plot the data with camera pixels as the x axis
                    self.display_raman.set_axis_labels("camera pixel", "a.u.")
                    x_axis_camera_px = np.arange(raman_spectrum.shape[0]) # camera pixels
                    self.display_raman.update_plot(x_axis_camera_px, raman_spectrum, labels = labels_raman)
            else:
                print("CLEARING RAMAN DISPLAY")
                self.display_raman.clear() # if no raman data to be displayed, clear axis     
        except Exception as e:
            logger.error(e, exc_info=True) 
    
    def construct_raman_profile_combobox(self):
        """Populate Raman profile combo box with available ORAS profiles."""
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
        """Populate acquisition name combo bo10x with data in folder selected by user."""
        try:
            if data_list is None:
                data_list = self.saved_data_list
            def data_list_sort(data):
                print("index:", int(data['acquisition_name'][data['acquisition_name'].index('_')+1:]))
                return int(data['acquisition_name'][data['acquisition_name'].index('_')+1:])
            data_list = sorted(data_list, key = data_list_sort)
            print("Before self.comboBoxAcqName.currentIndex(): ",self.comboBoxAcqName.currentIndex(), 'self.comboBoxAcqName.currentText():', self.comboBoxAcqName.currentText())
            self.comboBoxAcqName.blockSignals(True)
            self.comboBoxAcqName.clear()
            print("Constructing combobox...")
            for data in data_list:
                try:
                    print("acquisition name: in combobox:", data['acquisition_name'], data_list_sort(data))
                    self.comboBoxAcqName.addItem(data['acquisition_name']+': '+data['comment'], data) # the data is linked to each combobox space
                except Exception as e:
                    logger.error(e, exc_info=True) 
                     
            self.comboBoxAcqName.blockSignals(False)
            self.comboBoxAcqName.setCurrentIndex(0) # Select the first index when combobox is constructed #########################################################
            print("After self.comboBoxAcqName.currentIndex(): ",self.comboBoxAcqName.currentIndex(), 'self.comboBoxAcqName.currentText():', self.comboBoxAcqName.currentText())
        except Exception as e:
            logger.error(e, exc_info=True) 
        self.update_ui()

    def get_saved_acquisitions_data(self, directory: str | None = None)->list:
        """
        Load all joblib acquisition files from specified directory.

        Args:
            directory (str): User selected directory of folder containing acquisitions files

        Returns:
            list: List of data in the selected folder
        """
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
            print("data_list:", data_list)
            return data_list
        except Exception as e:
            logger.error(e, exc_info=True) 

    def get_acquisition_name(self) -> str:
        """Get acquisition name from UI text field, formatted as snake_case. An index is added to the measurement"""
        self.acqname = self.lineEditAcqName.text().replace(" ", "_")
        all_combobox_acq_names = [self.comboBoxAcqName.itemData(i)['acquisition_name'] for i in range(self.comboBoxAcqName.count())]
        new_acq_idx = 0
        for combobox_acq_name in all_combobox_acq_names:
            if self.acqname in combobox_acq_name:
                parts = combobox_acq_name.split('_')
                number_index_str = parts[-1]
                if number_index_str.isdigit():
                    current_idx = int(number_index_str)
                    if new_acq_idx <= current_idx:
                        new_acq_idx = current_idx+1
        self.acqname = self.acqname + f"_{new_acq_idx}"

        return self.acqname
    
    def get_acquisition_comment(self) -> str:
        """Get acquisition comment from UI text edit field."""
        comment = self.textEditComment.toPlainText()
        return comment

    def get_DRS_acq_params(self):
        """Get all DRS acquisition parameters from UI fields as tuple.

        Returns:
            tuple(float, float, float, float, int, int): Tuple containing retreived parameters of DRS acquisitions
                * index 0 (float): lower value to determine the exposure vs max count line
                * index 1 (float): upper value to determine the exposure vs max count line
                * index 2 (float): minimum possible value for exposure time
                * index 3 (float): maximum possible value for exposure time
                * index 4 (int): the target max count of a single accumulation
                * index 5 (int): The number of accumulations in a single acquisition
        """
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
        """
        Get list of available ORAS acquisition profiles, with fallback default list.

        Returns:
            list: List of raman profiles available in ORAS
        """
        try:
            self.raman_profiles = ext.get_profiles()
            print(f"Got raman profiles: {type(self.raman_profiles[0])}")
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
    
    def get_latest_raman_files(self):
        """Retrieve most recently generated or modified joblib and toml files from ORAS data directory.
        Returns:
            tuple(str, str): Most recently generated joblib and toml files by ORAS after Raman acquisition
                * index 0 (str): joblib file containing acquisition data
                * index 1 (str): toml file containing metadata
        """
        try:
            print("in get latest raman files")
            logger.info(f"Looking into following folder for Raman data: {self.main_oras_dir}")
            walk = os.walk(self.main_oras_dir) #top down walk of directory content in tuples of (root,dirs,files)
            data_paths = []
            print("walk:", walk)
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
        except Exception as e:
            logger.error(f"error while getting latest generated file: {e}")
        return joblib_file, toml_file
    
    def get_latest_raman_data(self)->tuple:
        """Extract Raman spectra data from latest ORAS output files.
        Returns:
            out(tuple(np.ndarray, np.ndarray, np.ndarray, np.ndarray)): Data extracted from most recent Raman acquisition
                * index 0 (np.ndarray): Raman x-axis
                * index 1 (np.ndarray): Raman background
                * index 2 (np.ndarray): Raman accumulations
                * index 3 (np.ndarray): Exposure time used for every raman accumulation
        """
        joblib_file, toml_file = self.get_latest_raman_files()
        with open(joblib_file, 'rb') as joblib_f, open(toml_file, 'rb') as toml_f:
            data_file = joblib.load(joblib_f)
            toml_dict = tomli.load(toml_f)
        raman_xaxis= data_file['xaxis'].T
        raman_bkg = data_file['background'].T
        raman_accumulations = data_file['accumulations'].T # Transposed to fit format of DRS acquisitions
        raman_exposure = toml_dict['acquisition_profile']['exposure_time'] # ms
        return raman_xaxis, raman_bkg, raman_accumulations, raman_exposure
    
    def AEC_extrapolation(self, shutter_position: int, min_aec_exp: float, max_aec_exp: float, min_acq_exp: float, max_acq_exp: float, target_count: int) -> float:
        """
        This automatic exposure control algorithm measures two values of max count with their associated user determined 
        exposure times. It then extrapolates or interpolates, with a linear function, the exposure that maximizes dynamic 
        range while being within max_acq_exp and min_acq_exp.
        
        Args:
            shutter_position (int): Halogen lamp shutter position (between 0 to approx 370)
            min_aec_exp (float): lower value to determine the exposure vs max count line
            max_aec_exp (float): upper value to determine the exposure vs max count line
            min_acq_exp (float): minimum possible value for exposure time
            max_acq_exp (float): maximum possible value for exposure time
            target_count (int): the target max count of a single accumulation

        Returns:
            out (float): optimal exposure in ms
        """
        try:
            hardware_min_exposure, hardware_max_exposure = self.mayaspectro.get_exposure_time_lims() #minimal exposure time in ms (/1000 to convert from micro seconds to ms)
            hardware_min_exposure +=1
            hardware_max_count = self.mayaspectro.get_max_intensity()
            if max_acq_exp > hardware_max_exposure:
                max_acq_exp = hardware_max_exposure
                logger.warning("The given maximum exposure is higher then the spectrometer's maximum,\nMax exposure set to hardware maximum: %f ms", hardware_max_exposure)            
            elif max_acq_exp <= hardware_min_exposure:
                logger.error("The given maximum exposure is lower then the spectrometer's minimum of %f ms.", hardware_min_exposure)
                raise ValueError("The given maximum exposure is lower then the spectrometer's minimum of %f ms.", hardware_min_exposure)
            if (min_acq_exp <= hardware_min_exposure):
                min_acq_exp = hardware_min_exposure
                logger.warning("The given minimum exposure is lower then the spectrometer's minimum.\nMin exposure set to hardware minimum: %f ms", hardware_min_exposure)
            elif (min_acq_exp > hardware_max_exposure):
                logger.error("Minimimum exposure exceeds hardware maximum of %f ms", hardware_max_exposure)
                raise ValueError("Minimimum exposure exceeds hardware maximum of %f ms", hardware_max_exposure)
            if target_count > hardware_max_count:
                target_count = hardware_max_count
                logger.warning("The given maximum count is higher than the maximum count measurable by the spectrometer.\nThe target count will be set to the hardware's highest measurable count: %f", hardware_max_count)
            if min_aec_exp >= max_aec_exp:
                logger.error("Minimimum aec exposure exceeds maximum aec exposure. Re-enter values")
                raise ValueError("Minimimum aec exposure exceeds maximum aec exposure. Re-enter values")
        except ValueError as e:
            logger.error("AEC failed: %s", str(e))
            self.disable_lamp() 
            return None
        
        exposures = np.array([min_aec_exp, max_aec_exp]) # ms 
        
        self.lamp.set_shutter_position(shutter_position)
        self.enable_lamp() #Start illumination
        print(f'Exposures used for count determination: min exposure = {exposures[0]} ms, max exposure = {exposures[1]} ms')
        logger.info(f"Taking acquisition with given AEC exposures of {exposures[0]} and {exposures[1]} ms")
        count_min_exposure = self.mayaspectro.spectrum_acquisition(exposures[0])[1]
        count_max_exposure = self.mayaspectro.spectrum_acquisition(exposures[1])[1]
    
        max_counts = np.array([np.max(count_min_exposure), np.max(count_max_exposure)])
        print(f"Determined counts = {max_counts[0]}, {max_counts[1]}")
        while max_counts[1] >= hardware_max_count:
            print("-------in while loop-------")
            print(f"max counts is: {max_counts}")
            print(f"initial exposures: {exposures}")
            if (max_counts[0] >= hardware_max_count) and max_counts[1] >= hardware_max_count:
                exposures = exposures - 0.3*exposures # If one of the higher exposure time leads to a max count equal to the hardware max, reduce it by 30%
                if exposures[0] <= hardware_min_exposure:
                    exposures[0] = hardware_min_exposure # set the min exposure to the hardware minimum but not the max exposure
                if exposures[1] <= hardware_min_exposure:
                    exposures[1] = 1.3*hardware_min_exposure # set the min exposure to the hardware minimum but not the max exposure
                    break
                max_counts = np.array([np.max(self.mayaspectro.spectrum_acquisition(exposures[0])[1]), 
                                    np.max(self.mayaspectro.spectrum_acquisition(exposures[1])[1])])
            elif max_counts[1] >= hardware_max_count:
                exposures[1] = 0.7*exposures[1]
                if exposures[1] <= hardware_min_exposure:
                    exposures[1] = 1.3*exposures[0] # set the min exposure to a value higher than the minimum exposure 
                    max_counts[1] = np.max(self.mayaspectro.spectrum_acquisition(exposures[1])[1])
                max_counts[1] = np.max(self.mayaspectro.spectrum_acquisition(exposures[1])[1])
            print(f"new exposures: {exposures}")
        
        #calculate parameters a*(exposure_time)+b = target count 
        a = (max_counts[1]-max_counts[0])/(exposures[1]-exposures[0])
        b = max_counts[1]-(a*exposures[1])
        optimal_exp = (target_count - b)/a
        logger.info(f"Found optimal exposure to be {optimal_exp} ms")
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
            logger.warning("The optimal exposure is lower than the minimum set by user. Exposure set to user minimum: %f ms", min_acq_exp)

        opt_exp_measured_count = self.mayaspectro.spectrum_acquisition(optimal_exp)[1]

        real_max_count = np.max(opt_exp_measured_count)
        #self.disable_lamp() #Stop illumination
        logger.info(f"-------AEC DONE-------")
        logger.info(f"Final AEC values: exposures = {exposures} ms with max counts = {max_counts}")
        logger.info(f"AEC extrapolation parameters: a = {a}, b = {b}")
        logger.info(f"Target count of {target_count} used to find optimal exposure: {optimal_exp} ms, with max count of {real_max_count}")
        return optimal_exp

    def DRS_background_acquisition(self, exposure): 
        """Measure background spectrum at specified exposure time with lamp disabled."""
        self.disable_lamp() # Stop illumination
        wavelengths, bkg_intensity = self.mayaspectro.spectrum_acquisition(exposure)
        return wavelengths, bkg_intensity

    def DRS_acquisition(self, progress_callback):
        """
        Perform complete DRS acquisition sequence with automatic exposure control and multiple accumulations.
None
        This method retrieves user-configured DRS parameters, calculates optimal exposure time via AEC,
        measures a background spectrum, then performs multiple accumulations with the lamp enabled.

        Args:
            progress_callback (PyQt5.QtCore.pyqtSignal): Signal to emit progress updates during accumulation loop.
                Emits messages of format "DRS acquisition {i-th accumulation}/{N accumulations}".

        Returns:
            tuple: A tuple containing DRS acquisition results.
                * index 0 (np.ndarray): Background spectrum measured at optimal exposure.
                * index 1 (np.ndarray): Wavelength x-axis from spectrometer.
                * index 2 (np.ndarray): DRS data accumulations (shape: wavelengths × num_accumulations).
                * index 3 (float): Exposure time determined by AEC algorithm (ms).
                
                Returns None if DRS acquisition parameters cannot be retrieved from UI.
        """
        # If some AEC parameters are missing, nothing is returned
        print("DRS acquisition parameters:", self.get_DRS_acq_params())
        if self.get_DRS_acq_params() == None:
            return None
        try:
            # Get optimal exposure
            min_aec_exp, max_aec_exp, min_acq_exp, max_acq_exp, target_count, N_accumulations = self.get_DRS_acq_params()
            shutter_position = 400 #value of max shutter opening to make sure that it is completely open
            aec_exposure = self.AEC_extrapolation(shutter_position, min_aec_exp, max_aec_exp, min_acq_exp, max_acq_exp, target_count)    
            print("aec_exposure", aec_exposure, "ms") 
            if aec_exposure == None:
                raise Exception("AEC exposure could not be found")
        except Exception as e:
            self.disable_lamp()
            return None
        self.aec_exposure = str(int(aec_exposure))
        
        # Proceed with the measurement including background signal substraction
        xaxis_DRS, DRS_background = self.DRS_background_acquisition(aec_exposure) #background to be substracted from normal acquisition
        self.enable_lamp()
        tt.sleep(0.7)# wait for lamp light intensity to stabilize 0.7s seems to be optimal
        for i in range(N_accumulations):
            progress_callback.emit(f"DRS acquisition {i+1}/{N_accumulations}")
            xaxis_DRS, intensity = self.mayaspectro.spectrum_acquisition(aec_exposure)
            if i == 0:
                DRS_data = np.atleast_2d(intensity-DRS_background).T
            else:
                DRS_data = np.hstack((DRS_data, np.atleast_2d(intensity-DRS_background).T))
        print(f"DRS_data.shape: {DRS_data.shape}")
        self.disable_lamp()
        return DRS_background, xaxis_DRS, DRS_data, aec_exposure
        
    def button_DRS_acquisition(self, progress_callback):
        """
        Execute DRS acquisition and save acquired data when triggered by UI button.
            Args:
                progress_callback (PyQt5.QtCore.pyqtSignal): Signal to emit progress updates during accumulation loop.
                Emits messages of format "DRS acquisition {i-th accumulation}/{N accumulations}".
            Returns:
                tuple(str, dict): On success returns data to update ui for data display and naming
                    * index 0: Acquisition name 
                    * index 1: Saved data
        """
        try:    
            logger.info("Started DRS acquisition") 
            acq_name = self.get_acquisition_name()
            acq_comment = self.get_acquisition_comment()
            print("before acquisition")
            drs_data  = self.DRS_acquisition(progress_callback) 
            if drs_data == None:
                raise Exception(f"DRS_acquisition returned {drs_data}") 
            DRS_background, xaxis_DRS, DRS_data, DRS_exposure = drs_data
            saved_data = self.save_acquisition(self.save_dir, acq_name, acq_comment, 
                                                DRS_spectralon = self.spectralon_spectrum, 
                                                DRS_background = DRS_background, 
                                                xaxis_DRS = xaxis_DRS, 
                                                DRS_data = DRS_data, 
                                                DRS_exposure = DRS_exposure)
            logger.info("DRS acquisition done")
            self.is_measuring = False
            return saved_data
        except Exception as e:
            self.is_measuring = False
            logger.error(f"Error during DRS acquisition: {e}")
        
    def button_DRS_acquisition_worker(self):
        """Run DRS acquisition in background worker and update UI"""
        try:
            self.is_measuring = True
            self.pushButtonMeasureDRS.setText("Measuring...")
            self.update_ui()   
            worker = WorkerThread(self.button_DRS_acquisition, "progress_callback")
            worker.signals.result.connect(lambda r: self.update_acq_combobox(r) if r is not None else None)
            worker.signals.finished.connect(self.update_ui)
            worker.signals.progress.connect(logger.info) # Log accumulation number
            self.threadpool.start(worker)
        except Exception as e:
            logger.error(e, exc_info=True)
            self.is_measuring = False
        finally:
            self.update_ui()

    def raman_acquisition(self, acq_name, acq_comment) -> None:
        """Trigger ORAS to run a Raman acquisition with the provided name and comment."""
        try:
            ext.set_file_name(acq_name) #Sets the file name in ORAS
            ext.set_comment(acq_comment) #Sets the comment in ORAS
            ext.start_acquisition(blocking = True) #Tells ORAS to start acquisition wihile blocking the thread it is running on until all acquisitions are returned
        except Exception as e:
            logger.error(f"Error during Raman acquisition: {e}")
            
    def button_raman_acquisition(self):
        """
        Run a Raman acquisition (via ORAS), fetch the latest ORAS files and save the result.

        Returns:
            tuple(str, dict): On success returns data to update ui for data display and naming
                    * index 0: Acquisition name 
                    * index 1: Saved data
        """
        try:
            logger.info("Started Raman acquisition")
            acq_name = self.get_acquisition_name()
            acq_name_parts = acq_name.split("_")
            acq_name_idx = acq_name_parts[-1]
            acq_name_idx_position = acq_name.find(acq_name_idx)
            oras_acq_name = acq_name[:acq_name_idx_position-1]
            acq_comment = self.get_acquisition_comment()
            self.raman_acquisition(oras_acq_name , acq_comment)
            raman_xaxis, raman_bkg, raman_accumulations, raman_exposure = self.get_latest_raman_data()
            if self.xaxis_raman is not None:
                raman_xaxis = self.xaxis_raman
            saved_data = self.save_acquisition(self.save_dir, acq_name, acq_comment,
                                            raman_background = raman_bkg,  xaxis_raman = raman_xaxis, 
                                            raman_accumulations = raman_accumulations, raman_exposure=raman_exposure)
            logger.info(f"Raman acquisition done with shape {raman_accumulations.shape}")
            self.is_measuring = False
            return saved_data
        except Exception as e:
            logger.error(f"Error during Raman acquisition: {e}")
            self.is_measuring = False

    def button_raman_acquisition_worker(self):
        """ Run Raman acquisition in a background worker and update UI state."""
        try:
            self.is_measuring = True
            self.pushButtonMeasureRaman.setText("Measuring...")
            self.update_ui()   
            worker = WorkerThread(self.button_raman_acquisition)
            worker.signals.result.connect(lambda r: self.update_acq_combobox(r) if r is not None else None)
            worker.signals.finished.connect(self.update_ui)
            self.threadpool.start(worker)
        except Exception as e:
            logger.error(e, exc_info=True)
        finally:
            self.update_ui()   

    def button_raman_DRS_acquisition(self, progress_callback):
        """
        When "Raman/DRS" button is pressed.
        Perform a DRS acquisition followed immediately by a Raman acquisition and save combined data. 
        Args:
            progress_callback (PyQt5.QtCore.pyqtSignal): Signal used to report progress during DRS accumulations.

        Returns:
            tuple(str, dict): On success returns data to update ui for data display and naming
                    * index 0: Acquisition name 
                    * index 1: Saved data
        """
        try:
            logger.info("Started Raman/DRS acquisition")
            acq_name = self.get_acquisition_name()
            acq_name_parts = acq_name.split("_")
            acq_name_idx = acq_name_parts[-1]
            acq_name_idx_position = acq_name.find(acq_name_idx)
            oras_acq_name = acq_name[:acq_name_idx_position-1]
            acq_comment = self.get_acquisition_comment()
            print("Starting DRS acquisition")
            DRS_background, xaxis_DRS, DRS_data, DRS_exposure  = self.DRS_acquisition(progress_callback) # DRS acquisition
            print("Ended DRS acquisition")
            print("Starting Raman acquisition")
            self.raman_acquisition(oras_acq_name, acq_comment) #Raman acquisition and [:-2] to not give the name index to oras
            raman_xaxis, raman_bkg, raman_accumulations, raman_exposure = self.get_latest_raman_data() # Get data from the file generated by ORAS
            print("Ended Raman acquisition")
            saved_data = self.save_acquisition(self.save_dir, acq_name, acq_comment,
                                                DRS_spectralon = self.spectralon_spectrum, 
                                                DRS_background = DRS_background, 
                                                xaxis_DRS = xaxis_DRS,
                                                DRS_data = DRS_data, 
                                                DRS_exposure = DRS_exposure,
                                                raman_background = raman_bkg,  
                                                xaxis_raman = raman_xaxis, 
                                                raman_accumulations = raman_accumulations, 
                                                raman_exposure = raman_exposure) # Save in data file
            logger.info("Raman/DRS acquisition done")
            self.is_measuring = False
            return saved_data
        except Exception as e:
             self.is_measuring = False
             logger.error(f"Error during Raman/DRS acquisition: {e}")
    
    def button_raman_DRS_acquisition_worker(self):
        """Run the combined Raman+DRS acquisition in a background worker and update UI state."""
        try:
            self.is_measuring = True
            self.pushButtonMeasureRamanDRS.setText("Measuring...")
            self.update_ui()   
            worker = WorkerThread(self.button_raman_DRS_acquisition, "progress_callback")
            worker.signals.result.connect(lambda r: self.update_acq_combobox(r) if r is not None else None)
            worker.signals.finished.connect(self.update_ui)
            worker.signals.progress.connect(logger.info)
            self.threadpool.start(worker)
        except Exception as e:
            logger.error(e, exc_info=True)
            self.is_measuring = False
        finally:
            self.update_ui()

    def enable_lamp(self):
        """Enable lamp output and update internal state tracking."""
        logger.info("Enabling lamp")
        self.lamp.set_enable(True)
        self.last_enabled_state = True

    def disable_lamp(self):
        """Disable lamp output with safety timeout and update internal state tracking."""
        logger.info("Disabling lamp")
        self.lamp.set_enable(False)
        tt.sleep(0.5) #wait for lamp to turn off
        self.last_enabled_state = False

    def set_initial_lamp_configurations(self):
        """Apply initial lamp settings: disable output and position shutter to home."""
        if self.lamp_info.is_connected:
            logger.info("Setting initial lamp configurations")
            logger.info("Setting lamp to disable")
            self.lamp.set_enable(False)
            logger.info("Setting lamp shutter position to a closed position")
            self.lamp.set_shutter_position(-400)
            logger.info("Setting lamp shutter closed position as home position")
            self.lamp.set_home_position()
        
    def set_labels_connected(self, lamp_isconnected: bool, spectro_isconnected: bool) -> None:
        """Update UI labels and colors for lamp and spectrometer connection status."""
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
        """
        Update UI label and color for lamp enable/disable status.
        
        Args:
            isenabled (bool): Whether the lamp bulb is currently enabled.
        """
        if isenabled:
            self.labelLampConnected.setText("ENABLED") 
            self.labelLampConnected.setStyleSheet("color:red")
        else:
            self.labelLampConnected.setText("Disabled")
            self.labelLampConnected.setStyleSheet("color:green")
    
    def set_oras_profile(self):
        """Set ORAS acquisition profile to currently selected profile in combo box."""
        try:
            None
            #logger.info(f"Setting oras profile to {self.comboBoxRamanProfile.currentText()}")
            #set_oras_profile_message = ext.set_profile(self.comboBoxRamanProfile.currentIndex())
            #if type(set_oras_profile_message) == ConnectionRefusedError:
                #raise ConnectionRefusedError(set_oras_profile_message)
        except Exception as e:
            #logger.error(e, exc_info=True)
            None

    def set_oras_status_loopworker(self):
        """Start background worker thread for continuous ORAS status polling."""
        logger.info("Setting loop thread for oras status polling")
        try:   
            initial_oras_status = ext.get_system_status()
            # self.oras_status = initial_oras_status
            print("initial oras status: ", initial_oras_status)
            self.oras_loop_worker = LoopWorkerThread(ext.get_system_status)  # create a long-running LoopWorkerThread instance, test method: self.test_oras_status_change
            print("after loop worker:", self.oras_loop_worker)
            self.threadpool.start(self.oras_loop_worker)
            self.oras_loop_worker.signals.result.connect(self.set_oras_status)
            self.oras_loop_worker.signals.result.connect(self.construct_raman_profile_combobox) 
        except Exception as e:
            logger.error(e, exc_info=True)

    def test_oras_status_change(self,n:int):
        """
        Generate alternating test ORAS status values based on input parameter.
        
        Returns:
            str: Current reported oras status as a string 
        """
        if n % 2 == 0:
            self.oras_status = 'READY'
            #self.lineEditOrasStatus.setStyleSheet("color:red")
        else: 
            self.oras_status = 'ACQUIRING' 
            #self.lineEditOrasStatus.setStyleSheet("color:green")
        #self.lineEditOrasStatus.setText(self.oras_status)
        return self.oras_status
    
    def set_oras_status(self, oras_status):
        """
        Update UI elements based on ORAS system status and connection state.
        
        Args:
            oras_status (str): ORAS status to be displayed on UI
        Returns:
            tuple(bool, str): 
                * index 0: ORAS connection status
                * index 1: ORAS acquisition status
        """
        try:
            possible_oras_status = ['READY', 'Not Ready', 'ACQUIRING']
            colors = ["color:green", "color:red","color:orange"]
            print("oras status from loop worker:", oras_status)
            if type(oras_status) == ConnectionRefusedError:
                raise ConnectionRefusedError(oras_status)
            elif oras_status in possible_oras_status:
                self.is_oras_linked = True
                print("is oras linked in set_oras_status(): ", self.is_oras_linked)
                self.oras_status = oras_status
                self.lineEditOrasStatus.setText(f'CONNECTED: {oras_status}')
                self.lineEditOrasStatus.setStyleSheet(colors[possible_oras_status.index(oras_status)])
            else:
                self.is_oras_linked = False
                oras_status = 'NOT CONNECTED'
                self.oras_status = oras_status
                self.lineEditOrasStatus.setText(oras_status)
                self.lineEditOrasStatus.setStyleSheet("color:red")
        except ConnectionRefusedError as e:
            #logger.error(e, exc_info=True)
            self.is_oras_linked = False
            oras_status = 'NOT CONNECTED'
            self.oras_status = oras_status
            self.lineEditOrasStatus.setText(oras_status)
            self.lineEditOrasStatus.setStyleSheet("color:red")
        finally:
            return self.is_oras_linked, self.oras_status
                                
    def update_ui(self):
        """Refresh all UI elements based on current instrument and acquisition state."""
        # Enable/disable controls if lamp or spectrometer are connected or not
        self.update_info()
        is_lamp_connected = self.lamp_info.is_connected
        is_spectro_connected = self.spectro_info.is_connected
        is_oras_linked = True#self.is_oras_linked
        self.oras_status = ext.get_system_status()
        tt.sleep(0.2)
        print("lamp status:", self.lamp_info.is_connected)
        print("spectro status:", self.spectro_info.is_connected)
        print("oras linked:", self.is_oras_linked)
        self.pushbtnConnectLamp.setEnabled(not is_lamp_connected)
        self.comboBoxAvailableLamp.setEnabled(not is_lamp_connected)
        self.pushbtnFindLamp.setEnabled(not is_lamp_connected)
        self.pushbtnDisconnectLamp.setEnabled(is_lamp_connected)
        
        print("is_spectro_connected:", is_spectro_connected)
        print("current oras status:", self.oras_status)
        print("is measuring:", self.is_measuring)
        self.pushbtnConnectSpectro.setEnabled(not is_spectro_connected)
        self.comboBoxAvailableSpectro.setEnabled(not is_spectro_connected)
        self.pushbtnFindSpectro.setEnabled(not is_spectro_connected)
        self.pushbtnDisconnectSpectro.setEnabled(is_spectro_connected)
        
        self.pushButtonMeasureDRS.setEnabled(is_spectro_connected and is_lamp_connected and (not self.is_measuring))
        self.pushButtonMeasureRaman.setEnabled(is_oras_linked and (not self.is_measuring) and (self.oras_status == "READY"))
        self.pushButtonMeasureRamanDRS.setEnabled(is_spectro_connected and 
                                                  is_lamp_connected and 
                                                  is_oras_linked and 
                                                  (not self.is_measuring)and
                                                  (self.oras_status == "READY"))
        # update UI based on lamp_info and spectro_info
        self.lineEditSetExposure.setText(self.aec_exposure) 
        self.set_labels_connected(is_lamp_connected, is_spectro_connected)
        if is_lamp_connected == "True":
            self.set_label_lamp_enabled(self.lamp_info.is_enabled)
            
        # Enable/disable controls if measurement in progress
        if self.is_measuring == False:
            self.pushButtonMeasureDRS.setText("DRS")
            self.pushButtonMeasureRaman.setText("Raman")
            self.pushButtonMeasureRamanDRS.setText("Raman\\DRS")
        
        if (self.saved_data_list is not None) and (len(self.saved_data_list) > 0)  and (not self.is_measuring):
            self.display_saved_data()

        if self.checkBoxSave.isChecked() == True:
            print("User selected acquisitions will be saved.") 
            self.labelSaveMessage.setStyleSheet("color: green;") #
            self.labelSaveMessage.setText("Acquisition will be saved")

        elif self.checkBoxSave.isChecked() == False:
            #logger.info("User selected acquisitions will not be saved.") 
            self.labelSaveMessage.setStyleSheet("color: red;") #background-color: black;
            self.labelSaveMessage.setText("Acquisition will not be saved")
        
        
    def lamp_safety_check(self):
        """Verify lamp is in expected enabled/disabled state and log any discrepancies."""
        is_enabled = self.lamp_info.is_enabled
        if is_enabled != self.last_enabled_state:
            logger.warning(
                "Lamp safety trip setting lamp to %s",
                ["Disabled", "Enabled"][is_enabled],
            )
            self.lamp.set_enable(is_enabled)
            self.last_enabled_state = is_enabled

    def update_info(self):
        """Fetch latest lamp and spectrometer status information from hardware."""
        self.lamp_info = self.lamp.get_info()
        self.spectro_info = self.mayaspectro.get_info()
        self.lamp_safety_check()

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Called when a close request is received for the window.
        Handles application close event with user confirmation and hardware cleanup.
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
                    if self.lamp_info.is_connected:
                        self.disconnect_lamp_worker()
                except Exception:
                    logger.exception("Error disconnecting lamp")
            if hasattr(self, "mayaspectro") and getattr(self, "mayaspectro", None) is not None:
                try:
                    if self.spectro_info.is_connected:
                        self.disconnect_mayaspectro_worker()
                except Exception:
                    logger.exception("Error disconnecting spectrometer")
        except Exception:
            logger.exception("Error during hardware cleanup")
        
        #Wait 2 seconds for threadpool tasks to finish
        try:
            #waitForDone expects milliseconds
            self.threadpool.waitForDone(2000)  #ms 
        except Exception:
            logger.exception("Error while waiting for threadpool to finish")

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
    except Exception as e:
        logger.error(e)
        window.LumedDRSWidget.threadpool.stop()