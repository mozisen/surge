"""Persistent billing on top of the CLI's cumulative counters (never reset cores)."""
import datetime
import time


def cycle_key(day, today=None):
    today = today or datetime.date.today()
    start = today.replace(day=day)
    if today < start:
        start = (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=day)
    return start.isoformat()


def traffic_state(db, core, proto, row, now=None):
    now = time.time() if now is None else now
    if proto.startswith('snell'):
        at = (row.get('users') or [{}])[0].get('traffic_observed_at', 0)
    elif (core == 'xray' and proto in ('vless', 'trojan')) or (core == 'singbox' and proto in ('vless', 'trojan', 'hy2', 'anytls', 'tuic')):
        at = db.get('meta', {}).get('traffic_observed_' + core, 0)
    else:
        return 'unsupported'
    return 'ready' if isinstance(at, (int, float)) and 0 <= now - at <= 900 else 'unavailable'


def advance(user, today=None):
    if 'panel_quota' not in user:
        return
    raw = max(0, int(user.get('used', 0)))
    previous = user.get('panel_last_used', raw)
    delta = raw - previous if raw >= previous else raw
    day = user.get('panel_reset_day', 0)
    key = cycle_key(day, today) if day else 'total'
    # Crossing a boundary charges the unsampled interval to the new cycle.
    if key > user.get('panel_cycle', ''):
        user['panel_used'] = 0
        user['panel_cycle'] = key
    user['panel_used'] = max(0, user.get('panel_used', 0)) + delta
    user['panel_last_used'] = raw


def configure(user, params, today=None):
    if 'panel_quota' not in user:
        # Existing lifetime usage remains visible until the first monthly boundary.
        user.update(panel_quota=user.get('quota', 0), panel_used=user.get('used', 0),
                    panel_last_used=user.get('used', 0), panel_reset_day=0, panel_cycle='total')
    advance(user, today)
    if 'quota_gb' in params:
        user['panel_quota'] = params['quota_gb'] * 1073741824
    if 'reset_day' in params:
        user['panel_reset_day'] = params['reset_day']
        user['panel_cycle'] = cycle_key(params['reset_day'], today) if params['reset_day'] else 'total'
    # CLI collection continues; only the shared renderer enforces this policy.
    user['quota'] = 0


def effective_usage(user):
    if 'panel_quota' in user:
        current = dict(user)
        advance(current)
        return current['panel_used'], current['panel_quota']
    return user.get('used', 0), user.get('quota', 0)
