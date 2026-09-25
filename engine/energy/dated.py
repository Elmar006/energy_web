"""UTC execution slots derived from an explicit local service calendar.

Intervals are actual elapsed hours. A daylight-saving transition therefore
produces 23 or 25 slots rather than silently copying a 24-hour profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .contracts import ChargingRequest, ServiceCalendar


@dataclass(frozen=True)
class DatedHorizon:
    start_utc: datetime
    end_utc: datetime
    slot_starts_utc: tuple[datetime, ...]
    local_hours: tuple[int, ...]
    day_boundaries_minutes: tuple[int, ...]

    @classmethod
    def from_calendar(cls, calendar: ServiceCalendar) -> DatedHorizon:
        zone = ZoneInfo(calendar.time_zone)
        boundaries = [datetime.combine(day, time.min, zone).astimezone(timezone.utc)
                      for day in calendar.covered_dates]
        boundaries.append(datetime.combine(calendar.covered_dates[-1] + timedelta(days=1),
                                           time.min, zone).astimezone(timezone.utc))
        start, end = boundaries[0], boundaries[-1]
        count = int((end - start).total_seconds() // 3600)
        if start + timedelta(hours=count) != end:
            raise ValueError("service calendar contains a non-hour-aligned timezone transition")
        slots = tuple(start + timedelta(hours=h) for h in range(count))
        return cls(start, end, slots,
                   tuple(slot.astimezone(zone).hour for slot in slots),
                   tuple(int((boundary - start).total_seconds() // 60)
                         for boundary in boundaries))

    def overlap_hours(self, request: ChargingRequest, slot: int,
                      travel_minutes: float = 0) -> float:
        beginning = max(self.slot_starts_utc[slot],
                        request.arrival_at.astimezone(timezone.utc) +
                        timedelta(minutes=travel_minutes))
        finish = min(self.slot_starts_utc[slot] + timedelta(hours=1),
                     request.deadline_at.astimezone(timezone.utc))
        return max(0.0, (finish - beginning).total_seconds() / 3600)
