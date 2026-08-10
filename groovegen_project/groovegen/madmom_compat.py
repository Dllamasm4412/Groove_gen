"""Import-time compatibility shims so madmom 0.16.1 runs on Python 3.12 / numpy>=1.24.

madmom 0.16.1 predates several stdlib + numpy changes:
  * collections.MutableSequence -> collections.abc.MutableSequence
  * np.float / np.int / np.bool / np.object / np.complex were removed
  * np.float128 may be missing on some platforms (not patched here unless needed)

Import THIS module before importing madmom.
"""
import collections, collections.abc, numpy as np

# --- stdlib: re-expose moved ABCs on `collections` ---
for _name in ("MutableSequence", "MutableMapping", "Mapping", "Sequence",
              "Iterable", "Callable", "MutableSet"):
    if not hasattr(collections, _name):
        setattr(collections, _name, getattr(collections.abc, _name))

# --- numpy: re-add removed scalar aliases ---
for _attr, _repl in (("float", float), ("int", int), ("bool", bool),
                     ("object", object), ("complex", complex)):
    if not hasattr(np, _attr):
        setattr(np, _attr, _repl)
