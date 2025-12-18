from arduino_control import Arduino
import time as tt
# The arduino freezes if it keeps on outputing with Serial.println() and never being read. 
# This constant output seems to fill the arduino's serial buffer. 
# Therefore, when a command is being sent to the arduino, it is not read.
arduino = Arduino()
arduino.connect()
#arduino.generate_pulse() 
# toc = tt.time()
# t = 0
# while t <= 10:
#     id = arduino._safe_scpi_query("*idn?")
#     print(f"Identification:{id}")
#     for i in range(5):
#         arduino.generate_pulse() 
#         tt.sleep(0.5)
#     print(f"time: {t} s")
#     t = tt.time()-toc
arduino.disconnect()

