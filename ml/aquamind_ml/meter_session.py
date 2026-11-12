"""One bounded, replaceable meter dataset per host-authenticated session."""

from secrets import token_hex
from threading import Lock
from typing import Literal

from .approvals import ApprovalSessionUnavailable
from .evidence import EvidenceModel, MeterWindowContext
from .meter_import import ImportedMeter


class ImportedMeterSummary(EvidenceModel):
    context: MeterWindowContext
    timezone: str
    total_us_gallons: str
    inference_status: Literal['not_enabled_for_imported_data'] = 'not_enabled_for_imported_data'
    limitations: tuple[str, ...] = (
        'User-provided readings and reading type remain unverified.',
        'Volumes describe intervals starting at each timestamp, not cumulative register readings.',
        'No model inference, real weather, utility tariff or fixture diagnosis is supplied.',
    )


class SessionMeters:
    def __init__(self, *, clock, session_deadline):
        self._clock = clock
        self._deadline = session_deadline
        self._lock = Lock()
        self._revoked = False
        self._household_id = 'house_' + token_hex(16)
        self._entry: tuple[str, ImportedMeter] | None = None

    def invalidate(self):
        with self._lock:
            self._revoked = True
            self._entry = None

    def _require_active(self):
        if self._revoked or self._clock() >= self._deadline:
            self._entry = None
            raise ApprovalSessionUnavailable('Session unavailable')

    def _summary(self):
        if self._entry is None:
            return None
        evidence_id, dataset = self._entry
        return ImportedMeterSummary(context=dataset.context(evidence_id=evidence_id,
            household_id=self._household_id), timezone=dataset.timezone,
            total_us_gallons=dataset.total_us_gallons)

    def replace(self, dataset: ImportedMeter) -> ImportedMeterSummary:
        # Only the trusted parser/host calls this. No caller-supplied ID or path.
        with self._lock:
            self._require_active()
            self._entry = ('meter_' + token_hex(16), dataset)
            return self._summary()

    def current(self) -> ImportedMeterSummary | None:
        with self._lock:
            self._require_active()
            return self._summary()

    def resolve(self, evidence_id: str) -> ImportedMeter:
        """Host-only resolution within this session, never a global checksum lookup."""
        with self._lock:
            self._require_active()
            if self._entry is None or self._entry[0] != evidence_id:
                raise LookupError('Meter evidence unavailable')
            return self._entry[1]

    def clear(self):
        with self._lock:
            self._require_active()
            self._entry = None
