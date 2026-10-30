"""Billing calendar helpers for the VPS traffic subscription."""
import calendar
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo


def quota_bytes(value):
    try:
        amount = Decimal(str(value)) * 1_000_000_000
        if not amount.is_finite() or amount <= 0 or amount != amount.to_integral_value():
            raise ValueError('quota must be a positive whole number of bytes')
        return int(amount)
    except InvalidOperation as exc:
        raise ValueError('invalid quota') from exc


def cycle_bounds(now, reset_day, timezone):
    if now.tzinfo is None or not 1 <= reset_day <= 31:
        raise ValueError('timezone-aware time and reset day 1–31 required')
    zone = ZoneInfo(timezone)
    local = now.astimezone(zone)

    def boundary(year, month):
        return datetime(year, month, min(reset_day, calendar.monthrange(year, month)[1]), tzinfo=zone)

    def move(year, month, delta):
        index = year * 12 + month - 1 + delta
        return divmod(index, 12)[0], divmod(index, 12)[1] + 1

    start = boundary(local.year, local.month)
    if local < start:
        start = boundary(*move(local.year, local.month, -1))
    end = boundary(*move(start.year, start.month, 1))
    return start, end

class StatisticsUnavailable(Exception):
    pass


def query_usage(settings, now):
    import json
    import os
    import subprocess
    from datetime import date
    start, end = cycle_bounds(now, settings['reset_day'], settings['timezone'])
    env = dict(os.environ, TZ=settings['timezone'])
    try:
        output = subprocess.check_output(['vnstat', '--config', settings.get('vnstat_config', '/etc/raystack/vnstat.conf'), '--json', 'd', '0', '-i', settings['interface']], env=env, timeout=10)
        data = json.loads(output)
        interface = next(item for item in data['interfaces'] if item['name'] == settings['interface'])
        days = interface['traffic']['day']
        if not days:
            raise ValueError('empty statistics')
        upload = download = 0
        cycle_days = set()
        for item in days:
            d = item['date']
            day = date(d['year'], d['month'], d['day'])
            if start.date() <= day < end.date():
                if day in cycle_days:
                    raise ValueError("duplicate daily statistics")
                cycle_days.add(day)
                rx, tx = item['rx'], item['tx']
                if not isinstance(rx, int) or not isinstance(tx, int) or min(rx, tx) < 0:
                    raise ValueError('invalid counters')
                upload += rx
                download += tx
        if not cycle_days:
            raise ValueError('no statistics in current cycle')
        if settings['accounting'] == 'outbound':
            upload = 0
        elif settings['accounting'] != 'both':
            raise ValueError('invalid accounting mode')
        return {'upload': upload, 'download': download, 'total': settings['quota_bytes'], 'next_reset': int(end.timestamp())}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, StopIteration) as exc:
        raise StatisticsUnavailable('vnStat data unavailable') from exc
