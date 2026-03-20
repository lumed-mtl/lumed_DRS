import numpy as np
from maya_control import MayaSpectrometer, SpectroInfo # Maya spectrometer control functions
from arduino_control import Arduino
import matplotlib.pyplot as plt
import time as tt
from threading import Thread
from seabreeze.types import SeaBreezeAPI
from seabreeze.pyseabreeze.features.spectrometer import SeaBreezeSpectrometerFeatureOOI
from seabreeze.spectrometers import list_devices, __getattr__
 
# class CustomThread(Thread):
#     def __init__(self, group=None, target=None, name=None,
#                  args=(), kwargs={}, Verbose=None):
#         Thread.__init__(self, group, target, name, args, kwargs)
#         self._return = None
 
#     def run(self):
#         if self._target is not None:
#             self._return = self._target(*self._args, **self._kwargs)
             
#     def join(self, *args): # .join() method of Thread being overwritten to return
#         Thread.join(self, *args)
#         return self._return
from worker import CustomThread
# Use this public method, which handles the necessary arguments internally:

# #Connect arduino
arduino = Arduino()
# arduino.find_arduino_device()
# arduino.connect()
# print("connected to spectrometer")
#Connect spectrometer
mayaspectro = MayaSpectrometer()
spectros = mayaspectro.find_spectros()
mayaspectro.device = spectros[0]
mayaspectro.connect()
#spectro_feature = SeaBreezeSpectrometerFeatureOOI(mayaspectro.spectro.receive())
tic = tt.time()

exposure_times = np.arange(20,200, 20)

mean_vals= []
fig, ax = plt.subplots(1,2)
try:
    for i,exposure_time in enumerate(exposure_times):
        #set integration time
        mayaspectro.spectro.integration_time_micros(exposure_time * 1000)

        #mayaspectro.spectrum_acquisition(exposure_time)  # *1000 because the exposure time is given in microseconds to the function
        # Get wavelengths and intensities
        
        
        #maya_thread = CustomThread(target=mayaspectro.spectrum_acquisition, args=(exposure_time,))
        maya_thread = CustomThread(target=mayaspectro.spectro.spectrum)

        maya_thread.start()
        tt.sleep(0.05)
        #send trigger pulse with a delay
        arduino.generate_pulse()     
        wavelenghts, count_ini_exposure = maya_thread.join()
        #wavelenghts, count_ini_exposure =  mayaspectro.spectrum_acquisition(exposure_time) #mayaspectro.spectro.f.spectrometer.get_intensities()
        print(count_ini_exposure)    
        mean_vals.append(np.mean(count_ini_exposure))
        ax[0].plot(count_ini_exposure, label = f'exposure = {exposure_time}ms')
        
    ax[1].plot(exposure_times, mean_vals, 'o')
    ax[0].legend()
except:
    None
finally:
    plt.show()
    mayaspectro.disconnect()
    arduino.disconnect()
