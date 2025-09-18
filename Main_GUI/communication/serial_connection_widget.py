# serial_connection_widget.py
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QComboBox, QTextEdit, QFrame, QGroupBox, QSpinBox,
    QScrollArea, QGridLayout, QMessageBox, QDialog, QListWidget,
    QListWidgetItem, QDialogButtonBox
)
from PyQt6.QtCore import QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QFont, QPalette
import sys
import os

# Import your serial API
from python_serial_api import python_serial_api

class DeviceSelectionDialog(QDialog):
    """Dialog for selecting a USB serial device"""
    
    def __init__(self, devices, parent=None):
        super().__init__(parent)
        self.devices = devices
        self.selected_device = None
        self.setup_ui()
    
    def setup_ui(self):
        self.setWindowTitle("Select USB Serial Device")
        self.setModal(True)
        self.resize(500, 300)
        
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("Available USB Serial Devices:")
        title.setStyleSheet("font-weight: bold; font-size: 14px; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # Device list
        self.device_list = QListWidget()
        self.device_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 5px;
                background-color: white;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #eee;
            }
            QListWidget::item:selected {
                background-color: #4CAF50;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #f0f0f0;
            }
        """)
        
        # Populate device list
        if self.devices:
            for device in self.devices:
                item = QListWidgetItem(device)
                item.setToolTip(f"Click to select: {device}")
                self.device_list.addItem(item)
            # Select first item by default
            self.device_list.setCurrentRow(0)
        else:
            item = QListWidgetItem("No USB serial devices found")
            item.setToolTip("Please check your USB connections")
            self.device_list.addItem(item)
            
        layout.addWidget(self.device_list)
        
        # Info label
        if self.devices:
            info_text = f"Found {len(self.devices)} device(s). Select one and click Connect."
        else:
            info_text = "No devices found. Please check your USB connections and try refreshing."
            
        info_label = QLabel(info_text)
        info_label.setStyleSheet("color: #666; font-size: 11px; margin: 5px 0px;")
        layout.addWidget(info_label)
        
        # Buttons
        button_box = QDialogButtonBox()
        
        if self.devices:
            self.connect_btn = QPushButton("Connect")
            self.connect_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    font-weight: bold;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 20px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
            """)
            button_box.addButton(self.connect_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        button_box.addButton(self.refresh_btn, QDialogButtonBox.ButtonRole.ActionRole)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #666;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        button_box.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        
        layout.addWidget(button_box)
        
        # Connect signals
        if self.devices:
            button_box.accepted.connect(self.accept_selection)
        button_box.rejected.connect(self.reject)
        self.refresh_btn.clicked.connect(self.refresh_devices)
        
        # Double-click to connect
        if self.devices:
            self.device_list.itemDoubleClicked.connect(self.accept_selection)
    
    def accept_selection(self):
        if self.devices and self.device_list.currentItem():
            self.selected_device = self.device_list.currentItem().text()
            self.accept()
    
    def refresh_devices(self):
        # Signal parent to refresh and reopen dialog
        self.done(2)  # Custom result code for refresh


class SerialConnectionWidget(QWidget):
    # Signals for communication with other parts of the application
    connection_status_changed = pyqtSignal(bool)  # True = connected, False = disconnected
    device_connected = pyqtSignal(str)  # Device name when connected
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.serial_api = python_serial_api()
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_devices)
        self.current_device = None
        
        self.init_ui()
        self.setup_styles()
        
        # Start automatic device refresh
        self.refresh_timer.start(2000)  # Refresh every 2 seconds
        self.refresh_devices()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Add stretch to push connection controls to bottom
        layout.addStretch()
        
        # Bottom connection section
        self.create_bottom_connection_section(layout)
    
    def create_bottom_connection_section(self, parent_layout):
        # Create a horizontal layout for bottom-right positioning
        bottom_layout = QHBoxLayout()
        
        # Add stretch to push content to the right
        bottom_layout.addStretch()
        
        # Connection status indicator
        self.status_indicator = QLabel("●")
        self.status_indicator.setStyleSheet("color: #f44336; font-size: 16px; font-weight: bold;")
        self.status_indicator.setToolTip("Connection Status")
        bottom_layout.addWidget(self.status_indicator)
        
        # Status text
        self.status_text = QLabel("Disconnected")
        self.status_text.setStyleSheet("color: #666; font-size: 12px; margin-left: 5px; margin-right: 10px;")
        bottom_layout.addWidget(self.status_text)
        
        # Single connect/disconnect button
        self.connection_btn = QPushButton("Connect USB Device")
        self.connection_btn.clicked.connect(self.toggle_connection)
        self.connection_btn.setMinimumSize(140, 35)
        self.connection_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        bottom_layout.addWidget(self.connection_btn)
        
        parent_layout.addLayout(bottom_layout)
    
    def create_control_section(self, parent_layout):
        """Hidden method - not used in minimal interface"""
        pass
    
    def create_status_section(self, parent_layout):
        """Hidden method - not used in minimal interface"""
        pass
    
    def setup_styles(self):
        # Set minimal widget style
        self.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)
    
    def refresh_devices(self):
        """Refresh the list of available serial devices (silent background operation)"""
        try:
            devices = self.serial_api.get_serial_devices()
            # Just check for devices silently - no UI updates needed for minimal interface
            return len(devices) > 0
        except Exception as e:
            print(f"Error refreshing devices: {str(e)}")
            return False
    
    def toggle_connection(self):
        """Toggle connection state - connect if disconnected, disconnect if connected"""
        if not self.serial_api.connected:
            # Show device selection dialog
            self.show_device_selection_dialog()
        else:
            # Disconnect
            try:
                if self.serial_api.disconnect_serial_device():
                    self.update_connection_status(False)
                    print(f"Disconnected from {self.current_device}")
                    self.current_device = None
                else:
                    print("Failed to disconnect")
            except Exception as e:
                print(f"Disconnect error: {str(e)}")
    
    def show_device_selection_dialog(self):
        """Show dialog to select USB device"""
        while True:  # Loop to handle refresh
            try:
                # Get available devices
                devices = self.serial_api.get_serial_devices()
                
                # Show selection dialog
                dialog = DeviceSelectionDialog(devices, self)
                result = dialog.exec()
                
                if result == QDialog.DialogCode.Accepted and dialog.selected_device:
                    # User selected a device
                    selected_device = dialog.selected_device
                    if self.connect_to_device(selected_device):
                        break  # Successfully connected, exit loop
                    else:
                        # Connection failed, ask if user wants to try again
                        reply = QMessageBox.question(
                            self, 
                            "Connection Failed", 
                            f"Failed to connect to {selected_device}.\n\nWould you like to try another device?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )
                        if reply == QMessageBox.StandardButton.No:
                            break
                        # Continue loop to show dialog again
                
                elif result == 2:  # Refresh requested
                    continue  # Refresh and show dialog again
                
                else:
                    # User cancelled
                    break
                    
            except Exception as e:
                print(f"Error in device selection: {str(e)}")
                self.show_error_message("Error", f"Error getting device list: {str(e)}")
                break
    
    def connect_to_device(self, device_info):
        """Connect to a specific device"""
        try:
            if self.serial_api.connect_serial_device(device_info):
                self.current_device = device_info
                self.update_connection_status(True)
                print(f"Connected to {device_info}")
                self.device_connected.emit(device_info)
                return True
            else:
                print(f"Failed to connect to {device_info}")
                return False
        except Exception as e:
            print(f"Connection error: {str(e)}")
            self.show_error_message("Connection Error", str(e))
            return False
    
    def show_error_message(self, title, message):
        """Show error message to user"""
        try:
            QMessageBox.critical(self, title, message)
        except:
            # If QMessageBox fails, just print to console
            print(f"{title}: {message}")
    
    def update_connection_status(self, connected):
        """Update UI elements based on connection status"""
        if connected:
            self.status_indicator.setStyleSheet("color: #4CAF50; font-size: 16px; font-weight: bold;")
            self.status_text.setText("Connected")
            self.status_text.setStyleSheet("color: #4CAF50; font-size: 12px; margin-left: 5px; margin-right: 10px;")
            self.connection_btn.setText("Disconnect")
            self.connection_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    font-weight: bold;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                }
                QPushButton:hover {
                    background-color: #da190b;
                }
                QPushButton:pressed {
                    background-color: #c1170a;
                }
            """)
            # Update tooltip
            device_name = self.current_device.split(' - ')[0] if self.current_device else "Unknown"
            self.status_indicator.setToolTip(f"Connected to {device_name}")
        else:
            self.status_indicator.setStyleSheet("color: #f44336; font-size: 16px; font-weight: bold;")
            self.status_text.setText("Disconnected")
            self.status_text.setStyleSheet("color: #666; font-size: 12px; margin-left: 5px; margin-right: 10px;")
            self.connection_btn.setText("Connect USB Device")
            self.connection_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    font-weight: bold;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
                QPushButton:pressed {
                    background-color: #3d8b40;
                }
            """)
            self.status_indicator.setToolTip("No device connected")
        
        self.connection_status_changed.emit(connected)
    
    def start_test(self):
        """Start a test vibration - simple version for API compatibility"""
        if not self.serial_api.connected:
            return False
        return self.serial_api.send_command(1, 7, 2, 1)  # Default test parameters
    
    def stop_test(self):
        """Stop the test vibration - simple version for API compatibility"""
        if not self.serial_api.connected:
            return False
        return self.serial_api.send_command(1, 7, 2, 0)
    
    def test_multiple_devices(self):
        """Test multiple devices - simple version for API compatibility"""
        if not self.serial_api.connected:
            return False
        
        commands = [
            {"addr": 1, "duty": 7, "freq": 2, "start_or_stop": 1},
            {"addr": 2, "duty": 7, "freq": 2, "start_or_stop": 1},
            {"addr": 3, "duty": 7, "freq": 2, "start_or_stop": 1}
        ]
        return self.serial_api.send_command_list(commands)
    
    def stop_multiple_devices(self):
        """Stop multiple device test - simple version for API compatibility"""
        if not self.serial_api.connected:
            return False
            
        commands = [
            {"addr": 1, "duty": 7, "freq": 2, "start_or_stop": 0},
            {"addr": 2, "duty": 7, "freq": 2, "start_or_stop": 0},
            {"addr": 3, "duty": 7, "freq": 2, "start_or_stop": 0}
        ]
        return self.serial_api.send_command_list(commands)
    
    def log_message(self, message, error=False):
        """Log message - simplified for minimal interface"""
        print(f"{'ERROR: ' if error else ''}{message}")
    
    def clear_log(self):
        """Clear log - minimal interface compatibility"""
        pass
    
    def get_serial_api(self):
        """Get the serial API instance for use by other parts of the application"""
        return self.serial_api
    
    def is_connected(self):
        """Check if currently connected to a device"""
        return self.serial_api.connected
    
    def get_current_device(self):
        """Get the currently connected device name"""
        return self.current_device
    
    def closeEvent(self, event):
        """Clean up when widget is closed"""
        if self.serial_api.connected:
            self.serial_api.disconnect_serial_device()
        self.refresh_timer.stop()
        super().closeEvent(event)


# Test the widget standalone
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys
    
    app = QApplication(sys.argv)
    
    # Create a test window
    widget = SerialConnectionWidget()
    widget.setWindowTitle("Serial Connection Test")
    widget.resize(400, 600)
    widget.show()
    
    sys.exit(app.exec())