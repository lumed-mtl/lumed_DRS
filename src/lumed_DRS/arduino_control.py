from serial.tools import list_ports
import pyvisa #https://pyvisa.readthedocs.io/en/latest/api/resources.html#api-resources
from pyvisa.constants import BufferType
import time as tt
import matplotlib.pyplot as plt
from threading import Lock
import time as tt
#import logger
class Arduino:
    def __init__(self, usb_lock=None) -> None:
        self.comport: str | None = None #communication port on which the arduino is connected via usb
        self.arduino_DRS_resource : str | None = None #communication resource on which the arduino is connected via usb
        self.pyvisa_serial: pyvisa.resources.serial.SerialInstrument | None = None
        self.isconnected: bool = False
        self._mutex: Lock = usb_lock if usb_lock is not None else Lock()
        self.resource_manage = pyvisa.ResourceManager("@py")


    def find_arduino_device(self) -> dict[str, pyvisa.highlevel.ResourceInfo]:
        """
        find_arduino_device finds and returns which resources detected by pyvisa's resource manage is an arduino

        Returns
        -------
        dict
            Mapping of resource name to ResourceInfo from pyvisa.
        """
        try:
            available_resources = self.resource_manage.list_resources(query='?*::INSTR')
            print("available resources",available_resources)
            ports = list_ports.comports()
            # for i, port in enumerate(ports):
            #     comport_string = str(port)
            #     if 'arduino' in comport_string.lower():  
            #         print('here')
            #         self.comport = resources[i] #comport_string[0: comport_string.find("-")].strip()
            #         print('arduino comport:', resources[i])
            #         return self.comport 
            for resource in available_resources:
                try:
                    tic = tt.time()
                    self.pyvisa_serial = self.resource_manage.open_resource(resource)
                    self.pyvisa_serial.baud_rate = 9600
                    self.pyvisa_serial.write_termination = "\n"
                    self.pyvisa_serial.read_termination = "\n"
                    self.pyvisa_serial.timeout = 1000 # ms                    
                    tt.sleep(2)
                    #self.pyvisa_serial.clear()
                    # current_device.timeout = 500
                    print("current resource:", resource, "current device:", self.pyvisa_serial)
                    query = self.pyvisa_serial.query('*idn?', delay=0.1).strip()
                    #query = self._safe_scpi_query('*idn?')
                    print('query:', query )
                    if 'DRS_arduino' in query:
                        self.pyvisa_serial.close()
                        return resource
                    else:
                        tic = tt.time()
                        self.pyvisa_serial.close()
                        print("closing time:", tt.time() - tic)
                except Exception as e:
                    print("Error:", e)
                    tic = tt.time()
                    self.pyvisa_serial.close()
                    print("closing time:", tt.time() - tic)
                    continue
        except Exception as e:
            print("Error:", e)
            return None
    def connect(self):
        try:
            print("finding arduino device")
            self.arduino_DRS_resource = self.find_arduino_device()
            self.pyvisa_serial = self.resource_manage.open_resource(self.arduino_DRS_resource)
            self.isconnected = True
            self.pyvisa_serial.write_termination = "\n"
            self.pyvisa_serial.read_termination = "\n"
            self.pyvisa_serial.encoding = "utf-8"
            self.pyvisa_serial.baud_rate = 9600 # 115200 # baud rate 
            self.pyvisa_serial.timeout = 1000 #ms
            tt.sleep(1) # Give time to establish the serial connection
            print(f"Connected to arduino on port: {self.arduino_DRS_resource}")
        except:
            print("Warning: could not connect to arduino")   
    def disconnect(self):
        try:
            self.pyvisa_serial.close()
            print(f"Disconnected arduino on port: {self.arduino_DRS_resource}")
        except:
            print("Not able to disconnect arduino")         

    def _safe_scpi_write(self, message: str) -> (int):
        """Sends a serial message to the arduino board and verifies if any communication error occured.

        Parameter : <message> (string) : Message send to the arduino by serial.
        The command syntax for those messages is explained in the documentation provided by IPS.  %

        Returns:
        <err_code> : communication error code
        <err_message> : communication error message
        """
        if not self.isconnected:
            return 0
        with self._mutex:
            try:
                self.pyvisa_serial.write(message)
            except Exception as e:
                print(e)
        # err_msg = self.pyvisa_serial.query("Error?").strip()
        # err_code = err_msg.split(",")[0]
        # err_msg = err_msg.split(",")[-1].strip().strip('"')

        return None #err_code, err_msg
    def _safe_scpi_query(self, message: str) -> (str):
        """Sends a serial message to the arduino

        Parameter : <message> (string) : Message send to the arduino by serial.

        Returns:
        <value> (string) : Answer provided by the arduino to the serial COM.
        """
        with self._mutex:
            try:
                print("before write")
                self.pyvisa_serial.write(message)
                print("after write")
                tt.sleep(0.1) #wait for process to occur
                reading = self.pyvisa_serial.read_raw().decode()
                print("Query reading:", reading)
                print("after read")
                return reading  
            except Exception as e:
                print(e)
    def generate_pulse(self):
        try:
            #pin_state = self._safe_scpi_query("ON")
            # print(f"ttl pin state:", pin_state)
            print("before generated pulse")
            self._safe_scpi_write("ON")
            print("generated pulse")
        except Exception as e:
            print("Generate pulse error:", e)
    def stop_pulse(self):
        try:
            self._safe_scpi_write("OFF")
        except:
            None
    def _safe_scpi_read(self):
        with self._mutex:
            try:
                reading = self.pyvisa_serial.read_raw().decode('utf-8').strip()
                return reading  
            except Exception as e:
                None

if __name__ == "__main__":
    print("Arduino class here")
    # arduino = Arduino()
    # arduino.find_arduino_device()
    # arduino.connect()
    # arduino.generate_pulse() 
    # #arduino._safe_scpi_write("ON")
    # #print("query:", arduino._safe_scpi_query("*idn?"))

    # toc = tt.time()
    # readings = []
    # counter = 0
    # while tt.time()- toc < 10:
    #     print("counter: ", counter)
    #     #arduino._safe_scpi_write("ON") 
    #     reading = arduino._safe_scpi_read()
    #     print("time (s):", round(tt.time()- toc, 3), "reading:", reading)
    #     readings.append(reading)
    #     counter += 1
    # # plt.figure()
    # # plt.plot(readings)
    # #plt.show()
    # arduino.disconnect()
    
    #print(arduino.comport)

