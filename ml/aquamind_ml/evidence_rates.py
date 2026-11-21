"""Application-owned arithmetic for reported imported interval volumes; no I/O."""

from decimal import Decimal, ROUND_HALF_UP, localcontext
import re

RATE_LANGUAGE = re.compile(
    r'\b(?:gpm|gph|flow_rates_gpm)\b|\bflow[ -]?rates?\b|'
    r'\b(?:us\s+)?gal(?:lon)?s?\s*(?:/|per|each|a)\s*(?:min(?:ute)?s?|hours?|hrs?|h)\b', re.I)


def discusses_rates(text):
    return isinstance(text, str) and RATE_LANGUAGE.search(text) is not None


def _amount(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,9}(?:\.[0-9]{1,6})?', value):
        raise ValueError('Invalid reported volume')
    amount = Decimal(value)
    if amount > 1_000_000:
        raise ValueError('Reported volume outside bounds')
    return amount


def _display(value):
    value = value.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
    return format(value, 'f').rstrip('0').rstrip('.') if value else '0'


def render_imported_rates(data, evidence):
    """Use only a successful meter-tool result and host-prepared coverage facts.

    Rate discussions replace the free-form model reply; a later disclaimer cannot
    repair incorrect model arithmetic. The caller still enforces actual MCP reads.
    """
    if not isinstance(data, dict) or data.get('inference_status') != 'not_enabled_for_imported_data':
        raise ValueError('Imported meter evidence required')
    context = data['context']
    minutes, count = context['interval_minutes'], context['reading_count']
    if type(minutes) is not int or not 1 <= minutes <= 60 or type(count) is not int or not 1 <= count <= 672:
        raise ValueError('Invalid interval coverage')
    reading = context['reading_type']
    if reading not in {'actual', 'estimated', 'mixed', 'unknown'}:
        raise ValueError('Invalid reported reading type')
    original_unit = context['volume_unit']
    unit_labels = {'us_gallons': 'US gallons', 'ccf': 'CCF', 'cubic_meters': 'cubic meters', 'liters': 'liters'}
    if original_unit not in unit_labels:
        raise ValueError('Invalid original volume unit')
    coverage = evidence['assessment']['coverage']
    if coverage not in {'partial_period', 'same_period'}:
        raise ValueError('Compatible bill coverage required')
    total = _amount(data['total_us_gallons'])
    values = data.get('interval_volumes_us_gallons')
    if values is not None and (not isinstance(values, (list, tuple)) or len(values) != count):
        raise ValueError('Invalid interval series')
    with localcontext() as precision:
        precision.prec = 40
        precision.rounding = ROUND_HALF_UP
        duration = minutes * count
        gpm = total / duration
        lines = [f'The provided readings report {_display(total)} US gallons over {duration} minutes '
                 f'({count} intervals of {minutes} minutes).',
                 'The supplied values are whole-interval volume totals, not average flow rates or instantaneous samples.',
                 f'Original CSV unit: {unit_labels[original_unit]}. The returned tool volumes used here are normalized US gallons.',
                 f'Derived average for the reported window: {_display(gpm)} GPM '
                 f'({_display(gpm * 60)} US gallons/hour).']
        if values is not None:
            amounts = [_amount(v) for v in values]
            lines.append('Derived interval averages from the reported volumes:')
            for index, volume in enumerate(amounts[:8], 1):
                lines.append(f'- Interval {index}: {_display(volume)} US gallons / {minutes} minutes '
                             f'= {_display(volume / minutes)} GPM.')
            if count > 8:
                lines.append(f'Only the first 8 of {count} intervals are listed; the window average uses the complete reported total.')
        else:
            lines.append('Individual interval rates are not supplied by the summary alone.')
        lines.append('Units: gallons ÷ minutes = GPM; GPM × minutes = gallons. '
                     'These are application-calculated averages from displayed, rounded reported volumes, not new sensor measurements.')
        if coverage == 'partial_period':
            lines.append('Coverage is partial: this window cannot explain or be directly compared with the whole bill period.')
        else:
            bill_total = _amount(evidence['bill']['total_us_gallons'])
            lines.append(f'The bill and readings cover the same complete period. The bill reports {_display(bill_total)} '
                         f'US gallons; the reported meter-minus-bill difference is {_display(total - bill_total)} US gallons. '
                         'This compares supplied numbers only; it does not verify their source.')
        lines.append(f'Reading type: {reading}, as reported by the user. The readings and household association '
                     'remain unverified. These averages do not establish constant flow, within-interval event timing or a fixture cause.')
        if not total:
            lines.append('Reported zero volumes do not independently prove the absence of physical water flow or leaks.')
        return '\n\n'.join(lines)
