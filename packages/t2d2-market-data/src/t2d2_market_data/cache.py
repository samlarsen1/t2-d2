"""
On-disk cache of daily OHLCV bars, partitioned by trading date.

Layout::

    <root>/<YYYY-MM-DD>/<yahoo ticker>.csv   # one row: that day's bar for that ticker

Each ticker only touches its own files, so concurrent fetches never write the same file.
Old partitions are removed with :meth:`PriceCache.prune`; only folders whose name is an
ISO date are ever deleted.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

# Yahoo symbols are letters, digits and . - = _ (e.g. "NG.L", "BRK-B", "GBPUSD=X")
_SAFE_TICKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=-]*$")
_PARTITION_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ticker_filename(ticker: str) -> str:
    """Return the CSV file name for ``ticker``, rejecting anything that could escape a folder."""
    if not _SAFE_TICKER.match(ticker) or ".." in ticker:
        raise ValueError(f"Unsafe ticker for price cache: {ticker!r}")
    return f"{ticker}.csv"


def _partition_date(path: Path) -> date | None:
    """Parse a partition folder's date, or None if ``path`` isn't a partition folder."""
    if not path.is_dir() or not _PARTITION_NAME.match(path.name):
        return None
    try:
        return date.fromisoformat(path.name)
    except ValueError:
        return None


class PriceCache:
    """Daily OHLCV bars stored as one CSV per ticker per date folder.

    Args:
        root: Directory holding the date partitions, e.g. ``data/prices``. Created on
            first write.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def _partitions(self) -> list[tuple[date, Path]]:
        if not self.root.is_dir():
            return []
        found = [(d, p) for p in self.root.iterdir() if (d := _partition_date(p)) is not None]
        return sorted(found)

    def load(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """Return cached bars for ``ticker`` dated ``start`` ≤ date < ``end``, oldest first.

        Returns an empty frame (with the OHLCV columns) when nothing is cached.
        """
        filename = _ticker_filename(ticker)
        frames: list[pd.DataFrame] = []
        for day, folder in self._partitions():
            if not start <= day < end:
                continue
            path = folder / filename
            if path.is_file():
                frames.append(pd.read_csv(path, index_col=0, parse_dates=True))
        if not frames:
            return pd.DataFrame(columns=OHLCV_COLUMNS, index=pd.DatetimeIndex([]))
        return pd.concat(frames).sort_index()[OHLCV_COLUMNS]

    def save(self, ticker: str, bars: pd.DataFrame) -> int:
        """Write each bar into its date's partition, replacing any cached bar for that date.

        Args:
            ticker: Yahoo ticker the bars belong to.
            bars: Frame indexed by date with at least the OHLCV columns.

        Returns:
            Number of bars written.
        """
        filename = _ticker_filename(ticker)
        written = 0
        for ts, row in bars[OHLCV_COLUMNS].iterrows():
            day = pd.Timestamp(ts).date()
            folder = self.root / day.isoformat()
            folder.mkdir(parents=True, exist_ok=True)
            frame = row.to_frame().T
            frame.index = pd.DatetimeIndex([pd.Timestamp(day)], name="Date")
            # Write then rename, so a crash never leaves a half-written file behind
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=f".{filename}.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    frame.to_csv(f)
                os.replace(tmp, folder / filename)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
            written += 1
        return written

    def delete_ticker(self, ticker: str) -> int:
        """Remove every cached bar for ``ticker``; returns how many files were deleted."""
        filename = _ticker_filename(ticker)
        removed = 0
        for _day, folder in self._partitions():
            path = folder / filename
            if path.is_file():
                path.unlink()
                removed += 1
        return removed

    def prune(self, keep_days: int, today: date) -> list[Path]:
        """Delete date partitions more than ``keep_days`` calendar days before ``today``.

        Only folders named ``YYYY-MM-DD`` directly under the root are removed; any other
        file or folder is left alone.

        Returns:
            The partition folders that were deleted.
        """
        removed: list[Path] = []
        for day, folder in self._partitions():
            if (today - day).days > keep_days:
                shutil.rmtree(folder)
                removed.append(folder)
        if removed:
            logger.info("Pruned %d price cache partitions older than %d days", len(removed),
                        keep_days)
        return removed
