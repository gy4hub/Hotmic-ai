from __future__ import annotations

import sys
from datetime import timezone

if sys.version_info >= (3, 11):
    from datetime import UTC
else:  # pragma: no cover
    UTC = timezone.utc
