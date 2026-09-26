"""composer package — re-exports the legacy composer.py module.

The composer/ directory shadows composer.py in normal Python resolution.
This __init__.py loads composer.py via importlib and re-exports its public
symbols so existing imports (`from composer import GENRE_CFG`, etc.) keep
working while cell files in the package (calm_cell, hiphop_cell, ...) are
imported normally as composer.calm_cell, composer.hiphop_cell, etc.

TODO: eventually kill composer.py and move its contents into the package.
"""

from __future__ import annotations

import importlib.util as _ilu
from pathlib import Path as _Path

# Load the sibling composer.py file (which the package directory shadows).
_legacy_path = _Path(__file__).parent.parent / "composer.py"
_spec = _ilu.spec_from_file_location("composer_legacy", _legacy_path)
_legacy = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_legacy)  # type: ignore[union-attr]

# Re-export every public name from composer.py at package top level.
for _name in dir(_legacy):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_legacy, _name)

# Keep a handle for cell files that want to be explicit about legacy access.
_composer_legacy = _legacy

del _ilu, _Path, _legacy_path, _spec, _legacy, _name
