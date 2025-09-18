#!/usr/bin/env python3
"""
Entry point for the Haptic Pattern Generator GUI
"""

import sys
import os

# Add the current directory to Python path to ensure imports work
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Add parent directory for external imports
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

def main():
    try:
        # Try the new import path first
        from gui.core.main_gui import main as gui_main
        gui_main()
    except ImportError:
        try:
            # Fallback to old import
            from gui.main_gui import main as gui_main
            gui_main()
        except ImportError:
            try:
                # Last resort fallback
                from main_gui import main as gui_main
                gui_main()
            except ImportError as e:
                print(f"Error: Could not import main GUI module: {e}")
                print("Please ensure the GUI modules are properly installed.")
                sys.exit(1)

if __name__ == "__main__":
    main()