#!/usr/bin/env python3
"""
Main entry point for the Haptic Pattern Generator
"""

import sys
import os

# Add pattern_generator to path
pattern_gen_path = os.path.join(os.path.dirname(__file__), 'pattern_generator')
if pattern_gen_path not in sys.path:
    sys.path.insert(0, pattern_gen_path)

try:
    # New import path after reorganization
    from gui.core.main_gui import main
    main()
except ImportError as e:
    print(f"Import error: {e}")
    try:
        # Fallback to old structure
        from gui.main_gui import main
        main()
    except ImportError as e2:
        print(f"Fallback import also failed: {e2}")
        print("Please check your GUI module structure")
        sys.exit(1)