
PATTERN_PARAMETERS = {
    "Single Pulse": {"parameters": []},
    "Wave": {"parameters": [
        {"name": "wave_speed", "label": "Wave speed", "type": "float", "range": (0.1, 3.0), "step": 0.1, "default": 0.6, "suffix": " s"}
    ]},
    "Pulse Train": {"parameters": [
        {"name": "pulse_on",  "label": "Pulse ON",  "type": "float", "range": (0.05, 2.0), "step": 0.05, "default": 0.2, "suffix": " s"},
        {"name": "pulse_off", "label": "Pulse OFF", "type": "float", "range": (0.05, 2.0), "step": 0.05, "default": 0.3, "suffix": " s"},
    ]},
    "Fade": {"parameters": []},
    "Circular": {"parameters": [
        {"name": "rotation_speed", "label": "Rotation speed", "type": "float", "range": (0.1, 3.0), "step": 0.1, "default": 1.0, "suffix": " s"}
    ]},
    "Random": {"parameters": [
        {"name": "change_interval", "label": "Change interval", "type": "float", "range": (0.05, 2.0), "step": 0.05, "default": 0.3, "suffix": " s"}
    ]},
    "Sine Wave": {"parameters": []},
    }

# ---- Premade Pattern catalog (templates you can expand anytime) ----
PREMADE_PATTERNS = [
    {
        "name": "Trio Burst",
        "description": "Single pulse on actuators 0–2. Good for smoke tests.",
        "config": {
            "pattern_type": "Single Pulse",
            "actuators": [0, 1, 2],
            "intensity": 9,
            "frequency": 4,  # device freq code you want as a default
            "specific_parameters": {},
            # If not present in the library, we keep the currently selected waveform
            "waveform": {"name": "Sine"}
        }
    },
    {
        "name": "3×3 Sweep",
        "description": "Wave pattern sweeping across a 3×3 grid (0–8).",
        "config": {
            "pattern_type": "Wave",
            "actuators": [0,1,2,3,4,5,6,7,8],
            "intensity": 8,
            "frequency": 4,
            "specific_parameters": {"wave_speed": 0.6},
            "waveform": {"name": "Sine"}
        }
    },
    {
        "name": "Back Ring (Circular)",
        "description": "Circular pattern over 16 actuators (0–15).",
        "config": {
            "pattern_type": "Circular",
            "actuators": list(range(16)),
            "intensity": 7,
            "frequency": 4,
            "specific_parameters": {"rotation_speed": 1.0},
            "waveform": {"name": "Sine"}
        }
    },
    {
        "name": "Pulse Train 8-Act",
        "description": "Pulse train on 0–7 with 0.2s ON / 0.3s OFF.",
        "config": {
            "pattern_type": "Pulse Train",
            "actuators": list(range(8)),
            "intensity": 9,
            "frequency": 4,
            "specific_parameters": {"pulse_on": 0.2, "pulse_off": 0.3},
            "waveform": {"name": "Sine"}
        }
    },
]