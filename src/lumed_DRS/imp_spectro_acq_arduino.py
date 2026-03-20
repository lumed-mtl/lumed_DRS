import numpy as np
from maya_control import MayaSpectrometer, SpectroInfo # Maya spectrometer control functions
from arduino_control import Arduino
import matplotlib.pyplot as plt
import time as tt
from threading import Thread
from seabreeze.types import SeaBreezeAPI
from seabreeze.pyseabreeze.features.spectrometer import SeaBreezeSpectrometerFeatureOOI
from seabreeze.spectrometers import list_devices, __getattr__
 


# Use this public method, which handles the necessary arguments internally:

#Connect spectrometer
mayaspectro = MayaSpectrometer()
spectros = mayaspectro.find_spectros()
mayaspectro.device = spectros[0]
mayaspectro.connect()
# mayaspectro.set_trigger_mode(0)
# wavelenghts, counts = mayaspectro.spectrum_acquisition(8)
#mayaspectro.set_trigger_mode(3)
# mayaspectro.disconnect()
# mayaspectro.connect()
try:
    exposure_times = np.arange(10,100, 20)

    mean_vals= []
    fig, ax = plt.subplots(1,2)

    for i,exposure_time in enumerate(exposure_times):
        tic = tt.time()
        wavelenghts, counts = mayaspectro.spectrum_acquisition(exposure_time) #mayaspectro.spectro.f.spectrometer.get_intensities()
        print(f"Exposure time: {exposure_time}, Spectrum acquisition time: {tt.time()-tic}s", counts)    
        mean_vals.append(np.mean(counts))
        ax[0].plot(counts, label = f'exposure = {exposure_time}ms')
        
    ax[1].plot(exposure_times, mean_vals, 'o')
    ax[0].legend()
    mayaspectro.disconnect()
    plt.show()
except:
    mayaspectro.disconnect()
