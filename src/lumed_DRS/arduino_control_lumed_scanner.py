import time

import pyvisa
from log_utils import get_shared_logger


class ArduinoControl:
    """Manages the serial connection to the Arduino, including methods for connecting, 
    disconnecting, and sending commands."""
    def __init__(self, parent=None):
        """Initializes an instance for handling VISA communication and commands."""
        # Initiate logger
        self.logger = get_shared_logger()

        # Create a PyVISA Resource Manager instance
        self.rm = pyvisa.ResourceManager("@py")

        self.arduino_visa_connection = None
        self.arduino_on = False
        self.main = parent

    def search_port(self, currently_opened_resources: list=[])->list:
        """
        Searches for and returns a list of available serial ports that are identified 
        as Arduino. This function scans all available serial ports on the system,
        filter ports based on if they contain one of the specified keywords to exclude,
        connects to each of the filtered ports, and sends the SCPI command `*idn?` to 
        query the device's identification string. If the response matches the expected 
        identification of the Arduino, the port is added to a list of recognized Arduino 
        ports.

        Args:
            currently_opened_resources (list): List of currently opened ressource's port names

        Returns:
            arduino_ports (list): A list of strings representing the serial ports that 
                are identified as Arduino ports.
        """
        
        # Get all available ports containing "ACM"
        # available_ports = self.rm.list_resources()
        available_ports = self.rm.list_resources_info(query="?*ACM?*")

        # Filter out excluded ports
        # keywords_to_exclude = ['Bluetooth-Incoming-Port']
        # filtered_ports = [port for port in available_ports if not any(kw in port for kw in keywords_to_exclude) and port not in currently_opened_resources]

        # Initialize a variable to store the Arduino ports
        arduino_ports = []

        # Open and check each port
        for port in available_ports:
            try:
                # Connect to the port
                self.arduino_visa_connection = self.rm.open_resource(port)
                self.arduino_visa_connection.baud_rate = 19200
                self.arduino_visa_connection.timeout = 1000 # ms
                self.arduino_visa_connection.write_termination = "\n"
                self.arduino_visa_connection.read_termination = "\n"
                time.sleep(2)

                # Ask for its identification string
                response = self.handle_command("*idn?")

                # Check if the expected Arduino strings are in response
                if response and "Arduino Due" in response and "ATSAM3X8E" in response:
                    arduino_ports.append(port)
                    self.logger.info(f"Arduino IDN: {response}.")
                
            except Exception as e:
                self.logger.error(f"Unexpected error while searching for arduino ports: {e}")

            finally:
                # Disconnect from the port
                self.arduino_visa_connection.close()

        self.arduino_ports = arduino_ports

        return arduino_ports

    def connect(self, port_name: str) -> None:
        """
        Establish a connection to the arduino using the specified port.

        Sets communication parameters such as baud rate and timeouts, and updates the 
        `arduino_on` attribute.

        Args:
            port_name (str): Name of the port to connect to.

        Raises:
            Exception: If an error occurs during the connection process.

        """
        try:
            # Open the arduino visa connection
            self.arduino_visa_connection = self.rm.open_resource(port_name)

            # Set communication parameters for the arduino
            self.arduino_visa_connection.baud_rate = 19200
            self.arduino_visa_connection.timeout = 1000 # ms
            self.arduino_visa_connection.write_termination = "\n"
            self.arduino_visa_connection.read_termination = "\n"
            time.sleep(2)

            # Ask for its identification string
            response = self.handle_command("*idn?")

            # Check if the expected Arduino strings are in response
            if response and "Arduino Due" in response and "ATSAM3X8E" in response:
                # Mark the arduino connection as on
                self.arduino_on = True
                self.logger.info(f"Successfully connected to arduino's port {port_name}.")

            else:
                self.logger.error(f"Trying to connect Arduino to the wrong port: {port_name}. Press 'Port' button to search for the right port.")

        except Exception as e:
            self.logger.error(f"Error: Could not connect to arduino's port {port_name}: {e}")

    def disconnect(self):
        """Attempts to close the currently open VISA connection. Updates the `arduino_on` 
        attribute to indicate that the arduino is no longer connected. Prints an error if 
        any exception occurs during the disconnection process."""

        if self.arduino_visa_connection:
            try:
                # Close the connection to the arduino
                self.arduino_visa_connection.close()

                # Mark the arduino connection as off
                self.arduino_on = False

                self.logger.info(f"Arduino successfully disconnected.")

            except Exception as e:
                self.logger.error(f'Unexpected error while disconnecting arduino: {e}')   
    
    def send_command(self, command):    
        """Sends a command string to the Arduino via the established VISA connection, waits 
        briefly for the command to be processed and then reads and returns the response from 
        the Arduino.

        Args:
            command (str): SCPI command to be sent to the Arduino (e.g., "measure:weight?")

        Returns:
            str or None: response from the Arduino as a string if successful, 
                None if there is an error or if the connection is not open.
        """
        if self.arduino_visa_connection:
            try:
                self.arduino_visa_connection.write(command)
                time.sleep(0.1)  # Wait for command to be processed
                response = self.arduino_visa_connection.read().strip()
                self.logger.debug(response)
                return response
            except pyvisa.errors.VisaIOError as e:
                self.logger.error(f'Unexpected error while sending command to the arduino: {e}')   
                self.arduino_on = False
                return None
        else:
            self.logger.error(f'Cannot send command to Arduino since the VISA connection is not open.')
            return None
    
    def measure_weight(self):
        """Send a command to the Arduino to measure weight from the load cell strain gauge 
        and return the result.

        The method sends the command "measure:weight?" to the Arduino via the `send_command` 
        method and parses the response.

        Returns:
            float or None: The measured weight as a float if the response is successful, 
                None if there is an error or no response.
        """
        command = "measure:weight?"
        response = self.send_command(command)
        if response:
            try:
                return float(response)
            except ValueError:
                self.logger.error(f"Invalid float received from Arduino: {response}")
                self.arduino_on = False
                return None
        else:
            return None
        
    def led_state(self):
        """Send a command to the Arduino to get the LED state and return the result.

        The method sends the command "led:state?" to the Arduino via the `send_command`
        method and parses the response.

        Returns:
            int or None: The LED state (1 if open, 0 if closed) if the response is successful,
                None if there is an error or no response.
        """
        command = "led:state?"
        response = self.send_command(command)
        if response:
            try:
                return int(response)
            except ValueError:
                self.logger.error(f"Invalid integer received from Arduino: {response}")
                self.arduino_on = False
                return None
        else:
            return None

    def identification(self):
        """Send a command to the Arduino to get the identification string of the board and 
        return the result.

        The method sends the command "*idn?" to the Arduino via the `send_command` method 
        and parses the response.

        Returns:
            str or None: The idn as a string if the response is successful, 
                None if there is an error or no response.
        """
        command = "*idn?"
        response = self.send_command(command)
        if response:
            try:
                return str(response)
            except ValueError:
                self.logger.error(f"Invalid string received from Arduino: {response}")
                return None
        else:
            return None
    
    def handle_command(self, command_str):
        """Handle a command string, execute the corresponding action, and return the result.

        This method processes the command string by stripping whitespace and converting it to 
        lowercase. It then matches the command to supported SCPI commands, delegates the 
        command execution to corresponding methods and returns the result.

        Args:
            command_str (str): SCPI command string to send to the arduino VISA connection

        Returns:
            float, int, or None: The result of the command execution
                - float if the command is measure:weight? and is successful
                - int if the command is led:state? and is successful
                - None if the command is invalid or if an error occurs
        """
        command = command_str.strip().lower()
        if command in ["measure:weight?", "measure:wt?", "meas:weight?", "meas:wt?"]:
            return self.measure_weight()
        elif command in ["led:state?", "led:stat?"]:
            return self.led_state()
        elif command == "*idn?":
            return self.identification()
        else:
            self.logger.error(f'Invalid Arduino command : {command_str}')
            return None

if __name__=="__main__":
    arduino = ArduinoControl()
    arduino.search_port(currently_opened_resources=["ASRL/dev/cu.usbserial-1140::INSTR"])