import seabreeze
from dataclasses import dataclass
seabreeze.use("pyseabreeze") # cseabreeze pyseabreeze two distinct implementations
from seabreeze.spectrometers import list_devices, Spectrometer
import time as tt
import importlib.util
from arduino_control import Arduino
import numpy as np
import logging
from pathlib import Path
from time import strftime
from threading import Lock
try:
    from worker import CustomThread
except ImportError:
    pass

logger = logging.getLogger(__name__)

# LOGS_DIR = Path.home() / "logs/lumed_DRS"
# LOG_PATH = LOGS_DIR / f"{strftime('%Y_%m_%d_%H_%M_%S')}.log"

# LOG_FORMAT = (
#     "%(asctime)s - %(levelname)s"
#     "(%(filename)s:%(funcName)s)"
#     "(%(filename)s:%(lineno)d) - "
#     "%(message)s"
# )

# def configure_logger():
#     """Configures the logger if lumed_DRS_widget is launched as a module"""

#     if not LOGS_DIR.parent.exists():
#         LOGS_DIR.parent.mkdir()
#     if not LOGS_DIR.exists():
#         LOGS_DIR.mkdir()

#     formatter = logging.Formatter(LOG_FORMAT)

#     terminal_handler = logging.StreamHandler()
#     terminal_handler.setFormatter(formatter)
#     file_handler = logging.FileHandler(LOG_PATH)
#     file_handler.setFormatter(formatter)

#     logger.addHandler(terminal_handler)
#     logger.addHandler(file_handler)
#     # Reduce noisy output from pyvisa/pyserial internals
#     logger.setLevel(logging.DEBUG)
#     logging.getLogger("pyvisa").setLevel(logging.WARNING)
#     logging.getLogger("pyvisa.messagebased").setLevel(logging.WARNING)
#     logging.getLogger("pyvisa-py").setLevel(logging.WARNING)
#     logging.getLogger("serial").setLevel(logging.WARNING)
    
#     # Prevent messages from being propagated to the root logger (and printed again)
logger.propagate = False

@dataclass
class SpectroInfo:
    model: str = "N/A"
    is_connected: bool = False
    serial_number: str = "N/A"

class MayaSpectrometer:

    def __init__(self):
        
        self.spectro: Spectrometer = None
        self.arduino: Arduino = None
        self.device = None
        self.spectro_id: str = None
        self.isconnected = False
           
        self.trigger_mode = 0 
        self.info = SpectroInfo()
        self._usb_lock = Lock()
        self._acq_lock = Lock()  # serialize spectrum acquisition calls (prevent concurrent spectro access)
    def find_spectros(self):
        """
        find_spectros finds available devices

        Returns
        -------
        available_spectros: list of available devices
        """
        available_spectros = list_devices()
        return available_spectros

    def is_spectro_available(self):
        """
        Checks if any spectrometers are available to be connected
        """
        if len(list_devices()) != 0:
            return True
        else:
            return False

    def set_trigger_mode(self, trig_mode):
        
        """
        Sets the trigger mode of ocean optics spectrometer.
        
        Args:
            trig_mode (int): trigger mode to be set
                - 0: Continuously scanning (Default)
                - 1: External Hardware Level Trigger Mode
                - 2: External Synchronous Trigger Mode
                - 3: External Hardware Edge Trigger Mode
        """
        spam_spec = importlib.util.find_spec("worker")
        found_worker_module = spam_spec is not None
        if found_worker_module:
            self.trigger_mode = trig_mode
            self.spectro.trigger_mode(self.trigger_mode) #set the trigger mode of intensity acquisition
        else:
            print("'worker' module was not found, spectrometer trigger mode set to default of '0'")
            self.trigger_mode = 0
            self.spectro.trigger_mode(self.trigger_mode) #set the trigger mode of intensity acquisition
    
    def connect(self):
        """
        Connect to requested spectrometer
        """
        try:
            # For some reason the trigger mode has to be first set to its default value (0) 
            # then take a dummy acquisition and set the wanted trigger mode of 3 
            # for it to properly work in the trigger mode 3 ¯\_(ツ)_/¯
            self.spectro = Spectrometer(self.device)
            #connect arduino
            self.arduino = Arduino(usb_lock = self._usb_lock)
            self.arduino.connect()
            self.spectro.trigger_mode(0) # Set the to trigger mode 0 even though its already at this trigger mode by default ¯\_(ツ)_/¯
            if self.arduino.isconnected: # arduino device exists
                print("performing dummy acquisition")
                wavelenghts, counts = self.spectrum_acquisition(8) # dummy acquisition of 8 ms so that spectrometer can properly change its trigger mode ¯\_(ツ)_/¯
                self.trigger_mode = 3 #set the trigger mode to external hardware if arduino is connected
            self.isconnected = True
            self.spectro.trigger_mode(self.trigger_mode) #set the trigger mode of intensity acquisition
            print(f"Connected to spectrometer: {self.spectro} with trigger mode set to {self.trigger_mode}")
        except Exception as e:
            print(f"Error spectrometer connection: {e}")

    def spectrum_acquisition(self, exposure_time):
        """
        Initiates a spectrum acquisition for a set exposure time and returns the measured counts with their associated wavelengths.

        ## Parameters:
        exposure_time: `float`\n
        exposure time given in units of ms

        ## Returns:
        combined array of wavelengths and measured intensities
        """
        with self._acq_lock:
            try:
                # Always set exposure first in a USB-safe block.
                try:
                    rounded_us_exp = int(np.round(exposure_time * 1000))
                    logger.info(f"Setting exposure time to {rounded_us_exp/1000:.3f} ms ({rounded_us_exp} µs)")
                    with self._usb_lock:
                        self.spectro.integration_time_micros(rounded_us_exp)
                    tt.sleep(0.05)
                except Exception as e:
                    logger.error("Error during integration time setting", exc_info=True)
                    raise

                #logger.info(f"acquisition with trigger mode: {self.trigger_mode}")

            #     if self.trigger_mode == 3:
            #         # Start the spectrometer acquisition in a dedicated thread, then pulse Arduino.
            #         def _capture_spectrum():
            #             return self.spectro.spectrum()

            #         spectrum_thread = CustomThread(target=self.spectro.spectrum)
            #         spectrum_thread.daemon = True
            #         spectrum_thread.start()
            #         logger.debug("Started external trigger spectrum worker")

            #         tt.sleep(0.1)  # small delay to ensure spectrometer has armed itself

            #         with self._usb_lock:
            #             self.arduino.generate_pulse()
            #             logger.info("Generated pulse")

            #         result = spectrum_thread.join(timeout=10.0)
            #         if result is None:
            #             raise TimeoutError("Spectrometer spectrum acquisition timed out. Check hardware trigger connection.")
            #         wavelengths, counts = result
            #         logger.info("Joined spectrum worker")

            #     else:
            #         with self._usb_lock:
            #             wavelengths, counts = self.spectro.spectrum()

            #     # Eagerly request features to warm up if available (no block)
            #     try:
            #         _ = self.spectro.features
            #     except Exception:
            #         pass

            #     return wavelengths, counts

            
                logger.info(f"acquisition with trigger mode:{self.trigger_mode}")
                if self.trigger_mode == 3:
                    #Start the spectrum acquisition thread
                    #with self._usb_lock:
                    spectrum_thread = CustomThread(target=self.spectro.spectrum)
                    logger.info(f"Initialized spectrum thread") 
                    spectrum_thread.start()
                    logger.info(f"Started spectrum thread") 
                    #Small delay to ensure spectrum() is actually running and waiting for trigger
                    tt.sleep(0.05)
                    #trigger pulse after thread is listening
                    self.arduino.generate_pulse()
                    print(f"Generated pulse")     
                    logger.info(f"Generated pulse") 
                    #Wait for the thread to complete with timeout
                    wavelengths, counts = spectrum_thread.join(timeout=10.0)
                    if wavelengths is None or counts is None:
                        raise TimeoutError("Spectrometer spectrum acquisition timed out. Check hardware trigger connection.")
                    logger.info(f"Joined thread")    
                else:
                    #Get wavelengths and intensities
                    print(f"running spectrum in else condition")  
                    with self._usb_lock:
                        wavelengths, counts = self.spectro.spectrum() 
                    self.spectro.features
                return wavelengths, counts
            except Exception as e:
                logger.error(e, exc_info=True)
                print(f"Error during integration time setting: {e}")
                raise Exception

    def disconnect(self):
        """Disconnect spectrometer"""
        if self.arduino.isconnected:
            self.arduino.disconnect()
        self.spectro.close()
        self.isconnected = False
        print(f"Disconnected from spectrometer: {self.spectro}")

    def get_max_intensity(self):
        return self.spectro.max_intensity

    def get_exposure_time_lims(self):
        """Returns the upper and lower bounds on exposure time in seconds for the current spectrometer self.spectro"""
        return (
            self.spectro.integration_time_micros_limits[0] / 1000,
            self.spectro.integration_time_micros_limits[1] / 1000,
        )

    def get_model(self):
        """Returns the connected spectrometer's model"""
        return self.spectro.model

    def get_serial_number(self):
        """Returns the connected spectrometer's serial number"""
        return self.spectro.serial_number
    
    def get_info(self) -> SpectroInfo:
        if not self.isconnected:
            return SpectroInfo()
        try:
            model = self.get_model()
            serial_number = self.get_serial_number()
            return SpectroInfo(
                model=model,
                is_connected=True,
                serial_number=serial_number
            )
        except Exception as _:
            return SpectroInfo()

if __name__ == "__main__":
    print("yoyoyo")
    # import matplotlib.pyplot as plt

    # spectro = MayaSpectrometer()
    # spectro.device = spectro.find_spectros()[0]
    # print("available devices:", spectro.find_spectros())
    # print("Maya available:", spectro.is_spectro_available())
    # # spectro.connect()
    # # print(type(spectro.spectro))
    # spectro.connect()
    # print(type(spectro.spectro))
    # print("Maya available2:", spectro.is_spectro_available())
    # print("Maya spectro max count:", spectro.get_max_intensity())
    # print("Maya exposure limits:", spectro.get_exposure_time_lims(), "ms")
    # exposure = 100
    # wavelengths, intensities = spectro.spectrum_acquisition(exposure)
    # spectro.disconnect()
    # plt.figure()
    # plt.plot(wavelengths, intensities)
    # plt.show()
