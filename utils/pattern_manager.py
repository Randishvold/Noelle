# Noelle_Bot/utils/pattern_manager.py

import os
import pathlib
from typing import Dict, Optional, Tuple

# Tentukan path ke direktori patterns
PATTERNS_DIR = pathlib.Path(__file__).resolve().parent.parent / "patterns"

# Cache untuk menyimpan patterns yang sudah dimuat agar tidak membaca file berulang kali
_pattern_cache: Dict[str, Tuple[str, str]] = {}

def _load_patterns():
    """Memuat atau memuat ulang semua pattern dari direktori."""
    if not os.path.isdir(PATTERNS_DIR):
        print(f"Direktori patterns tidak ditemukan di {PATTERNS_DIR}, akan dibuat.")
        os.makedirs(PATTERNS_DIR)
        return

    _pattern_cache.clear()
    for filename in os.listdir(PATTERNS_DIR):
        if filename.endswith(".md"):
            pattern_name = filename[:-3].lower()
            filepath = os.path.join(PATTERNS_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Ambil baris pertama sebagai deskripsi, fallback jika kosong
                    description = content.splitlines()[0].strip() if content.splitlines() else "Tidak ada deskripsi."
                    _pattern_cache[pattern_name] = (content, description)
            except Exception as e:
                print(f"Error memuat pattern '{filename}': {e}")

def get_pattern(name: str) -> Optional[str]:
    """Mengambil konten system prompt dari pattern yang sudah dimuat."""
    name = name.lower()
    if not _pattern_cache:
        _load_patterns()
    
    pattern_data = _pattern_cache.get(name)
    return pattern_data[0] if pattern_data else None

def get_available_patterns() -> Dict[str, str]:
    """Mengembalikan dictionary nama pattern dan deskripsinya."""
    if not _pattern_cache:
        _load_patterns()
        
    return {name: data[1] for name, data in _pattern_cache.items()}

# Muat patterns saat modul diimpor pertama kali
_load_patterns()