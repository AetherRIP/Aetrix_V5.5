"""The one correction engine this build contains.

``aetrix_v5_5`` is it: the adapter in ``aetrix.py`` records provenance and hands
the claimed job to ``AetrixPipeline``, which owns per-question marking, evidence,
integrity, recovery, the independent double check and the result guard.  There is
no registry, no configuration switch and no placeholder.
"""

from __future__ import annotations

from .aetrix import AetrixEngine
from .protocol import engine_attribution_conflict

__all__ = [
    "AetrixEngine",
    "engine_attribution_conflict",
]
