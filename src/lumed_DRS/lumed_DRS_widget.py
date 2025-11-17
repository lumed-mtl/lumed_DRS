"""User Interface (UI) for the control of ocean optics HL_2000_HP_232R halogen lamp with the HL2000() class 
imported from the HL_2000_HP_232R_control module"""

import logging
import sys
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from time import strftime
import datetime as dt
import time as tt
import joblib
import glob
import os

import pyqt5_fugueicons as fugue
from PyQt5.QtCore import QTimer, pyqtSignal, pyqtSlot
from PyQt5 import QtWidgets, QtGui
from PyQt5.QtWidgets import QDialog, QApplication, QLabel, QWidget, QMainWindow,QCheckBox, QVBoxLayout
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDoubleValidator, QIntValidator

from maya_control import MayaSpectrometer, SpectroInfo # Maya spectrometer control functions
from HL_2000_HP_232R_control import HL2000Lamp, LampInfo #Lamp control functions.
from ui.Lumed_DRS_ui import Ui_Form

logger = logging.getLogger(__name__)

LOGS_DIR = Path.home() / "logs/HL_2000_HP_232R"
LOG_PATH = LOGS_DIR / f"{strftime('%Y_%m_%d_%H_%M_%S')}.log"

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
    """Configures the logger if lumed_HL_2000_HP_232R is launched as a module"""

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
    logger.setLevel(logging.DEBUG)


class LumedDRSWidget(QWidget, Ui_Form):
    """User Interface for HL_2000_HP_232R white light lamp control.
    Subclass HL2000Widget to customize the Ui_HL2000Widget widget"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # logger
        logger.info("Widget intialization")

        self.lamp: HL2000Lamp = HL2000Lamp()
        self.lamp_info: LampInfo = self.lamp.info
        self.last_enabled_state: bool = False
        self.is_spectro_connected: bool = False
        self.is_oras_linked: bool = False
        self.mayaspectro: MayaSpectrometer = MayaSpectrometer()
        self.spectro_info: SpectroInfo = self.mayaspectro.info
        self.xaxis_file: str|None = None
        self.yaxis_file: str|None = None
        self.spectralon_file: str|None = None
        self.save_dir:  str|None = None
        self.acqname: str|None = None
        self.acqnames_list: list = []
        self.comments_list: list = []
        self.saved_data_list: list = []
        # ui parameters
        self.setup_default_ui()
        self.connect_ui_signals()
        self.setup_update_timer()
        self.setup_pulse_timer()
        self.update_ui()
        logger.info("Widget initialization complete")

    def setup_default_ui(self):
        self.pushbtnFindLamp.setIcon(fugue.icon("magnifier-left"))
        self.pushbtnFindSpectro.setIcon(fugue.icon("magnifier-left"))
        self.checkBoxSave.setChecked(True)
        self.checkBoxSpectralon.setCheckable(False) # Make the normalization check unavailable until a spectralon file is selected 
        #self.spinboxShutterPosition.setMaximum(400)  # max position of lamp shutter
    
    def connect_ui_signals(self):
        self.pushbtnFindLamp.clicked.connect(self.find_lamp)
        self.pushbtnConnectLamp.clicked.connect(self.connect_lamp)
        self.pushbtnDisconnectLamp.clicked.connect(self.disconnect_lamp)
        self.pushbtnFindSpectro.clicked.connect(self.find_spectro)
        self.pushbtnConnectSpectro.clicked.connect(self.connect_mayaspectro)
        self.pushbtnDisconnectSpectro.clicked.connect(self.disconnect_mayaspectro)
        self.toolButtonSpectralonFileSelect.clicked.connect(self.select_spectralon) 
        self.toolButtonXaxisFileSelect.clicked.connect(self.select_xaxis)
        self.toolButtonYaxisFileSelect.clicked.connect(self.select_yaxis)
        self.toolButtonSaveDir.clicked.connect(self.select_save_folder_dir)
        self.pushButtonMeasureDRS.clicked.connect(self.button_DRS_acquisition)
        self.pushButtonMeasureRaman.clicked.connect(self.button_raman_acquisition)
        self.pushButtonMeasureRamanDRS.clicked.connect(self.button_raman_DRS_acquisition)
        self.checkBoxSave.stateChanged.connect(self.update_ui)
        self.comboBoxAcqName.currentTextChanged.connect(self.display_saved_data)  #lambda _: self.display_saved_data()
        
    def find_lamp(self):
        logger.info("Looking for connected lamps")
        self.pushbtnFindLamp.setEnabled(False)
        self.pushbtnFindLamp.setIcon(fugue.icon("hourglass"))
        self.repaint()
        try:
            lamps = self.lamp.find_lamp_device()
            logger.info("Found lamps : %s", lamps)
            self.comboBoxAvailableLamp.clear()
            for lamp in lamps:
                self.comboBoxAvailableLamp.addItem(lamp)
        except Exception as e:
            logger.error(e, exc_info=True)
        self.pushbtnFindLamp.setEnabled(True)
        self.pushbtnFindLamp.setIcon(fugue.icon("magnifier-left"))
        self.update_ui()

    def connect_lamp(self):
        logger.info("Connecting lamp")
        self.pushbtnConnectLamp.setEnabled(False)
        try:
            self.lamp.comport = self.comboBoxAvailableLamp.currentText()
            print("self.lamp.comport:", self.lamp.comport)
            self.lamp.connect()
            logger.info("Connected lamp : %s", self.lamp.comport)
            self.set_initial_lamp_configurations()
            #self.update_timer.start()
        except Exception as e:
            logger.error(e, exc_info=True)
        self.update_ui()
        

    def disconnect_lamp(self):
        logger.info("Disconnecting lamp")
        self.pushbtnDisconnectLamp.setEnabled(False)
        try:
            self.set_initial_lamp_configurations()
            self.lamp.disconnect()
            logger.info("Disconnected lamp")
            self.update_timer.stop()
        except Exception as e:
            logger.error(e, exc_info=True)
        self.update_ui()
        
    
    def connect_mayaspectro(self):
        logger.info("Connecting spectrometer")
        self.pushbtnConnectSpectro.setEnabled(False)
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
            print("Maya spectrometer not available")
        self.update_ui()

    def disconnect_mayaspectro(self):
        logger.info("Disconnecting spectrometer")
        self.pushbtnDisconnectSpectro.setEnabled(False)
        try:
            self.mayaspectro.disconnect()
        except:
            if self.mayaspectro.is_spectro_available() == False:
                print("Maya spectrometer not available")
            raise Exception("No spectrometer available")
        self.update_ui()
        logger.info("Disconnected spectrometer")

    #Calibration files selection
    def select_xaxis(self):
        self.xaxis_file = QtWidgets.QFileDialog.getOpenFileName(self, caption = "Select a file to set xaxis", filter=("Text files (*.txt)"))[0] #CHANGE FILTER PARAMETER
        url = QUrl.fromLocalFile(self.xaxis_file)
        print("xaxis file to be used:", url.fileName())
        self.lineEditXaxisFile.setText(url.fileName()) # Display the selected Spectralon file

    def select_yaxis(self):
        self.yaxis_file = QtWidgets.QFileDialog.getOpenFileName(self, caption = "Select a file to set yaxis", filter=("Text files (*.txt)"))[0] #CHANGE FILTER PARAMETER
        url = QUrl.fromLocalFile(self.yaxis_file)
        print("yaxis file to be used:", url.fileName())
        self.lineEditYaxisFile.setText(url.fileName()) # Display the selected Spectralon file

    def select_spectralon(self):
        self.spectralon_file = QtWidgets.QFileDialog.getOpenFileName(self, caption = "Select a spectralon file", filter=("Text files (*.txt)"))[0] #CHANGE FILTER PARAMETER
        url = QUrl.fromLocalFile(self.spectralon_file)
        print("spectralon file to be used:", url.fileName())
        self.lineEditSpectralonFile.setText(url.fileName()) # Display the selected Spectralon file 
        self.checkBoxSpectralon.setCheckable(True) # Make the normalization check available 

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
        self.construct_combobox(data_list= self.saved_data_list)
        self.update_ui()

    def save_acquisition(self, directory, acq_name, acq_comment, 
                         DRS_background = None, xaxis_DRS = None, DRS_data = None, 
                         raman_background = None,  xaxis_raman = None, raman_data = None):
        """
        Structures data into a dictionnary and saved into .joblib file.
        inputs

        outputs 
        saved_data: dictionnary with measured data 
        """
        saved_data =  {}
        saved_data['acquisition_name'] = acq_name
        saved_data['comment'] = acq_comment
        saved_data['DRS_background'] = DRS_background
        saved_data['xaxis_DRS'] = xaxis_DRS
        saved_data['drs_data'] = DRS_data
        saved_data['raman_background'] = raman_background
        saved_data['xaxis_raman'] = xaxis_raman
        saved_data['raman_data'] = raman_data
        self.saved_data_list.append(saved_data) #add newer data to list of saved data to be displayed on ui
        filename = acq_name.replace(" ", "_")+".joblib" #make name into snakecase
        with open(directory+'\\'+filename, 'w') as f:# Save data in .joblib file
            joblib.dump(saved_data, directory +'\\'+ filename)
        return saved_data

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
        

    def update_combobox(self, acq_name: str, current_data: dict) -> None:
        self.comboBoxAcqName.insertItem(0, acq_name, current_data)
        self.comboBoxAcqName.setCurrentIndex(0)
        #self.textEditComment.setPlainText(self.comboBoxAcqName.currentData()["comment"])

    def display_saved_data(self):
        try:
            print("self.comboBoxAcqName.currentData(): ", self.comboBoxAcqName.currentData())
            self.textEditComment.setPlainText(self.comboBoxAcqName.currentData()["comment"]) #access the data linked to the combobox item
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
    
    def construct_combobox(self, data_list: list | None = None):
        try:
            if data_list is None:
                data_list = self.saved_data_list
            if not data_list:
                return # do nothing if self.data_file_list is None 
            acq_name_list =  [data['acquisition_name'] for data in data_list]
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
        

    def get_acquisition_name(self) -> str:
        self.acqname = self.lineEditAcqName.text()
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

    def AEC_extrapolation(self, shutter_position: int, min_aec_exp: float, max_aec_exp: float, min_acq_exp: float, max_acq_exp: float, target_count: int) -> float:
        """
        This automatic exposure control algorithm tries to ba faster than AEC() by measuring two values of max count with their associated 
        exposure times. It then extrapolates, with a linear curve, the exposure that maximizes dynamic range given by the 'max_exposure' parameter.
        """
        try:
            hardware_min_exposure, hardware_max_exposure = self.mayaspectro.get_exposure_time_lims() #minimal exposure time in ms (/1000 to convert from micro seconds to ms)
            hardware_max_count = self.mayaspectro.get_max_intensity()
            if max_exposure > hardware_max_exposure:
                max_exposure = hardware_max_exposure
                logger.warning("The given maximum exposure is higher then the spectrometer's maximum,\nMax exposure set to hardware maximum: %f ms", hardware_max_exposure)            
            elif max_exposure <= hardware_min_exposure:
                min_exposure = hardware_min_exposure
                logger.error("The given maximum exposure is lower then the spectrometer's minimum.")
                return None
            
            if (min_exposure <= hardware_min_exposure):
                min_exposure = hardware_min_exposure
                logger.warning("The given minimum exposure is lower then the spectrometer's minimum.\nMin exposure set to hardware minimum: %f ms", hardware_min_exposure)
            elif (min_exposure > hardware_max_exposure):
                logger.error("Minimimum exposure exceeds hardware maximum")
                return None
            if target_count > hardware_max_count:
                print("The given maximum count is higher than the maximum count measurable by the spectrometer.\nThe target count will be set to the highest measurable count")
                target_count = hardware_max_count
        except Exception as e:
            logger.error("AEC failed: %s", str(e))
            self.disable_lamp() 
            return None
        
        exposures = np.sort(np.array([min_aec_exp, max_aec_exp])) # ms 
        print("Exposures:", exposures)
        self.lamp.set_shutter_position(shutter_position)
        self.enable_lamp() #Start illumination
        count_min_exposure = self.mayaspectro.spectrum_acquisition(min_exposure)[1] 
        count_max_exposure = self.mayaspectro.spectrum_acquisition(max_exposure)[1]
        max_counts = np.sort(np.array([np.max(count_min_exposure), np.max(count_max_exposure)])) # counts

        while (max_counts[0] > hardware_max_count) or (max_counts[1] > hardware_max_count):
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
        elif optimal_exp <= hardware_min_exposure:
            optimal_exp = hardware_min_exposure
        
        obtained_target_count = np.max(self.mayaspectro.spectrum_acquisition(optimal_exp)[1])
        self.disable_lamp() #Stop illumination
        print(f"Target count: {target_count} used to find\noptimal exposure: {optimal_exp}ms, got max count of {obtained_target_count}", )
        return optimal_exp  

    def background_acquisition(self, exposure): 
        self.disable_lamp() # Stop illumination
        wavelengths, bkg_intensity = self.mayaspectro.spectrum_acquisition(exposure)
        return wavelengths, bkg_intensity

    def DRS_acquisition(self):
        # If some AEC parameters are missing, nothing is returned
        print("self.get_DRS_acq_params():", self.get_DRS_acq_params())
        if self.get_DRS_acq_params() == None:
            return None
        # Get optimal exposure
        min_aec_exp, max_aec_exp, min_acq_exp, max_acq_exp, target_count, N_accumulations = self.get_DRS_acq_params()
        shutter_position = 400 #value of max shutter opening to make sure that it is completely open
        aec_exposure = self.AEC_extrapolation(shutter_position, min_aec_exp, max_aec_exp, min_acq_exp, max_acq_exp, target_count)    
        print("aec_exposure", aec_exposure) 
        
        self.lineEditSetExposure.setText(str(int(aec_exposure)))
        # Proceed with the measurement including background signal
        xaxis_DRS, DRS_background = self.background_acquisition(aec_exposure) #background to be substracted from normal acquisition
        self.enable_lamp()
        for i in range(N_accumulations):
            xaxis_DRS, intensity = self.mayaspectro.spectrum_acquisition(aec_exposure)
            if i == 0:
                DRS_data = np.atleast_2d(intensity-DRS_background).T
            else:
                DRS_data = np.hstack((DRS_data, np.atleast_2d(intensity-DRS_background).T))
        self.disable_lamp()
        return DRS_background, xaxis_DRS, DRS_data

    def button_DRS_acquisition(self):
        # Turn on measuring and tell user it is measuring
        self.pushButtonMeasureDRS.setEnabled(False)
        print(f"Measuring... with {self.checkBoxSave.isChecked()} for saving")
        self.pushButtonMeasureDRS.setText("Measuring...")
        DRS_background, xaxis_DRS, DRS_data  = self.DRS_acquisition()
        if self.checkBoxSave.isChecked() == True:
            # Get info
            raman_background = None 
            xaxis_raman= None
            raman_data = None   
            acq_name = self.get_acquisition_name()
            acq_comment = self.get_acquisition_comment()
            print('acq_comment: ', acq_comment)

            saved_data = self.save_acquisition(self.save_dir, acq_name, acq_comment, 
                                               DRS_background = DRS_background, xaxis_DRS = xaxis_DRS, DRS_data = DRS_data)
        # TODO
        # Display measurment 
        # # Normalize data if checkbox is checked
        # if (self.spectraloncheckbox.isChecked() == True) and (self.spectralon_file !=None):
        #     spectralon_data = np.loadtxt(self.spectralon_file)
            
        #     norm_data = self.data[:,1:]/np.mean(spectralon_data[:,1:], axis=1)[:,None]  #Normalized diffuse reflectance data
        #     self.dspl.ax.cla() #Clears axis
        #     for i in range(1,norm_data.shape[1]):
        #         self.dspl.plot_basic_line(spectralon_data[:,0],norm_data[:,i], label=f"acquisition {i}", xlim = self.minxlim)
        #     self.dspl.plot_basic_line(spectralon_data[:,0],np.mean(norm_data[:,1:], axis=1)[:,None], label=f"average", xlim = self.minxlim)
        #     self.pushButtonMeasureDRS.setText("Measure")
        
        # else :
        #     # No normalizaton if checkbox is unchecked
        #     if (self.spectraloncheckbox.isChecked() == True) and (self.spectralon_file == None):
        #         print("No spectralon file selected. Measurment will not be normalized")
        #         self.errormessage.setText("No spectralon file selected. Measurment will not be normalized")
        #     self.dspl.ax.cla() #Clears axis
        #     self.dspl.plot_basic_line(self.data[:,0],self.background, label="background")
        #     for i in range(1,self.data.shape[1]):
        #         self.dspl.plot_basic_line(self.data[:,0],self.data[:,i], label=f"acquisition {i}")
        #     self.dspl.plot_basic_line(self.data[:,0],np.mean(self.data[:,1:], axis=1)[:,None], label=f"average", xlim = self.minxlim)
        self.pushButtonMeasureDRS.setEnabled(True)
        self.pushButtonMeasureDRS.setText("DRS")
        self.update_combobox(acq_name, saved_data)
        self.update_ui()

    def button_raman_acquisition():
        pass

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

    def find_spectro(self):
        logger.info("Looking for connected spectros")
        self.pushbtnFindSpectro.setEnabled(False)
        self.pushbtnFindSpectro.setIcon(fugue.icon("hourglass"))
        self.repaint()
        try:
            spectros = self.mayaspectro.find_spectros()
            logger.info("Found spectrometers : %s", spectros)
            self.comboBoxAvailableSpectro.clear()
            for spectro in spectros:
                self.comboBoxAvailableSpectro.addItem(
                    f"{spectro.model}:{spectro.serial_number}"
                )
        except Exception as e:
            logger.error(e, exc_info=True)
        self.pushbtnFindSpectro.setEnabled(True)
        self.pushbtnFindSpectro.setIcon(fugue.icon("magnifier-left"))
        self.update_ui()

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
        
        self.pushButtonMeasureDRS.setEnabled(is_spectro_connected and is_lamp_connected)
        self.pushButtonMeasureRaman.setEnabled(is_oras_linked)
        self.pushButtonMeasureRamanDRS.setEnabled(is_spectro_connected and is_lamp_connected and is_oras_linked)
        self.set_labels_connected(is_lamp_connected,is_spectro_connected)
        if (self.saved_data_list is not None) and (len(self.saved_data_list) > 0):
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
    #     self.texteditFV.setPlainText(self.lamp_info.firmware_version.strip("Version "))
    #     self.texteditShutterPosition.setPlainText(str(self.lamp_info.shutter_position))
    #     self.texteditTemperature.setPlainText(str(self.lamp_info.coil_temperature))
    #     self.texteditDrivercurrent.setPlainText(str(self.lamp_info.driver_current))

if __name__ == "__main__":

    # Set up logging
    configure_logger()

    # Create app window
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.show()

    window.setCentralWidget(LumedDRSWidget())

    app.exec_()
