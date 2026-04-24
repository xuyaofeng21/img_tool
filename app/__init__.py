"""Application package for the local image toolbox."""

import sys
import tempfile
from pathlib import Path


def get_cache_dir() -> Path:
    """Get a writable cache directory for synthesize previews.
    
    - On Windows EXE: writes next to the exe (writable)
    - On Linux AppImage: exe dir is read-only FUSE mount, falls back to
      ``~/.cache/ImgToolbox``
    - In dev mode: uses system temp dir
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
        exe_parent = Path(sys.executable).parent
        cache_dir = exe_parent / "cache" / "img_tool_synthesize_cache"
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            return cache_dir
        except (OSError, PermissionError):
            # Read-only mount (AppImage FUSE) - use user home
            cache_dir = Path.home() / ".cache" / "ImgToolbox" / "img_tool_synthesize_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            return cache_dir

    cache_dir = Path(tempfile.gettempdir()) / "img_tool_synthesize_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

