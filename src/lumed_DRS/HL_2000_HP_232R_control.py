import importlib.metadata
import logging
from dataclasses import dataclass
from threading import Lock
import pyvisa #https://pyvisa.readthedocs.io/en/latest/api/resources.html#api-resources
import time as tt
import serial.tools.list_ports
logger = logging.getLogger()

ERROR_CODES = {
    0: "NO_ERROR",  # Hardware error
}

@dataclass
class LampInfo:
    firmware_version: str = "N/A"
    is_connected: bool = False
    is_enabled: bool = False
    coil_temperature: float = float("nan")
    shutter_position: float = float("nan")
    driver_current: float = float("nan")

class HL2000Lamp:
    """Control Ocean Optics' halogen lamp HL-2000-HP-232R."""
    def __init__(self) -> None:
        self.firmware_version: str | None = None
        self.comport: str | None = None #communication port on which the lamp is connected via usb
        self.pyvisa_serial: pyvisa.resources.serial.SerialInstrument | None = None
        
        self._mutex: Lock = Lock()
        self.isconnected: bool = False
        self.isenabled: bool = False
        self.drive: bool = False
        self.shutter_position: float = float("nan")
        self.resource_manage = pyvisa.ResourceManager("@py")
        self.info = LampInfo()
        
    def find_lamp_device(self) -> dict[str, pyvisa.highlevel.ResourceInfo]:
        """
        find_lamp_device finds and returns which resources detected by pyvisa's resource manage is associated with HL2000 lamp

        Returns
        -------
        dict
            Mapping of resource name to ResourceInfo from pyvisa.
        """
        
        resources = self.resource_manage.list_resources_info()
        ports = serial.tools.list_ports.comports()
        connected_lamps = {}
        counter = -1
        for k, v in resources.items():
            counter+=1
            if "Bluetooth" in ports[counter].description:
                #exclude blutooth COM ports
                continue
            time0 = tt.time()
            try:
                device = self.resource_manage.open_resource(k)
                device.timeout = 50
                version = device.query("VER").strip()
            except Exception as _:
                continue
            if 'Version' in version:
                connected_lamps[k] = {"resourceInfo": v, "version": version.strip()}
        return connected_lamps
    
    ## Basic methods
    def _safe_scpi_write(self, message: str) -> (int):
        """Sends a serial message to the lamp and verifies if any communication error occured.

        Parameter : <message> (string) : Message send to the lamp by serial.
        The command syntax for those messages is explained in the documentation provided by IPS.  %

        Returns:
        <err_code> : communication error code
        <err_message> : communication error message
        """
        if not self.isconnected:
            return 0, ERROR_CODES[0]
        with self._mutex:
            try:
                self.pyvisa_serial.write(message)
            except Exception as e:
                logger.error(e)
        # err_msg = self.pyvisa_serial.query("Error?").strip()
        # err_code = err_msg.split(",")[0]
        # err_msg = err_msg.split(",")[-1].strip().strip('"')

        return None #err_code, err_msg

    def _safe_scpi_query(self, message: str) -> (str):
        """Sends a serial message to the lamp

        Parameter : <message> (string) : Message send to the lamp by serial.

        Returns:
        <value> (string) : Answer provided by the lamp to the serial COM.
        """
        with self._mutex:
            time0 = tt.time()
            try:
                readings = []
                self.pyvisa_serial.write(message)
                reading = 'OK\r\n'
                while reading == 'OK\r\n':
                    reading = self.pyvisa_serial.read_raw().decode()
                return reading  
            except Exception as e:
                logger.error(e)
        #err_msg = self.pyvisa_serial.query("Error?").strip()
        #err_code = int(err_msg.split(",")[0])
        #err_msg = err_msg.split(",")[-1].strip().strip('"')


    def __repr__(self) -> str:
        reprstr = (
            f"HL2000Lamp(Firmware version = '{self.firmware_version}', "
            f"comport = '{self.comport}', "
            f"connected = {self.isconnected}, "
            f"enabled = {self.isenabled}, "
            f"shutter position = {self.info.shutter_position} mA, "
            f" coil temperature = {self.info.coil_temperature}C, "
        )
        return reprstr
    
    ## Getters
    def get_fault_status(self) -> dict:
        """Requests the fault status by looking at the 4-bits returned by the lamp

        Bit #0 = over-temperature;\n
        Bit #1 = over-current;\n
        Bit #2 = under-voltage;\n
        Bit #3 = over-voltage\n
        
        Returns
        fault_status_dict [dict]: Dictionnary with the state of every fault status
        """
        fault_status = self._safe_scpi_query("GFS")
        fault_status_dict = {"Over-temperature":False, "Over-current":False, "Under-voltage":False, "Over-voltage":False}
        if fault_status[0] == "1":
            fault_status_dict["Over-temperature"] = True
            print("Over-temperature condition reached")

        if fault_status[1] == "1":
            fault_status_dict["Over-current"] = True
            print("Over-current condition reached")
            
        if fault_status[2] == "1":
            fault_status_dict["Under-voltage"] = True
            print("Under-voltage condition reached (<15 VDC)")
            
        if fault_status[3] == "1":
            fault_status_dict["Over-voltage"] = True
            print("Over-voltage condition reached (>28 VDC)")   
        elif fault_status == "0000":
            print("No fault detected")
        return fault_status_dict

    def get_coil_temperature(self) -> float:
        """Reports the lightbulb's coil temperature in °C.

        Returns
        coil_temp [float]: module case temperature in °C"""
        coil_temp = self._safe_scpi_query("TEM")
        coil_temp = float(coil_temp)
        return coil_temp
    
    def get_shutter_position(self) -> float:
        """Reports the current shutter position

        Returns 
        shutter_pos [int]: The shutter position
        """
        shutter_pos = self._safe_scpi_query('POS')
        #shutter_pos = float(shutter_pos)
        return shutter_pos
    
    def get_motion_control_status(self) -> str:
        """Requests the motion controller status by looking at the 7-bits returned by the lamp

        Bit 0: 1... Position mode\n
               0... Velocity mode\n
        Bit 1: 1... Speed command is analog input\n
               0... Speed command comes via RS232\n
        Bit 2: 1... Speed command is PWM\n
               0... Speed command is analog voltage\n
        Bit 3: 1... Amplifier Enabled\n
               0... Amplifier Disabled\n       
        Bit 4: 1... In Position
               0... Not in Position
        Bit 5: 1... Rising edge on external switch is valid
               0... Falling edge on external switch is valid
        Bit 6: 1... External switch now high level
               0... External switch now low level
        
        Returns
        motion_control_status_dict [dict]: Dictionnary with the state of every motion control parameter
        """
        motion_control_status = str(self._safe_scpi_query("GST"))
        motion_control_status_dict = {"Motion mode":None, 
                             "Speed command input":None, 
                             "Speed command power":None, 
                             "Amplifier":None, 
                             "Position state":None, 
                             "external switch edge state":None, 
                             "external switch level state":None}
        if motion_control_status[0] == "0":
            motion_control_status_dict["Motion mode"] = "velocity"
        elif motion_control_status[0] == "1":
            motion_control_status_dict["Motion mode"] = "position"

        if motion_control_status[1] == "0":
            motion_control_status_dict["Speed command input"] = "rs232"
        elif motion_control_status[1] == "1":
            motion_control_status_dict["Speed command input"] = "analog"

        if motion_control_status[2] == "0":
            motion_control_status_dict["Speed command power"] = "analog voltage"
        elif motion_control_status[2] == "1":
            motion_control_status_dict["Speed command power"] = "PWM"
        
        if motion_control_status[3] == "0":
            motion_control_status_dict["Amplifier"] = "disabled"
        elif motion_control_status[3] == "1":
            motion_control_status_dict["Amplifier"] = "enabled"
        
        if motion_control_status[4] == "0":
            motion_control_status_dict["Position state"] = "not in position"
        elif motion_control_status[4] == "1":
            motion_control_status_dict["Position state"] = "in position"

        if motion_control_status[5] == "0":
            motion_control_status_dict["external switch edge state"] = "Falling edge is valid"
        elif motion_control_status[5] == "1":
            motion_control_status_dict["external switch edge state"] = "Rising edge is valid"

        if motion_control_status[6] == "0":
            motion_control_status_dict["external switch level state"] = "high"
        elif motion_control_status[6] == "1":
            motion_control_status_dict["external switch level state"] = "low"
        
        return motion_control_status, motion_control_status_dict

    def get_firmware_version(self) -> str:
        """Reports the device's firmware version

        Returns 
        firmware_version [str]: The firmware version
        """
        return self._safe_scpi_query("VER")
    def get_driver_current(self):
        """Reports the motion control driver's current in mA

        Returns 
        current [str]: The driver current in mA
        """
        return float(self._safe_scpi_query("GRC").strip("\r\n"))
    #Setters

    def set_enable(self, enable) -> None:
        """Controls whether the lamp is enabled or disabled.

        Parameter : <enable> (int) : 1/ON = Enables the Lamp, 0/OFF = Disables the lamp
        """
        if enable: 
            #Lamp light will be enabled
            self._safe_scpi_write("SO")
            self.isenabled = True
        elif not enable: 
            #Lamp light will be disabled
            self._safe_scpi_write("CO")
            self.isenabled = False      
    
    def set_home_position(self) -> None:
        """Sets the shutter's home position
        """
        self._safe_scpi_write("HO")

    def set_shutter_position(self, shutter_position, delay = 0.1) -> None:
        """Sets the shutter's position relative to the home position (home position = 0)
        """
        self.set_drive(True)
        self._safe_scpi_write(f'LA{int(shutter_position)}') # Load absolute position (which is relative to home position)
        tt.sleep(delay)
        self._safe_scpi_write('M') #Initiate shutter movement
        tt.sleep(delay)

    def set_drive(self, enable) -> None:
        """Controls whether the shutter motor's drive electronics are enabled or disabled.

        Parameter: <enable> (int) : 1/ON = Enables the drive electronics, 0/OFF = Disables Enables the drive electronics
        """
        if enable:
            self._safe_scpi_write("EN")
            self.drive = True

        elif not enable: 
            self._safe_scpi_write("DI")
            self.drive = False

    ## Compound methods

    def connect(self) -> bool:
        """Connects the lamp"""
        try:
            self.pyvisa_serial = self.resource_manage.open_resource(self.comport)
            self.pyvisa_serial.write_termination = '\r\n'
            self.pyvisa_serial.read_termination = '\r\n'
            self.isconnected = True
        except Exception as _:
            self.isconnected = False

        return self.isconnected
    
    def disconnect(self) -> str:
        """Close the serial connection to the lamp,
        disable lamp light if enabled."""
        self.set_enable(False)
        self.set_drive(False)
        self.pyvisa_serial.close()
        self.isconnected = False
        self.firmware_version = None
        return not self.isconnected
    
    def get_info(self) -> LampInfo:
        if not self.isconnected:
            return LampInfo()

        try:
            version = self.get_firmware_version()
            is_enabled = self.isenabled
            coil_temperature = self.get_coil_temperature()
            shutter_position = self.get_shutter_position()
            driver_current = self.get_driver_current()
            return LampInfo(
                firmware_version=version,
                is_connected=True,
                is_enabled=is_enabled,
                coil_temperature=coil_temperature,
                shutter_position = shutter_position,
                driver_current = driver_current
            )
        except Exception as _:
            return LampInfo()
        


if __name__ == "__main__":
    print("START")
    lamp = HL2000Lamp()
    time0 = tt.time()
    connected_lamps = lamp.find_lamp_device()
    print("find lamp time", time0-tt.time())
    print("Connected lamps:")
    print(list(connected_lamps))
    lamp.comport = list(connected_lamps)[0]
    print("comport:", lamp.comport)
    print("Connecting lamp...")
    lamp.connect()
    lamp.set_shutter_position(-400) 
    lamp.set_home_position() #Setting home posiiton (0) as position with shutter completely closed
    print("real current after moving shutter to home position", lamp._safe_scpi_query('GRC').strip("\r\n"), "mA")
    lamp.set_enable(True)
    print("real current after enabling light", lamp._safe_scpi_query('GRC').strip("\r\n"), "mA")
    print("Illumination open")
    tt.sleep(1)
    lamp._safe_scpi_write('SP1000')
    print("Maximum velocity:", lamp._safe_scpi_query('GSP').strip("\r\n"))
    print("Start loop")
    
    for shutter_position in range(0,500,400):
        tt.sleep(1)
        print("Expected position:", shutter_position)
        # motion_status, motion_status_dict = lamp.get_motion_control_status()
        # print(motion_status)
        # print("Posiiton state before:", motion_status_dict["Position state"])
        lamp.set_shutter_position(shutter_position)
        print("velocity sent", lamp._safe_scpi_query('GV').strip("\r\n"))
        print("real current after moving shutter", lamp._safe_scpi_query('GRC').strip("\r\n"), "mA")
        

        lamp_info = lamp.get_info()
        print("lamp_info position:", lamp_info.shutter_position)
        print("Current position:", lamp.get_shutter_position())
        
        

    tt.sleep(0.1)
    lamp.set_enable(False)
    print("LAMP OFF")
    lamp.disconnect()
    print("Disconnected lamp")

    #lamp.comport = 'ASRL6::INSTR'
    # device = lamp.resource_manage.open_resource(lamp.comport)
    # device.timeout = 500
    # device.query_delay = 0.2
    # device.write_termination = '\r\n'
    # device.read_termination = '\r\n'

    # device.baud_rate = 9600
    # device.data_bits = 8
    # device.parity = pyvisa.constants.Parity.none
    # device.stop_bits = pyvisa.constants.StopBits.one
    # device.flow_control = pyvisa.constants.ControlFlow.none

    #device.write("CO")
    # print("LAMP OFF")
    # device.write('DI')
    
    # tt.sleep(0.5)
    # version = device.query('VER').strip('Version')
    # print("version:",  version)
    # fault_status = device.query('GFS').strip()
    # print("fault status:", fault_status)

    # device.write('EN') #Enable drive elecronics
    # device.write(f'LA{-200}') #load absolute position to attain
    
    # device.write('M') #start motion with the set posiiton
    # tt.sleep(0.1)
    # device.write('GST')
    # while True:
    #     try:
    #         print('motor status', device.read_raw())
    #     except Exception as _:
    #         break
    
    # print('INITIAL POSITION')
    # device.write('POS')
    # while True:
    #     try:
    #         print(device.read_raw())
    #     except Exception as _:
    #         break
    # device.write('HO') #Set present position as home position
    # print("LAMP ON")
    # device.write("SO") #Enable light
    
    # i = 0
    # for shutter_position in range(30,100,20):
    #     print('MOVE TO', shutter_position)
    #     device.write('EN') #Enable drive elecronics
    #     tt.sleep(0.1)
    #     device.write(f'LA{shutter_position}') #load absolute position to attain
    #     tt.sleep(0.1)
    #     device.write('M') #start motion with the set posiiton
    #     tt.sleep(0.1)

    #     device.write('POS')
    #     device.read_raw()
    #     device.write('POS')
    #     readings = []
    #     while True:
    #         try:
    #             readings.append(device.read_raw())
    #         except Exception as _:
    #             break
    #     print(readings)
    
    # tt.sleep(0.01)

    # print("LAMP OFF")
    # device.write('DI')
    # device.write('CO')
    #device.close()

   