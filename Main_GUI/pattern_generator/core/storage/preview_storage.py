import os
from typing import Optional
from ..phantom_engine import PreviewBundle

PREVIEWS_DIR = "saved_previews"

def ensure_dir():
    if not os.path.exists(PREVIEWS_DIR):
        os.makedirs(PREVIEWS_DIR)

def save_bundle(bundle: PreviewBundle) -> str:
    ensure_dir()
    safe = bundle.name.replace(" ", "_")
    path = os.path.join(PREVIEWS_DIR, f"{safe}.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(bundle.to_json())
    return path

def load_bundle(path: str) -> Optional[PreviewBundle]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return PreviewBundle.from_json(f.read())

def list_bundles() -> list[str]:
    ensure_dir()
    return sorted([f for f in os.listdir(PREVIEWS_DIR) if f.endswith(".json")])