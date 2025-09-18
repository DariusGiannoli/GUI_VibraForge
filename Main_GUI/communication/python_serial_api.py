import serial
import serial.tools.list_ports
import threading
import time
import asyncio

class python_serial_api:
    def __init__(self):  # Fixed: was _init_ instead of __init__
        self.MOTOR_UUID = 'f22535de-5375-44bd-8ca9-d0ea9ff9e410'  # Keep for compatibility
        self.serial_connection = None
        self.connected = False

    async def send_command_async(self, addr, duty, freq, start_or_stop):
        """Asynchronous method to send a command to the serial device"""
        start_time = time.time()
        if self.send_command(addr, duty, freq, start_or_stop):
            print(f'Command sent asynchronously to #{addr} with duty {duty} and freq {freq}, start_or_stop {start_or_stop}')
        else:
            print(f'Failed to send command asynchronously to #{addr} with duty {duty} and freq {freq}')

        # Wait until it receives a message
        while True:
            if self.serial_connection is None or not self.connected:
                print('Serial connection is not established.')
                return False
            try:
                response = self.serial_connection.readline()
                response = response.decode('utf-8').strip()
                if response:
                    print(f'Received response: {response}')
                    break
            except Exception as e:
                print(f'Error reading from serial: {e}')
            await asyncio.sleep(0.001)

    def create_command(self, addr, duty, freq, start_or_stop):
        serial_group = addr // 16
        serial_addr = addr % 16
        byte1 = (serial_group << 2) | (start_or_stop & 0x01)
        byte2 = 0x40 | (serial_addr & 0x3F)  # 0x40 represents the leading '01'
        byte3 = 0x80 | ((duty & 0x0F) << 3) | (freq & 0x07)  # 0x80 represents the leading '1'
        return bytearray([byte1, byte2, byte3])

    def send_command(self, addr, duty, freq, start_or_stop) -> bool:
        if self.serial_connection is None or not self.connected:
            return False
        if addr < 0 or addr > 127 or duty < 0 or duty > 15 or freq < 0 or freq > 7 or start_or_stop not in [0, 1]:
            return False
        command = self.create_command(int(addr), int(duty), int(freq), int(start_or_stop))
        #command = command + bytearray([0xFF, 0xFF, 0xFF]) * 19  # Padding
        try:
            self.serial_connection.write(command)
            print(f'Serial sent command to #{addr} with duty {duty} and freq {freq}, start_or_stop {start_or_stop}')
            return True
        except Exception as e:
            print(f'Serial failed to send command to #{addr} with duty {duty} and freq {freq}. Error: {e}')
            return False

    def send_command_list(self, commands) -> bool:
        if self.serial_connection is None or not self.connected:
            return False
        command = bytearray()
        for c in commands:
            addr = c.get('addr', -1)
            duty = c.get('duty', -1)
            freq = c.get('freq', -1)
            start_or_stop = c.get('start_or_stop', -1)
            if addr < 0 or addr > 127 or duty < 0 or duty > 15 or freq < 0 or freq > 7 or start_or_stop not in [0, 1]:
                return False
            command = command + self.create_command(int(addr), int(duty), int(freq), int(start_or_stop))
        # padding to 60 bytes
        command = command + bytearray([0xFF, 0xFF, 0xFF]) * (20 - len(commands))
        try:
            self.serial_connection.write(command)
            print(f'Serial sent command list {commands}')
            return True
        except Exception as e:
            print(f'Serial failed to send command list {commands}. Error: {e}')
            return False

    def get_serial_devices(self):
        """Get a list of available serial ports"""
        ports = serial.tools.list_ports.comports()
        return [f"{port.device} - {port.description}" for port in ports]

    def connect_serial_device(self, port_info) -> bool:
        """Connect to a serial device using port information"""
        try:
            # Extract port name from the port_info string
            port_name = port_info.split(' - ')[0]
            
            # Try to open the serial connection
            self.serial_connection = serial.Serial(
                port=port_name,
                baudrate=115200,  # Match Arduino baud rate
                timeout=1,
                write_timeout=1
            )
            
            # Wait a moment for the connection to establish
            time.sleep(2)
            
            if self.serial_connection.is_open:
                self.connected = True
                print(f'Serial connected to {port_name}')
                return True
            else:
                return False
                
        except Exception as e:
            print(f'Serial failed to connect to {port_info}. Error: {e}')
            self.serial_connection = None
            self.connected = False
            return False

    def disconnect_serial_device(self) -> bool:
        """Disconnect from the serial device"""
        try:
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.close()
                self.connected = False
                self.serial_connection = None
                print('Serial disconnected')
                return True
        except Exception as e:
            print(f'Serial failed to disconnect. Error: {e}')
        return False

    # Legacy method names for compatibility with existing code
    def get_ble_devices(self):
        """Legacy method - returns serial devices instead"""
        return self.get_serial_devices()

    def connect_ble_device(self, device_name):
        """Legacy method - connects to serial device instead"""
        return self.connect_serial_device(device_name)

    def disconnect_ble_device(self):
        """Legacy method - disconnects serial device instead"""
        return self.disconnect_serial_device()

if __name__ == '__main__':
    serial_api = python_serial_api()
    print("Searching for Serial devices...")
    device_names = serial_api.get_serial_devices()
    print(device_names)
    
    # Example usage with GUI interaction:
    if device_names:
        if serial_api.connect_serial_device(device_names[2]):
            serial_api.send_command(1, 7, 2, 1)
            time.sleep(3)

            serial_api.send_command(1, 7, 2, 0)
            time.sleep(3)

            # Example usage with a list of commands:
            commands = [
                {
                    "addr": 0,
                    "duty": 7,
                    "freq": 2,
                    "start_or_stop": 1
                },
                {
                    "addr": 1,
                    "duty": 7,
                    "freq": 2,
                    "start_or_stop": 1
                },
                {
                    "addr": 2,
                    "duty": 7,
                    "freq": 2,
                    "start_or_stop": 1
                }
            ]
            serial_api.send_command_list(commands)
            time.sleep(3)

            for c in commands:
                c['start_or_stop'] = 0
            serial_api.send_command_list(commands)
            time.sleep(3)
            
            serial_api.disconnect_serial_device()
            time.sleep(3)