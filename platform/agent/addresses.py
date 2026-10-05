"""Bounded public-address discovery, shared by read-only exports."""
import concurrent.futures
import ipaddress
import json
import re
import subprocess
import time

_cache = None
_at = 0


def valid(value, family=None):
    try:
        ip = ipaddress.ip_address(value.strip().strip('[]'))
        return str(ip) if ip.is_global and (family is None or ip.version == family) else ''
    except ValueError:
        return ''


def curl(url, family=None):
    try:
        command = ['curl', '-fsS', '--connect-timeout', '1', '--max-time', '2']
        if family: command.append('-' + str(family))
        return subprocess.run(command + [url], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ''


def discover():
    global _cache, _at
    if _cache is not None and time.monotonic() - _at < 300:
        return dict(_cache)
    local = {}
    try:
        result = subprocess.run(['ip','-j','address','show','scope','global'], capture_output=True,text=True,timeout=2)
        for interface in json.loads(result.stdout):
            for info in interface.get('addr_info', []):
                address = valid(info.get('local', ''))
                if address: local.setdefault('ipv6' if ':' in address else 'ipv4', address)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [(family, pool.submit(curl, endpoint, family)) for family in (4,6)
                for endpoint in ('https://ip.sb','https://ifconfig.me')]
        found = {}
        for family, future in jobs:
            address = valid(future.result(),family)
            if address: found.setdefault('ipv'+str(family),address)
    for key, value in local.items(): found.setdefault(key,value)
    if not found:
        raise ValueError('Agent 未读取到可用公网 IP，请检查节点网络后重试')
    country = curl('https://ipinfo.io/' + (found.get('ipv4') or found['ipv6']) + '/country')
    found['country'] = country if re.fullmatch('[A-Z]{2}',country) else 'XX'
    _cache, _at = found, time.monotonic()
    return dict(found)
