import pyvisa

# Initialize the Resource Manager using the Python backend
rm = pyvisa.ResourceManager('@py')

# Open the specific resource found in your list
# Replace settings (baud_rate, etc.) with those from your instrument's manual
try:
    instrument = rm.open_resource('ASRL/dev/ttyUSB0::INSTR')
    
    # Standard RS232 configurations (Adjust to your device)
    instrument.baud_rate = 9600
    instrument.data_bits = 8
    instrument.stop_bits = pyvisa.constants.StopBits.one
    instrument.parity = pyvisa.constants.Parity.none
    
    # Crucial: Most instruments need these to know when a command ends
    instrument.read_termination = '\n'
    instrument.write_termination = '\n'

    # Test communication
    print("Connected to device.")
    # print(instrument.query('*IDN?')) # Only if your device supports SCPI
    
except Exception as e:
    print(f"Connection failed: {e}")

import serial
print(f"Path: {serial.__file__}")
print(f"Version: {getattr(serial, 'VERSION', 'Unknown')}")
# This should now work without error
print(f"Success: {hasattr(serial, 'serial_for_url')}")

print(serial.__file__)