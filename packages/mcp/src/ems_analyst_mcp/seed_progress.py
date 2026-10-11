"""Progress reporting for applying a seed dump to the database.

`seed.py` logs the *download* as `seed progress: <label> N% (X MiB of Y MiB)`.
For a big dump the import that follows is the long, silent part — an ISO
install sat at "100%" for minutes — so the apply loop reports its own
percent as `seed import: <label> N% (A of B statements)`. The on-prem
wizard parses both line shapes (platform-engineer's contract).
"""

import logging


class ImportProgress:
    """Logs 'seed import: {label} N% (A of B statements)' as batches commit.

    Call `advance(n)` only AFTER n statements have committed, so the
    percent never runs ahead of what the database actually holds. Logs
    once each time the percent reaches a new multiple of `granularity_pct`
    (1 -> every whole percent, 10 -> every decile).
    """

    def __init__(
        self,
        logger: logging.Logger,
        label: str,
        total: int,
        granularity_pct: int,
    ) -> None:
        self._logger = logger
        self._label = label
        self._total = total
        self._granularity_pct = granularity_pct
        self._applied = 0
        self._last_bucket = 0

    def advance(self, committed: int) -> None:
        """Record `committed` more statements as applied; log if a new bucket was hit."""
        self._applied += committed
        pct = min(self._applied * 100 // self._total, 100)
        bucket = pct - pct % self._granularity_pct
        if bucket > self._last_bucket:
            self._last_bucket = bucket
            self._logger.info(
                "seed import: %s %d%% (%d of %d statements)",
                self._label,
                bucket,
                self._applied,
                self._total,
            )
