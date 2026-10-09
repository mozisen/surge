"""Read-only client display using the pinned script's actual display templates."""
import hashlib
import ipaddress
import json
import re
import subprocess

from .runtime import ROOT, UPSTREAM_SHA
from .inventory import users_for
from vaio.common import PROTOCOL_CORES


def config_details(core, proto, row, params, connection_only=False):
    if core not in PROTOCOL_CORES.get(proto, ()):
        raise ValueError('不支持此协议配置详情')
    users = [u for u in users_for(row) if u.get('name') == params['name']]
    if len(users) != 1:
        raise ValueError('用户不存在或不唯一')
    source = (ROOT / 'vendor/vless-server.sh').read_bytes()
    if hashlib.sha256(source).hexdigest() != UPSTREAM_SHA:
        raise ValueError('脚本完整性校验失败')
    source = source.decode()
    display = re.search(r'^show_single_protocol_info\(\) \{\n.*?^\}', source, re.M | re.S)[0]
    fields = display.split('    # 从 JSON 提取字段\n', 1)[1].split('    # 重新获取连接地址', 1)[0]
    template = display.split('    case "$protocol" in\n', 1)[1].split('\n    esac', 1)[0]
    helper = re.search(r'^gen_snell_surge_line\(\) \{\n.*?^\}', source, re.M | re.S)[0]
    data = dict(row)
    # The CLI's top-level credential represents its default user; export the selected user.
    data.update(uuid=users[0]['uuid'], password=users[0]['uuid'], psk=users[0]['uuid'])
    if proto.startswith('snell'):
        data['version'] = {'snell': 4, 'snell-v5': 5, 'snell-v6': 6}[proto]
    host = params['host']
    config_ip = '[' + host + ']' if ':' in host else host
    functions = ['get_ip_suffix', 'gen_vless_link', 'gen_hy2_link', 'gen_trojan_link',
                 'gen_ss2022_link', 'gen_ss_legacy_link', 'gen_snell_link', 'gen_anytls_link']
    for name in functions:
        helper += '\n' + re.search(r'^' + name + r'\(\) \{\n.*?^\}', source, re.M | re.S)[0]
    helper += '\ngen_snell_v5_link() { gen_snell_link "$1" "$2" "$3" "${4:-5}" "$5"; }\n'
    link_template = display.split('        case "$protocol" in\n', 1)[1].split('\n        esac', 1)[0]
    shell = helper + '\nrender() {\nlocal protocol="$1" config_ip="$2" country_code="$3"\nlocal cfg; cfg=$(cat)\n' + fields + '\nlocal display_port="$port"\ncase "$protocol" in\n' + ('' if connection_only else template) + '\nesac\nlocal ip_addr="$config_ip" link_port="$port" link join_code\ncase "$protocol" in\n' + link_template + '\nesac\nprintf "%s\\n" "$link"\n}\nrender "$@"'
    result = subprocess.run(['bash', '-c', shell, 'vaio-details', proto, config_ip, row.get('country', 'XX')],
                            input=json.dumps(data), capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise ValueError('读取脚本配置模板失败')
    if connection_only:
        return result.stdout.strip()
    addresses = []
    for key in ('ipv4', 'ipv6'):
        if row.get(key):
            addresses.append(key.upper() + ': ' + str(row[key]))
    try:
        label = 'IPv' + str(ipaddress.ip_address(host).version)
    except ValueError:
        label = '连接域名'
    header = [f'{label}: {host}', '运行内核: ' + ('独立核心' if proto.startswith('snell') else 'Xray' if core == 'xray' else 'Sing-box'),
              f"端口: {row['port']}", '用户: ' + params['name']]
    header += [x for x in addresses if x != header[0]]
    return '\n'.join(header) + '\n' + result.stdout.rsplit('\n', 2)[0].strip() + '\n'
