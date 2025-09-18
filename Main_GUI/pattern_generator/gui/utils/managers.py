import os
import sys
import json
from datetime import datetime

# Configuration du PYTHONPATH pour trouver waveform_designer
current_dir = os.path.dirname(os.path.abspath(__file__))  # gui/
pattern_generator = os.path.dirname(current_dir)          # pattern_generator/
main_gui = os.path.dirname(pattern_generator)             # Main_GUI/
if main_gui not in sys.path:
    sys.path.insert(0, main_gui)

try:
    from waveform_designer.event_designer.core.event_data_model import HapticEvent, WaveformData, load_csv_waveform, EventMetadata, EventCategory
except ImportError:
    # Si waveform_designer n'est pas disponible, définir des classes de fallback
    print("Warning: waveform_designer module not found, using fallback classes")
    HapticEvent = None
    WaveformData = None
    load_csv_waveform = None
    EventMetadata = None
    EventCategory = None


class WaveformLibraryManager:

    EXT = (".json", ".csv", ".haptic")

    def __init__(self):
        here = os.path.dirname(os.path.abspath(__file__))  # .../Main_GUI/Pattern_Generator/gui
        pattern_generator = os.path.dirname(here)          # .../Main_GUI/Pattern_Generator  
        main_gui = os.path.dirname(pattern_generator)      # .../Main_GUI
        project_root = os.path.dirname(main_gui)           # .../VibraForge_GUI
        
        # Vérification que c'est bien la racine
        indicators = ['requirements.txt', 'pyproject.toml', '.git', 'README.md']
        if not any(os.path.exists(os.path.join(project_root, i)) for i in indicators):
            print(f"Warning: Project root indicators not found in {project_root}")

        root_lib = os.path.join(project_root, "waveform_library")
        alt_lib  = os.path.join(main_gui,    "waveform_library")

        def count_customized(lib_root):
            d = os.path.join(lib_root, "customized")
            try:
                return sum(1 for fn in os.listdir(d) if fn.lower().endswith(self.EXT))
            except Exception:
                return -1

        # 2) Choose the lib with more files in customized/
        root_cnt = count_customized(root_lib)
        alt_cnt  = count_customized(alt_lib)
        chosen   = root_lib if root_cnt >= alt_cnt else alt_lib

        self.lib_root   = chosen
        self.custom_dir = os.path.join(self.lib_root, "customized")
        os.makedirs(self.custom_dir, exist_ok=True)

        # helpful for logs
        self._which = "repo_root" if chosen == root_lib else "Main_GUI"

    def list_entries(self):
        entries = []
        try:
            for fn in sorted(os.listdir(self.custom_dir)):
                if fn.lower().endswith(self.EXT):
                    path = os.path.join(self.custom_dir, fn)
                    name, ext = os.path.splitext(fn)
                    entries.append({"name": name, "display": name, "ext": ext.lower(), "path": path})
        except Exception as e:
            print(f"[WaveformLibrary] scan error: {e}")
        return entries

    def load_event(self, entry):
        if HapticEvent is None:
            return None
        try:
            if entry["ext"] in (".json", ".haptic"):
                return HapticEvent.load_from_file(entry["path"])
            # CSV → wrap
            t, y, sr = load_csv_waveform(entry["path"], default_sr=1000.0)
            wf = WaveformData(
                amplitude=[{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t, y)],
                frequency=[], duration=float(t[-1] if len(t) else 0.0), sample_rate=float(sr)
            )
            ev = HapticEvent()
            ev.metadata = EventMetadata(name=entry["name"], category=EventCategory.CUSTOM,
                                        description=f"CSV from {self._which}")
            ev.waveform_data = wf
            return ev
        except Exception as e:
            print(f"[WaveformLibrary] load error: {e}")
            return None
        
class EventLibraryManager:
    """Manager for the root-level event library"""
    
    def __init__(self):
        # Determine the event_library path relative to the project root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        self.event_library_path = os.path.join(project_root, "event_library")
        
        # Create event_library directory if it doesn't exist
        os.makedirs(self.event_library_path, exist_ok=True)
        
        # Create __init__.py if it doesn't exist
        init_file = os.path.join(self.event_library_path, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, 'w') as f:
                f.write("# Event Library\n")
    
    def get_all_events(self):
        """Get all available events"""
        events = {}
        
        try:
            if os.path.exists(self.event_library_path):
                for filename in os.listdir(self.event_library_path):
                    if filename.endswith('.json'):
                        event_name = filename[:-5]  # Remove .json extension
                        events[event_name] = filename
        except Exception as e:
            print(f"Error scanning event library: {e}")
        
        return events
    
    def load_event(self, event_name):
        """Load an event from the library"""
        try:
            if HapticEvent:
                filepath = os.path.join(self.event_library_path, f"{event_name}.json")
                return HapticEvent.load_from_file(filepath)
        except Exception as e:
            print(f"Error loading event {event_name}: {e}")
        return None
    
class PatternLibraryManager:
    """Gestionnaire pour la bibliothèque de patterns"""
    
    def __init__(self):
        # Determine the pattern_library path relative to the project root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        self.pattern_library_path = os.path.join(project_root, "pattern_library")
        
        # Create pattern_library directory if it doesn't exist
        os.makedirs(self.pattern_library_path, exist_ok=True)
        
        # Create __init__.py if it doesn't exist
        init_file = os.path.join(self.pattern_library_path, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, 'w') as f:
                f.write("# Pattern Library\n")
    
    def save_pattern(self, pattern_name, pattern_data):
        """Sauvegarder un pattern dans la bibliothèque"""
        filename = f"{pattern_name}.json"
        filepath = os.path.join(self.pattern_library_path, filename)
        
        try:
            with open(filepath, 'w') as f:
                json.dump(pattern_data, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving pattern {pattern_name}: {e}")
            return False
    
    def load_pattern(self, pattern_name):
        """Charger un pattern depuis la bibliothèque"""
        filename = f"{pattern_name}.json"
        filepath = os.path.join(self.pattern_library_path, filename)
        
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading pattern {pattern_name}: {e}")
            return None
    
    def get_all_patterns(self):
        """Obtenir tous les patterns disponibles"""
        patterns = {}
        
        try:
            if os.path.exists(self.pattern_library_path):
                for filename in os.listdir(self.pattern_library_path):
                    if filename.endswith('.json'):
                        pattern_name = filename[:-5]  # Remove .json extension
                        pattern_data = self.load_pattern(pattern_name)
                        if pattern_data:
                            patterns[pattern_name] = pattern_data
        except Exception as e:
            print(f"Error scanning pattern library: {e}")
        
        return patterns
    
    def delete_pattern(self, pattern_name):
        """Supprimer un pattern de la bibliothèque"""
        filename = f"{pattern_name}.json"
        filepath = os.path.join(self.pattern_library_path, filename)
        
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                return True
        except Exception as e:
            print(f"Error deleting pattern {pattern_name}: {e}")
        
        return False
    
    def get_pattern_info(self, pattern_name):
        """Obtenir les informations d'un pattern"""
        pattern_data = self.load_pattern(pattern_name)
        if pattern_data:
            return {
                'name': pattern_data.get('name', pattern_name),
                'description': pattern_data.get('description', ''),
                'timestamp': pattern_data.get('timestamp', ''),
                'config': pattern_data.get('config', {})
            }
        return None

class DrawingLibraryManager:
    """Storage for freehand drawings done on the actuator canvas overlay."""
    def __init__(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        self.root = os.path.join(project_root, "drawing_library")
        os.makedirs(self.root, exist_ok=True)
        init_file = os.path.join(self.root, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, "w") as f:
                f.write("# Drawing Library\n")

    def list(self) -> list[str]:
        items = []
        for fn in sorted(os.listdir(self.root)):
            if fn.lower().endswith(".json"):
                items.append(fn[:-5])  # without .json
        return items

    def save_json(self, name: str, data: dict) -> bool:
        path = os.path.join(self.root, f"{name}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"[DrawingLib] save error: {e}")
            return False

    def load_json(self, name: str) -> dict | None:
        path = os.path.join(self.root, f"{name}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[DrawingLib] load error: {e}")
            return None

    def delete(self, name: str) -> bool:
        path = os.path.join(self.root, f"{name}.json")
        try:
            if os.path.exists(path):
                os.remove(path)
                return True
            return False
        except Exception as e:
            print(f"[DrawingLib] delete error: {e}")
            return False

    def export_png_path(self, name: str) -> str:
        return os.path.join(self.root, f"{name}.png")