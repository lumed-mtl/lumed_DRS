from worker import WorkerThread, LoopWorkerThread, CustomThread
from arduino_control import Arduino
from maya_control import MayaSpectrometer, SpectroInfo # Maya spectrometer control functions
from HL_2000_HP_232R_control import HL2000Lamp, LampInfo #Lamp control functions.
import matplotlib.pyplot as plt
import numpy as np
from seabreeze.spectrometers import list_devices, Spectrometer
import time as tt
import sys
from threading import Lock

#connect spectro
trigger_mode = 0
device = list_devices()[0]
spectro = Spectrometer(device)

spectro.trigger_mode(trigger_mode) #set the trigger mode of intensity acquisition
#connect arduino
print(f"Connected to spectrometer: {spectro} with trigger mode set to {trigger_mode}")
exp_list = [10, 200, 300, 400]
fig1, ax1 = plt.subplots(2)
fig2, ax2 = plt.subplots(2)
try:
    for i, exp in enumerate(exp_list):
        spectro.integration_time_micros(exp*1000)
        if i == 0:
            _ = spectro.spectrum()
        wavelengths, counts = spectro.spectrum()
        print("counts:", counts)
        ax1[0].plot(i, np.mean(counts), 'o',label = f"{exp}ms exposure")
        ax1[1].plot(wavelengths, counts,label = f"{exp}ms exposure")
    ax1[0].legend()
    ax1[1].legend()
    #Trigger mode edge
    trigger_mode = 3
    spectro.trigger_mode(trigger_mode) #set the trigger mode of intensity acquisition
    #connect arduino
    _usb_lock = Lock()
    arduino = Arduino(usb_lock = _usb_lock)
    arduino.connect()
     
    for i, exp in enumerate(exp_list):
        spectro.integration_time_micros(exp*1000)
        maya_thread = CustomThread(target=spectro.spectrum)
        maya_thread.start()
        tt.sleep(0.1)
        arduino.generate_pulse() 
        wavelengths, counts = maya_thread.join()
        print("counts:", counts)
        ax2[0].plot(i, np.mean(counts), 'o',label = f"{exp}ms exposure")
        ax2[1].plot(wavelengths, counts,label = f"{exp}ms exposure")
    ax2[0].legend()
    ax2[1].legend()
    plt.show()
    
    
except Exception as e:
    print("error:", e)
    spectro.close()

spectro.close()
