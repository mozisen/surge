'use strict';
const $ = (s, root = document) => root.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
} [c]));
const icons = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    server: '<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.01M7 17.5h.01M15 6.5h3M15 17.5h3"/>',
    tasks: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2h6v2M9 10h6M9 14h6M9 18h3"/>',
    pulse: '<path d="M2 12h5l3-8 4 16 3-8h5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    back: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    forward: '<path d="M4 7h13M13 3l4 4-4 4M20 17H7M11 13l-4 4 4 4"/>',
    relay: '<circle cx="4.5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19.5" cy="12" r="2"/><path d="M6.5 12h3.5M14 12h3.5"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c5 5 5 13 0 18M12 3c-5 5-5 13 0 18"/>',
    refresh: '<path d="M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 13-3l2 3M4 16l2 3a8 8 0 0 0 13-3"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.server}</svg>`;
const states = {
    online: '在线',
    offline: '离线',
    pending: '待连接',
    revoked: '已撤销',
    running: '运行中',
    stopped: '已停止',
    unknown: '待核对',
    queued: '等待中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
    resolved: '已核对'
};
const badge = status => `<span class="badge ${esc(status)}">${esc(states[status] || status)}</span>`;
const names = {
    'ss-legacy': 'SS',
    ss2022: 'SS2022',
    vless: 'VLESS Reality',
    hy2: 'Hysteria2',
    trojan: 'Trojan',
    anytls: 'AnyTLS',
    snell: 'Snell v4',
    'snell-v5': 'Snell v5',
    'snell-v6': 'Snell v6',
    'vless-vision': 'VLESS Vision',
    'vless-ws': 'VLESS-WS',
    'vless-ws-notls': 'VLESS-WS（无 TLS）',
    'vless-xhttp': 'VLESS-XHTTP',
    'vless-xhttp-cdn': 'VLESS-XHTTP CDN',
    'vmess-ws': 'VMess-WS',
    'trojan-ws': 'Trojan-WS',
    tuic: 'TUIC',
    socks: 'SOCKS5',
    'snell-shadowtls': 'Snell + ShadowTLS',
    'snell-v5-shadowtls': 'Snell v5 + ShadowTLS',
    'ss2022-shadowtls': 'SS2022 + ShadowTLS',
    naive: 'NaïveProxy'
};
const actions = {
    install: '安装协议',
    update: '修改端口',
    delete: '卸载实例',
    restart: '重启服务',
    start: '启动服务',
    stop: '停止服务',
    user_add: '新增用户',
    user_update: '修改用户',
    user_delete: '删除用户',
    share: '配置信息',
    inspect: '检查实例',
    platform_apply: '平台用户同步',
    agent_upgrade: '一键升级',
    forward_apply: '端口转发',
    agent_set_url: '切换面板地址',
    core_update: '更新内核'
};
const coreLabels = {xray: 'Xray', singbox: 'Sing-box', 'snell-v5': 'Snell v5', 'snell-v6': 'Snell v6'};
// 内核更新任务的一行摘要：内核名 + 版本变化
const coreSummary = t => {
    const c = t.result?.core;
    return (coreLabels[t.request.params?.core] || '') + (c ? ' ' + (c.changed ? c.from + ' → ' + c.to : c.to) : '');
};
// 端口转发任务的一行摘要：操作 + 监听端口
const forwardSummary = t => {
    const op = t.request.params?.ops?.[0] || {}, rule = op.rule || op.base || {};
    return ({add: '新增', update: '修改', delete: '删除', enable: '启用', disable: '停用'}[op.op] || '') + ' ' + (rule.listen_port ? '监听 ' + rule.listen_port : '');
};
const bytes = n => n == null ? '—' : n >= 1073741824 ? (n / 1073741824).toFixed(1) + ' GiB' : n >= 1048576 ? (n / 1048576).toFixed(0) + ' MiB' : (n / 1024).toFixed(0) + ' KiB';
const date = n => n ? new Date(n * 1000).toLocaleString('zh-CN', {
    hour12: false
}) : '—';
const brand = `<div class="brand">VAIO</div>`;
let panelVersion = '',
    groupFilter = '',
    csrf = '',
    nodes = [],
    tasks = [],
    selected = null,
    detailTab = 'protocols',
    search = '',
    lastRefresh = '',
    authenticated = false;
let currentCommand = '',
    currentScript = '',
    activeTaskId = null,
    refreshBusy = false;

async function api(path, options = {}) {
    const response = await fetch('/api' + path, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': csrf,
            ...options.headers
        },
        credentials: 'same-origin'
    });
    const data = await response.json();
    if (!response.ok) {
        if (response.status === 401 && path !== '/login' && path !== '/session') {
            authenticated = false;
            login();
        }
        throw new Error(data.error || '请求失败');
    }
    return data;
}
const post = (path, data = {}, headers = {}) => api(path, {
    method: 'POST',
    body: JSON.stringify(data),
    headers
});

function toast(text) {
    const notice = $('#toast');
    notice.textContent = text;
    notice.style.display = 'block';
    // Native dialog lives in the top layer; z-index alone cannot place a toast above it.
    if (notice.showPopover) {
        notice.setAttribute('popover', 'manual');
        if (notice.matches(':popover-open')) notice.hidePopover();
        notice.showPopover();
    } else {
        ($('#modal').open ? $('#modal') : document.body).append(notice);
    }
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => {
        if (notice.hidePopover && notice.matches(':popover-open')) notice.hidePopover();
        notice.style.display = 'none';
    }, 4500);
}

function formatConfigDetails(text) {
    const seenAddresses = new Set();
    return String(text).split('\n').map(line => line.replace(/^ {2}/, '').replace(/^IPV([46]):/, 'IPv$1:'))
        .filter(line => {
            if (!/^IPv[46]:/.test(line)) return true;
            if (seenAddresses.has(line)) return false;
            seenAddresses.add(line);
            return true;
        }).join('\n');
}

function modal(title, body, wide = false, extraClass = '', back = null) {
    const dialog = $('#modal');
    if (dialog.contains($('#toast'))) document.body.append($('#toast'));
    dialog.className = [wide ? 'wide' : '', extraClass].filter(Boolean).join(' ');
    dialog.innerHTML = `<div class="modal-head"><h2 id="dialog-title">${esc(title)}</h2>${back ? `<button class="quiet modal-back" type="button" aria-label="返回" title="返回">${icon('back')}</button>` : ''}<button class="quiet" data-action="close" aria-label="关闭">${icon('close')}</button></div><div class="modal-body">${body}</div>`;
    if (back) dialog.querySelector('.modal-back').onclick = back;
    dialog.querySelectorAll('select').forEach(enhanceSelect);
    if (!dialog.open) dialog.showModal();
}

function formError(error) {
    const target = $('#modal .error');
    if (target) target.textContent = error.message;
    else toast(error.message);
}

function login() {
    $('#modal').close();
    $('#app').innerHTML = `<main class="login-page"><header class="login-header">${brand}</header><section class="login-form"><form class="login-box" id="login-form"><h2>登录</h2><p class="subtext">管理员或已开通登录的用户，输入账号和密码。</p><label for="username">账号</label><input id="username" required autocomplete="username" maxlength="32"><label for="password">密码</label><input id="password" type="password" required autocomplete="current-password" placeholder="输入管理员密码"><button class="primary" type="submit">登录 ${icon('arrow')}</button><div class="error" role="alert"></div></form></section></main>`;
    $('#login-form').addEventListener('submit', async e => {
        e.preventDefault();
        const button = $('button', e.target);
        button.disabled = true;
        try {
            const data = await post('/login', {
                username: $('#username').value,
                password: $('#password').value
            });
            csrf = data.csrf;
            panelVersion = data.version;
            if (data.role === 'user') return await portal();
            authenticated = true;
            await refresh();
        } catch (err) {
            $('.error', e.target).textContent = err.message;
        } finally {
            button.disabled = false;
        }
    });
}

function shell(content, section) {
    checkPanelUpdate();
    const links = [['overview', 'grid', '总览'], ['nodes', 'server', '服务器'], ['instances', 'globe', '节点管理'], ['relays', 'relay', '中转管理'], ['forwards', 'forward', '端口转发'], ['users', 'users', '用户管理'], ['traffic', 'pulse', '流量统计'], ['monitor', 'pulse', '通知配置'], ['tasks', 'tasks', '任务记录'], ['audit', 'shield', '操作审计']];
    const nav = links.map(([id, ico, text]) => `<a href="#${id}" class="${section===id?'active':''}"${section===id?' aria-current="page"':''}>${icon(ico)}${text}</a>`).join('');
    $('#app').innerHTML = `<div class="shell"><aside class="sidebar">${brand}<nav class="nav" aria-label="主导航">${nav}</nav><div class="sidebar-foot"><div class="account-actions"><button class="quiet small" data-action="settings">系统设置</button><button class="quiet small" data-action="panel-update">${panelUpdateLabel()}</button><button class="quiet small" data-action="logout">退出</button></div></div></aside><main class="main">${content}</main></div>`;
}

// Readout value: number large, unit set apart in small muted type.
function reading(value, unit = '') {
    return `<span class="reading-value">${value}</span>${unit?`<span class="reading-unit">${unit}</span>`:''}`;
}

function stat(title, value, foot, unit = '', positive = false) {
    return `<div class="stat"><div class="stat-label">${title}</div><div class="stat-value">${reading(value, unit)}</div><div class="stat-foot ${positive?'positive':''}">${foot}</div></div>`;
}

function summary() {
    const online = nodes.filter(n => n.status === 'online').length;
    const count = nodes.reduce((s, n) => s + (n.snapshot.instances || []).length, 0);
    return `<div class="stats">${stat('服务器',nodes.length,'集中管理你的基础设施')}${stat('当前在线',online,online ? '心跳连接正常' : '等待节点建立连接','',!!online)}${stat('协议实例',count,'按协议和监听端口独立识别')}${stat('进行中的任务',tasks.filter(t=>['running','queued'].includes(t.status)).length,'执行过程与结果可追溯')}</div>`;
}

function emptyNodes() {
    return `<div class="panel"><div class="empty"><h3>连接你的第一台服务器</h3><p>为服务器生成专属安装脚本。在节点执行后，它会自动出现在这里；确认接管后即可管理协议。</p><button class="primary" data-action="add-node">${icon('plus')}添加服务器</button></div><ol class="onboarding"><li class="step"><span class="step-number">1</span><div><b>添加节点</b><p>设置名称与分组</p></div></li><li class="step"><span class="step-number">2</span><div><b>运行安装脚本</b><p>节点主动连接主面板</p></div></li><li class="step"><span class="step-number">3</span><div><b>开始集中管理</b><p>识别现有配置并确认接管</p></div></li></ol></div>`;
}

// 10-segment usage bar; unknown values render empty segments and "—".
function meter(label, percent) {
    const known = Number.isFinite(percent);
    const value = known ? Math.max(0, Math.min(100, percent)) : null;
    const filled = known ? Math.max(value > 0 ? 1 : 0, Math.round(value / 10)) : 0;
    const segments = Array.from({length: 10}, (_, i) => `<i${i < filled ? ' class="on"' : ''}></i>`).join('');
    // role="meter" requires aria-valuenow, so an unknown value hides the bar and leaves the visible "—".
    const bar = known ? `role="meter" aria-label="${label}使用率" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${value.toFixed(0)}"` : 'aria-hidden="true"';
    return `<div class="meter"><span class="meter-label">${label}</span><span class="meter-bar" ${bar}>${segments}</span><span class="meter-value">${known?value.toFixed(0)+'%':'—'}</span></div>`;
}

function card(node) {
    const s = node.snapshot,
        m = s.metrics || {},
        instances = s.instances || [];
    const memory = m.memory_total ? m.memory_used / m.memory_total * 100 : null;
    const disk = m.disk_total ? m.disk_used / m.disk_total * 100 : null;
    return `<article class="node-row ${esc(node.status)}"><div class="node-state">${badge(node.status)}</div><div class="node-name"><h3><a href="#nodes/${node.id}">${esc(node.name)}</a></h3><div class="node-sub"><span>${esc(node.group_name)}</span><span>${esc(s.hostname || '等待首次连接')}</span></div></div><div class="node-meters">${meter('内存', memory)}${meter('磁盘', disk)}</div><div class="node-traffic"><span>接收 ${trafficValue(m.network_rx)}</span><span>发送 ${trafficValue(m.network_tx)}</span></div>${nodeVersion(node)}<div class="node-count">${instances.length} 个实例 ${icon('arrow')}</div></article>`;
}

function nodeCards() {
    const filtered = nodes.filter(n => (!groupFilter || n.group_name === groupFilter) && (n.name + ' ' + n.group_name + ' ' + (n.snapshot.hostname || '')).toLowerCase().includes(search.toLowerCase()));
    return filtered.length ? `<div class="node-list">${filtered.map(card).join('')}</div>` : '<div class="panel empty"><p>没有匹配的服务器。</p></div>';
}

function taskTable(list) {
    return list.length ? `<div class="table-wrap"><table><thead><tr><th>操作 / 实例</th><th>服务器</th><th>状态</th><th>创建时间</th><th>结果</th></tr></thead><tbody>${list.map(t=>`<tr><td><strong>${esc(actions[t.action]||t.action)}</strong><br><span class="muted mono">${t.action==='platform_apply'?(t.request.params?.ops||[]).length+' 项统一用户操作':t.action==='agent_upgrade'?'节点程序与节点脚本':t.action==='core_update'?esc(coreSummary(t)):t.action==='forward_apply'?esc(forwardSummary(t)):t.action==='agent_set_url'?esc(t.request.params?.url||''):esc(t.request.protocol)+' : '+t.request.port}</span></td><td>${esc(t.node_name)}</td><td>${badge(t.status)}</td><td class="muted">${date(t.created)}</td><td><button class="small" data-action="task" data-id="${t.id}">查看记录</button>${t.status==='unknown'?` <button class="small" data-action="resolve-task" data-id="${t.id}">核对结果</button>`:''}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty"><p>暂无任务。节点上的操作会在这里留下记录。</p></div>';
}

let overviewSummary = null;
// Overview: summary cards only (servers, online, instances, users, relay lines, today / this month traffic of all servers).
function overviewPage() {
    const online = nodes.filter(n => n.status === 'online').length;
    const instances = nodes.reduce((sum, n) => sum + (n.snapshot.instances || []).length, 0);
    const sm = overviewSummary;
    const traffic = (label, t) => {
        if (!t) return stat(label, '—', '统计加载中');
        const [value, unit] = bytes(t.rx + t.tx).split(' ');
        return stat(label, value, `接收 ${bytes(t.rx)} · 发送 ${bytes(t.tx)}`, unit || '');
    };
    shell(`<div class="overview-cards">${stat('服务器', nodes.length, nodes.filter(n => n.status === 'pending').length + ' 台待连接')}${stat('当前在线', online, online ? '心跳连接正常' : '等待节点建立连接', '', !!online)}${stat('协议实例', instances, '按协议和监听端口识别')}${stat('用户', sm ? sm.users : '—', '平台用户')}${stat('中转线路', sm ? sm.relays : '—', '用户经中转连接落地协议')}${traffic('今日流量', sm?.today)}${traffic('本月流量', sm?.month)}</div><p class="helper overview-note">流量为所有服务器网卡接收与发送之和（包含系统其他流量），按面板时区计算。</p>`, 'overview');
    api('/summary').then(d => {
        const changed = JSON.stringify(d) !== JSON.stringify(overviewSummary);
        overviewSummary = d;
        if (changed && (location.hash.slice(1) || 'overview') === 'overview' && $('.overview-cards')) overviewPage();
    }).catch(() => {});
}

function overview(section) {
    if (section === 'overview') return overviewPage();
    shell(`<div class="heading"><div><h1>服务器</h1></div><div class="action-row"><button data-action="core-update-all">一键更新内核</button><button data-action="upgrade-all"${nodes.some(n=>n.adopted&&n.upgrade_available)?'':' disabled title="所有节点程序已是最新"'}>一键更新节点程序</button><button class="primary" data-action="add-node">${icon('plus')}添加服务器</button></div></div>${summary()}<div class="section-label"><h2>我的服务器 <span class="count">${nodes.length}</span></h2><div class="tools"><button class="quiet small" data-action="trash">回收站</button>${filterMenu('group-filter', '筛选分组', [['', '全部分组'], ...[...new Set(nodes.map(n=>n.group_name).filter(Boolean))].map(g=>[g, g])], groupFilter)}<div class="search">${icon('search')}<input id="search" type="search" aria-label="搜索服务器" placeholder="搜索名称或分组" value="${esc(search)}"></div></div></div><div id="node-results">${nodes.length?nodeCards():emptyNodes()}</div>`, section);
    $('#group-filter').onchange = e => { groupFilter = e.target.value; $('#node-results').innerHTML = nodeCards(); };
    $('#search').addEventListener('input', e => {
        search = e.target.value;
        $('#node-results').innerHTML = nodeCards();
    });
}

let trafficNodeId = '';
function trafficUsage(instance) {
    const supported = instance.traffic_state !== 'unsupported';
    const users = instance.users || [];
    const total = users.reduce((sum,u)=>sum+(Number.isFinite(u.used)&&u.used>=0?u.used:0),0);
    return {value: supported && (instance.traffic_state === 'ready' || total > 0) ? total : null,
        ready: instance.traffic_state === 'ready', supported};
}
function trafficValue(value) { return Number.isFinite(value) && value >= 0 ? (value < 1024 ? value + ' B' : bytes(value)) : '—'; }
function trafficStatus(instance, node) {
    if (instance.traffic_state === 'unsupported') return '暂不支持统计';
    if (node.status !== 'online') return '离线快照';
    return instance.traffic_state === 'ready' ? '正常' : '等待有效采样';
}
function trafficTotal(instances) {
    const data = instances.map(trafficUsage), known = data.filter(x=>x.value !== null);
    return {value:known.length ? known.reduce((sum,x)=>sum+x.value,0) : null,
        partial: data.some(x=>!x.ready), count: known.length, all: data.length};
}
function trafficPage() {
    const node = nodes.find(n=>n.id===trafficNodeId) || nodes[0];
    const instances = node?.snapshot.instances || [];
    const total = trafficTotal(instances);
    const coreName = p => p.protocol.startsWith('snell') ? '独立核心' : p.core==='singbox' ? 'Sing-box' : 'Xray';
    shell(`<div class="heading"><div><h1>流量统计</h1></div><button data-action="refresh">${icon('refresh')}刷新</button></div>
    <div class="section-label"><h2>服务器流量</h2></div><div class="panel table-wrap"><table><thead><tr><th>服务器</th><th>状态</th><th class="num">网卡接收</th><th class="num">网卡发送</th><th class="num">网卡合计</th><th class="num">用户用量汇总</th><th>上报时间</th></tr></thead><tbody>${nodes.map(n=>{
        const m=n.snapshot.metrics||{}, sum=trafficTotal(n.snapshot.instances||[]);
        const network = Number.isFinite(m.network_rx)&&Number.isFinite(m.network_tx)?m.network_rx+m.network_tx:null;
        return `<tr><td><button class="quiet small" data-action="traffic-node" data-id="${esc(n.id)}" ${n.id===node?.id?'aria-current="true"':''}>${esc(n.name)}</button></td><td>${badge(n.status)}</td><td class="num">${trafficValue(m.network_rx)}</td><td class="num">${trafficValue(m.network_tx)}</td><td class="num">${trafficValue(network)}</td><td class="num">${trafficValue(sum.value)}${sum.partial?'<br><span class="muted">部分统计可用</span>':''}</td><td>${date(n.last_seen)}${n.status!=='online'?'<br><span class="muted">离线快照</span>':''}</td></tr>`;
    }).join('')||'<tr><td colspan="7">暂无服务器</td></tr>'}</tbody></table></div>
    <p class="helper traffic-note">网卡收发量来自系统累计计数，包含其他服务与虚拟网卡流量，重启或接口重建可能清零；不等同于代理用户用量或服务商账单。</p>
    ${node?`<div class="section-label"><h2>${esc(node.name)} · 协议流量</h2><div class="section-meta"><span>用户用量汇总 ${trafficValue(total.value)}${total.partial?'（部分统计）':''}</span><a href="#nodes/${esc(node.id)}">管理服务器 →</a></div></div>
    <div class="panel table-wrap"><table><thead><tr><th>协议 / 内核</th><th class="num">端口</th><th class="num">用户数</th><th class="num">用户用量合计</th><th>统计状态</th></tr></thead><tbody>${instances.map(p=>`<tr><td><strong>${esc(names[p.protocol]||p.protocol)}</strong><br><span class="muted">${coreName(p)}</span></td><td class="num mono">${p.port}</td><td class="num">${(p.users||[]).length}</td><td class="num">${trafficValue(trafficUsage(p).value)}</td><td>${trafficStatus(p,node)}</td></tr>`).join('')||'<tr><td colspan="5">暂无协议实例</td></tr>'}</tbody></table></div>
    <div class="section-label"><h2>用户流量</h2></div><div class="panel table-wrap"><table><thead><tr><th>用户</th><th>协议 / 端口</th><th class="num">当前用量</th><th class="num">配额</th><th class="num">剩余</th><th>统计周期</th><th>统计状态</th></tr></thead><tbody>${instances.flatMap(p=>(p.users||[]).map(u=>{
        const available=p.traffic_state!=='unsupported'&&(p.traffic_state==='ready'||u.used>0);
        return `<tr><td>${esc(u.name)}</td><td>${esc(names[p.protocol]||p.protocol)} · ${p.port}<br><span class="muted">${coreName(p)}</span></td><td class="num">${available?trafficValue(u.used):'—'}</td><td class="num">${u.quota?bytes(u.quota):'不限'}</td><td class="num">${available&&u.quota?bytes(Math.max(0,u.quota-u.used)):u.quota?'—':'不限'}</td><td>${u.reset_day?`每月 ${u.reset_day} 日重置`:'累计（按脚本计数）'}</td><td>${trafficStatus(p,node)}${available&&u.quota&&u.used>=u.quota?'<br>已达配额':''}</td></tr>`;
    })).join('')||'<tr><td colspan="7">暂无用户</td></tr>'}</tbody></table></div>
    <p class="helper traffic-note">协议与服务器的用户用量合计为当前用户计费周期之和，不同用户的重置日可能不同，删除的用户不计入。用户统计来自节点脚本采样；暂不提供未采集的上传、下载拆分。等待采样时如有历史值，会保留显示；“—”表示未获得数据。</p>`:''}`, 'traffic');
}

function protocolTable(node) {
    const instances = node.snapshot.instances || [];
    return instances.length ? `<div class="table-wrap"><table><thead><tr><th>协议 / 内核</th><th class="num">监听端口</th><th>服务状态</th><th class="num">用户</th><th class="num">用户用量合计</th><th>管理</th></tr></thead><tbody>${instances.map((p,index)=>`<tr><td><strong>${esc(names[p.protocol]||p.protocol)}</strong><br><span class="muted">${esc(p.core==='xray'&&!p.protocol.startsWith('snell')?'Xray':p.core==='singbox'?'Sing-box':'独立进程')}</span></td><td class="num mono">${p.port}</td><td>${badge(p.status)}</td><td class="num">${(p.users||[]).length} 位</td><td class="num">${trafficValue(trafficUsage(p).value)}<br><span class="muted">${trafficStatus(p,node)}</span></td><td><button class="small" data-action="instance" data-index="${index}">${p.managed?'管理实例':'查看实例'}</button></td></tr>`).join('')}</tbody></table></div>` : `<div class="empty"><div class="empty-icon">${icon('globe')}</div><h3>尚未发现协议实例</h3><p>确认接管后，可选择节点支持的协议进行安装。</p><button class="primary" data-action="install" ${!node.adopted||node.status!=='online'||node.maintenance?'disabled':''}>${icon('plus')}安装协议</button></div>`;
}

function detail(node) {
    selected = node;
    const s = node.snapshot,
        m = s.metrics || {};
    shell(`<div class="heading"><div><a class="back-link" href="#nodes">返回服务器</a><h1>${esc(node.name)} ${badge(node.status)}</h1><div class="detail-info"><span>${esc(node.group_name)}</span><span>${esc(s.hostname||'等待连接')}</span><span>${esc(s.arch||'—')}</span><span>节点程序 ${esc(s.agent_version||'—')}</span></div></div><div class="action-row">${node.upgrade_available?`<button data-action="upgrade-agent" title="节点程序 ${esc(s.agent_version)}，当前面板 ${esc(node.panel_version)}">${s.upgrade_version===1&&node.status==='online'?'一键升级':'升级节点'}</button>`:''}<button data-action="history">历史曲线</button><button data-action="node-settings">节点设置</button><button class="primary" data-action="install" ${!node.adopted||node.status!=='online'||node.maintenance?'disabled':''}>${icon('plus')}安装协议</button></div></div>${node.maintenance || node.status!=='online' || s.error?`<div class="notice warn">${esc(node.connection_hint)}</div>`:''}${node.notes?`<div class="notice node-notes">${esc(node.notes)}</div>`:''}${authorityNotice(node)}${!node.adopted?`<div class="notice"><div><strong>${node.status==='pending'?'等待节点连接':'配置已识别，尚未接管'}</strong><br>${node.status==='pending'?'在服务器运行安装脚本，节点将自动上线。':'请检查下面的协议与端口。接管后面板可以修改节点配置。'}</div><button data-action="${node.status==='pending'?'renew':'adopt'}" ${node.status==='offline'?'disabled':''}>${node.status==='pending'?'重新生成脚本':'确认接管'}</button></div>`:''}<div class="stats">${stat('系统负载',m.load??'—',`${m.cpu_count||'—'} 个逻辑核心`)}${stat('内存使用',m.memory_total?(m.memory_used/m.memory_total*100).toFixed(0):'—',bytes(m.memory_used)+' / '+bytes(m.memory_total),m.memory_total?'%':'')}${stat('磁盘使用',m.disk_total?(m.disk_used/m.disk_total*100).toFixed(0):'—',bytes(m.disk_used)+' / '+bytes(m.disk_total),m.disk_total?'%':'')}${stat('协议实例',(s.instances||[]).length,'配置以节点实际状态为准')}</div><div class="tabs"><button data-action="tab" data-tab="protocols" class="${detailTab==='protocols'?'active':''}">协议管理</button><button data-action="tab" data-tab="tasks" class="${detailTab==='tasks'?'active':''}">执行记录</button></div><div class="split"><section><div class="panel"><div class="panel-head"><h2>${detailTab==='protocols'?'已安装协议':'节点任务'} <span class="count">${detailTab==='protocols'?(s.instances||[]).length:tasks.filter(t=>t.node_id===node.id).length}</span></h2><button class="quiet small" data-action="refresh">${icon('refresh')}刷新</button></div>${detailTab==='protocols'?protocolTable(node):taskTable(tasks.filter(t=>t.node_id===node.id))}</div></section><aside class="detail-aside">${authorityBlock(node)}${coreBlock(node)}<section class="info-block"><h3>节点信息</h3>${s.script_api?`<div class="kv"><span>脚本接口</span><span>${s.script_api.status==='ready'?'只读预览':'暂不可用'}</span></div><p class="helper">${s.script_api.status==='ready'?`${esc(s.script_api.version)} · ${Number(s.script_api.protocol_count)||0} 种协议与内核组合。新增协议写接口尚未开放。`:'接口检查失败，请查看节点依赖及脚本校验。'}现有管理功能使用已验收的独立适配器。</p>`:''}<div class="kv"><span>系统</span><span>${esc(s.os||'—')}</span></div><div class="kv"><span>运行时间</span><span>${m.uptime?Math.floor(m.uptime/86400)+' 天':'—'}</span></div><div class="kv"><span>网卡累计接收</span><span>${bytes(m.network_rx)}</span></div><div class="kv"><span>网卡累计发送</span><span>${bytes(m.network_tx)}</span></div><div class="kv"><span>最后心跳</span><span>${date(node.last_seen)}</span></div><div class="kv"><span>流量同步</span><span>${esc(({ok:'正常',unavailable:'暂不可用',stale:'等待同步',error:'同步异常',unknown:'未知',no_core:'未找到内核',no_stats:'暂无统计',snell_error:'Snell 同步失败',singbox_error:'Sing-box 同步失败',partial_singbox_error:'部分统计失败',temp_error:'临时文件错误'})[s.traffic_status]||'暂不可用')}</span></div></section><section class="info-block"><h3>${icon('shield')} 操作说明</h3><p>共享核心的配置修改会重启对应核心，可能短暂影响同服务的其他协议。</p><p>不支持写入的协议仅展示状态。配置备份保留在节点本地。</p></section></aside></div>`, 'nodes');
}
async function render() {
    const route = location.hash.slice(1) || 'overview';
    if (route.startsWith('nodes/')) {
        const node = nodes.find(n => n.id === route.split('/')[1]);
        if (node) detail(node);
        else shell('<div class="empty"><h3>节点不存在</h3><a href="#nodes">返回节点列表</a></div>', 'nodes');
    } else if (route === 'tasks') {
        shell(`<div class="heading"><div><h1>任务记录</h1></div><button data-action="refresh">${icon('refresh')}刷新</button></div><div class="notice">执行结果未确认的任务不会自动重试。请检查节点实际状态后再发起新操作。</div><div class="panel">${taskTable(tasks)}</div>`, 'tasks');
    } else if (route === 'users') {
        await usersPage();
    } else if (route.startsWith('users/')) {
        await userDetail(route.split('/')[1]);
    } else if (route === 'relays') {
        await relaysPage();
    } else if (route === 'forwards') {
        forwardsPage();
    } else if (route === 'instances') {
        instancesPage();
    } else if (route === 'traffic') {
        trafficPage();
        await userTraffic();
    } else if (route === 'monitor') {
        await monitorPage();
    } else if (route === 'audit') {
        const data = await api('/audit');
        shell(`<div class="heading"><div><h1>操作审计</h1></div></div><div class="panel"><div class="table-wrap"><table><thead><tr><th>时间</th><th>事件</th><th>节点</th><th>说明</th></tr></thead><tbody>${data.events.map(e=>`<tr><td class="muted">${date(e.at)}</td><td class="mono">${esc(e.event)}</td><td>${esc(nodes.find(n=>n.id===e.node_id)?.name||'—')}</td><td>${esc(e.detail)}</td></tr>`).join('')}</tbody></table></div></div>`, 'audit');
    } else overview(route === 'nodes' ? 'nodes' : 'overview');
}
async function refresh() {
    if (refreshBusy || !authenticated) return;
    refreshBusy = true;
    try {
        const [n, t] = await Promise.all([api('/nodes'), api('/tasks')]);
        nodes = n.nodes;
        tasks = t.tasks;
        lastRefresh = new Date().toLocaleTimeString('zh-CN', {
            hour12: false
        });
        if (!['search', 'instance-search', 'forward-search', 'relay-search'].includes(document.activeElement?.id) && !document.querySelector('.filter-menu.open')) await render();
        if (activeTaskId && $('#modal').open) showTask(activeTaskId);
    } catch (err) {
        toast(err.message);
    } finally {
        refreshBusy = false;
    }
}

function enrollment(data) {
    currentScript = data.script;
    currentCommand = data.command;
    modal('连接服务器', `<p>在目标服务器以 root 粘贴执行以下命令，完成后节点自动上线。</p><label for="install-command">安装命令</label><textarea id="install-command" readonly rows="5">${esc(data.command)}</textarea><p class="helper">凭据 30 分钟内有效，注册一次后失效；请勿分享此命令。服务器需已安装 curl。</p><div class="modal-foot"><button data-action="download-script">下载脚本</button><button class="primary" data-action="copy-command">复制安装命令</button></div>`, true);
}

async function accountSettings() {
    const session = await api('/session');
    modal('系统设置', `${settingsTabs('account')}<form id="account-form"><label for="account-name">管理员账号</label><input id="account-name" name="username" value="${esc(session.username)}" required minlength="3" maxlength="32" pattern="[A-Za-z0-9_.\\-]{3,32}" autocomplete="username"><p class="helper">3–32 位字母、数字、点、下划线或短横线。</p><label for="current-password">当前密码</label><input id="current-password" name="current_password" type="password" required autocomplete="current-password"><label for="new-password">新密码</label><input id="new-password" name="new_password" type="password" minlength="8" maxlength="128" autocomplete="new-password"><p class="helper">留空表示只修改账号；新密码至少 8 位。</p><label for="confirm-password">确认新密码</label><input id="confirm-password" name="confirm_password" type="password" maxlength="128" autocomplete="new-password"><p>保存后所有已登录会话退出，请使用新的账号信息重新登录。</p><div class="error" role="alert"></div><div class="modal-foot"><button type="button" data-action="close">取消</button><button class="primary" type="submit">保存修改</button></div></form>`);
    $('#account-form').onsubmit = async e => {
        e.preventDefault();
        const button = $('[type=submit]', e.target);
        const data = Object.fromEntries(new FormData(e.target));
        if (data.new_password !== data.confirm_password) {
            formError(new Error('两次输入的新密码不一致'));
            return;
        }
        button.disabled = true;
        try {
            await post('/account', data);
            authenticated = false;
            csrf = '';
            $('#modal').close();
            login();
            $('#username').value = data.username;
            toast('登录信息已修改，请重新登录');
        } catch (err) {
            formError(err);
        } finally {
            button.disabled = false;
        }
    };
}

function nodeSettings() {
    const node = selected;
    modal('节点设置', `<form id="node-settings-form"><label for="settings-name">服务器名称</label><input id="settings-name" name="name" value="${esc(node.name)}" maxlength="80" required><label for="settings-group">分组</label><input id="settings-group" name="group_name" value="${esc(node.group_name)}" maxlength="40"><label for="settings-notes">备注</label><textarea id="settings-notes" name="notes" maxlength="1000">${esc(node.notes)}</textarea><div class="error" role="alert"></div><div class="modal-foot"><button type="submit" class="primary">保存信息</button></div></form><hr><p>节点版本 ${esc(node.snapshot.agent_version||'未上报')}，面板版本 ${esc(node.panel_version)}。</p><div class="action-row"><button data-action="upgrade-agent">升级节点程序</button><button data-action="renew" ${node.maintenance?'disabled':''}>重新注册</button><button data-action="revoke" ${node.maintenance?'disabled':''}>撤销身份</button><button class="danger" data-action="delete-node" ${node.maintenance?'disabled':''}>删除节点</button></div><p class="helper">删除节点将撤销连接并移入回收站，保留历史记录；不会卸载服务器上的代理。</p>`);
    $('#node-settings-form').onsubmit = async e => {
        e.preventDefault();
        const b = $('[type=submit]', e.target); b.disabled = true;
        try { await post('/nodes/'+node.id+'/settings',Object.fromEntries(new FormData(e.target))); $('#modal').close(); await refresh(); toast('节点信息已保存'); }
        catch (err) { formError(err); b.disabled=false; }
    };
}
async function showTrash() {
    const data = await api('/nodes?deleted=1');
    modal('节点回收站', `<p>恢复后保留原记录，但需要重新注册节点；旧连接凭据不会恢复。</p>${data.nodes.length?data.nodes.map(n=>`<div class="trash-row"><span>${esc(n.name)}</span><button data-action="restore-node" data-id="${n.id}">恢复记录</button></div>`).join(''):'<p>回收站为空。</p>'}`);
}
function deleteNode() {
    const node = selected;
    modal('删除节点', `<p>将 ${esc(node.name)} 移入回收站并撤销连接？此操作不会卸载任何协议。</p><div class="error"></div><div class="modal-foot"><button data-action="close">取消</button><button id="confirm-delete-node" class="danger">移入回收站</button></div>`);
    $('#confirm-delete-node').onclick = async e => {
        e.target.disabled=true;
        try { await post('/nodes/'+node.id+'/delete'); $('#modal').close(); location.hash='nodes'; await refresh(); }
        catch (err) { formError(err); e.target.disabled=false; }
    };
}
function resolveTask(id) {
    activeTaskId=null;
    modal('核对执行结果', `<form id="resolve-form"><p>请先在节点核对实际配置、服务和备份。此操作只记录核对结果，不重新执行任务。</p><label for="resolve-note">核对说明</label><textarea id="resolve-note" required maxlength="500"></textarea><div class="error"></div><div class="modal-foot"><button class="primary" type="submit">标记已核对</button></div></form>`);
    $('#resolve-form').onsubmit = async e => {
        e.preventDefault();
        try { await post('/tasks/'+id+'/resolve',{note:$('#resolve-note').value}); $('#modal').close(); await refresh(); }
        catch(err) { formError(err); }
    };
}

function addNode() {
    modal('添加服务器', `<form id="node-form"><p>填写名称后，复制一条命令到服务器执行即可。</p><label for="node-name">服务器名称</label><input id="node-name" name="name" required maxlength="80" placeholder="例如：香港 · 主节点" autocomplete="off"><label for="node-group">分组</label><input id="node-group" name="group_name" maxlength="40" value="默认分组"><div class="error" role="alert"></div><div class="modal-foot"><button type="button" data-action="close">取消</button><button class="primary" type="submit">生成安装命令 ${icon('arrow')}</button></div></form>`);
    $('#node-form').addEventListener('submit', async e => {
        e.preventDefault();
        const b = $('[type=submit]', e.target);
        b.disabled = true;
        try {
            const data = await post('/nodes', Object.fromEntries(new FormData(e.target)));
            enrollment(data);
            await refresh();
        } catch (err) {
            formError(err);
        } finally {
            b.disabled = false;
        }
    });
}

function showInstance(index) {
    activeTaskId = null;
    const p = selected.snapshot.instances[index];
    if (!p) return;
    const writable = p.managed && selected.adopted && selected.status === 'online' && !selected.maintenance;
    // Nodes reporting a user authority take no user edits here: script mode is read-only, platform mode uses 用户管理.
    const locked = selected.snapshot.authority_version === 1, platform = selected.snapshot.user_authority === 'platform';
    const shareable = (p.managed || (selected.snapshot.share_version === 2 && p.user_available)) && selected.status === 'online';
    modal(`${names[p.protocol]||p.protocol} · ${p.port}`, `<p class="instance-service">服务：<code>${esc(p.service)}</code> ${badge(p.status)}</p>${p.user_mode?`<p class="helper">用户：${esc(userModeText(p))}</p>`:''}${!p.managed?'<div class="notice warn">此实例尚未适配安全写入，当前仅可查看；安装列表按节点已声明的协议与内核能力展示。</div>':''}<div class="action-row"><button data-action="edit-port" data-index="${index}" ${writable?'':'disabled'}>修改端口</button><button data-action="${p.status==='running'?'stop':'start'}" data-index="${index}" ${writable?'':'disabled'}>${p.status==='running'?'停止服务':'启动服务'}</button><button data-action="restart" data-index="${index}" ${writable?'':'disabled'}>重启服务</button><button class="danger" data-action="delete" data-index="${index}" ${writable?'':'disabled'}>卸载此实例</button></div><label>实例用户</label><div class="table-wrap"><table><thead><tr><th>用户</th><th>已用 / 配额</th><th>状态</th><th>操作</th></tr></thead><tbody>${(p.users||[]).map((u,i)=>`<tr><td><strong>${esc(u.name)}</strong><br><span class="muted">${esc(u.expire_date||'永不过期')}</span>${u.account_id?`<br><span class="muted">统一用户 ${esc(selected.snapshot.accounts?.[u.account_id]?.name||'')}</span>`:''}</td><td>${p.traffic_state==='ready'?bytes(u.used):'统计不可用'} / ${u.quota?bytes(u.quota):'不限'}${u.reset_day?`<br><span class="muted">每月 ${u.reset_day} 日重置</span>`:''}</td><td>${badge(u.enabled?'running':'stopped')}${u.quota&&u.used>=u.quota?'<br>已超额':u.expire_date&&u.expire_date<new Date().toLocaleDateString('sv')?'<br>已到期':''}</td><td>${locked?(platform?`<a class="small-link" href="#users">在用户管理中修改</a>`:'<span class="small-link muted">由节点脚本管理</span>'):u.account_id?`<a class="small-link" href="#users">在用户管理中修改</a>`:`<button class="small" data-action="edit-user" data-index="${index}" data-user="${i}" ${writable?'':'disabled'}>编辑</button>`}<button class="small" data-action="share" data-index="${index}" data-user="${i}" ${shareable?'':'disabled'}>配置信息</button></td></tr>`).join('')}</tbody></table></div><p class="helper">${locked?(platform?'该节点的用户由平台「用户管理」管理。':'该节点的用户由节点脚本管理，面板只读；可在节点详情中切换为平台管理。'):''}用户流量来自节点数据库，依赖原脚本统计任务；无统计接口时不代表真实用量为零。</p><div class="modal-foot"><button data-action="add-user" data-index="${index}" ${writable&&!locked&&!p.protocol.startsWith('snell')&&!['ss-legacy','ss2022'].includes(p.protocol)?'':'disabled'}>新增用户</button><button data-action="close">关闭</button></div>`, true);
}
async function submitTask(action, p, params = {}, node = selected) {
    const data = await post('/nodes/' + node.id + '/tasks', {
        action,
        protocol: p.protocol,
        core: p.core,
        port: p.port,
        params,
        revision: node.snapshot.revision
    }, {
        'Idempotency-Key': crypto.randomUUID()
    });
    activeTaskId = data.id;
    await refresh();
    showTask(data.id);
}

function showTask(id) {
    activeTaskId = id;
    const t = tasks.find(t => t.id === id);
    if (!t) {
        modal('任务已提交', '<p>等待节点领取任务…</p>');
        return;
    }
    const r = t.result || {};
    modal(t.action === 'share' ? '协议配置详情' : actions[t.action] + ' · 执行记录', `<p class="task-head">${badge(t.status)} <span class="mono">${t.action==='platform_apply'?(t.request.params?.ops||[]).map(o=>esc(o.op)).join(', '):t.action==='agent_upgrade'?'节点程序与节点脚本':t.action==='core_update'?esc(coreSummary(t)):t.action==='forward_apply'?esc(forwardSummary(t)):t.action==='agent_set_url'?esc(t.request.params?.url||''):esc(t.request.protocol)+':'+t.request.port}</span> · ${esc(t.node_name)}</p><div class="kv"><span>创建时间</span><span>${date(t.created)}</span></div><div class="kv"><span>开始时间</span><span>${date(t.started)}</span></div><div class="kv"><span>完成时间</span><span>${date(t.finished)}</span></div><p>${esc(t.message||'等待节点执行，请保持 Agent 在线。')}</p>${r.steps?`<pre>${r.steps.map((x,i)=>(i+1)+'. '+esc(x)).join('\n')}</pre>`:''}${r.backup?`<p>节点备份：<code>${esc(r.backup)}</code></p>`:''}${r.connection&&!r.config_details?'<p class="helper">此节点尚未返回完整配置详情，请升级节点程序后重新读取。</p>':''}${r.config_details?`<label for="config-details">协议配置详情</label><textarea id="config-details" readonly rows="16">${esc(formatConfigDetails(r.config_details))}</textarea><button data-action="copy-config-details">复制配置详情</button>`:''}${r.connection?`<label for="connection">连接信息</label><textarea id="connection" readonly>${esc(r.connection)}</textarea><button data-action="copy-connection">复制连接信息</button><p>连接二维码</p><img class="connection-qr" src="/api/tasks/${encodeURIComponent(id)}/qr" alt="连接信息二维码" width="240" height="240">`:''}${t.action==='share'&&!r.connection&&t.status==='succeeded'?'<p>连接信息已过期，请重新导出。</p>':''}<div class="modal-foot">${t.status==='queued'?`<button data-action="cancel-task" data-id="${id}">取消等待</button>`:''}<button data-action="close">关闭</button></div>`, true);
}

function installPortCandidate(instances, current) {
    const used = new Set(instances.map(i => Number(i.port)));
    used.add(Number(current));
    const count = 65535 - 20000 + 1;
    const random = crypto.getRandomValues(new Uint32Array(1))[0] % count;
    for (let i = 0; i < count; i++) {
        const port = 20000 + (random + i) % count;
        if (!used.has(port)) return port;
    }
    throw new Error('没有可推荐的高位端口，请检查节点端口配置。');
}

function installNameCandidate(instances, protocol, port) {
    const used = new Set(instances.filter(i => i.protocol === protocol).flatMap(i => (i.users || []).map(u => u.name)));
    const base = 'u' + port;
    let name = base;
    for (let n = 1; used.has(name); n++) name = base + '_' + n;
    return name;
}

// Mirrors COMMON_SNI_LIST in the pinned script; install-form.cjs checks parity.
function installSniCandidate(current) {
    const pool = ['ads', 'advertising', 'apps', 'asia', 'books', 'community', 'crl',
        'developer', 'files', 'guide', 'iphone', 'link', 'maps', 'ml', 'music',
        'one', 'store', 'support', 'time', 'tv', 'videos'].map(name => name + '.apple.com');
    const candidates = pool.filter(name => name !== current);
    return candidates[crypto.getRandomValues(new Uint32Array(1))[0] % candidates.length];
}

function installProtocolGuidance(protocol) {
    const tls = '只有使用自签证书时才需跳过验证。';
    return {
        vless: 'Reality 模式：目标 SNI 需支持 TLS 1.3，且节点可以访问。自动生成仅选择脚本候选域名，不代表已验证连通性。',
        hy2: 'Hysteria2 使用 UDP，请放行 UDP 监听端口。当前安装不启用端口跳跃。' + tls,
        trojan: 'Trojan 使用 TCP + TLS；当前安装为原生 TCP，不是 WebSocket。' + tls,
        'ss-legacy': 'SS 使用独立端口和密码。请放行 TCP 和 UDP；当前一用户一端口，按独立入站采集用户流量。',
        ss2022: 'SS2022 使用标准 Base64 密钥。请放行 TCP 和 UDP；当前一用户一端口，按独立入站采集用户流量。',
        anytls: 'AnyTLS 使用 TCP + TLS。' + tls,
        snell: 'Snell v4 使用独立核心和 PSK，一用户一端口。',
        'snell-v5': 'Snell v5 使用独立核心和 PSK，一用户一端口。',
        'snell-v6': 'Snell v6 使用独立核心和 PSK，可设置模式、DNS 及客户端 TFO。'
    }[protocol];
}

// Install target: kept apart from `selected` so a periodic re-render of a detail page cannot switch it mid-form.
let installTargetId = null;
function installServers() {
    return nodes.filter(n => !n.deleted && n.adopted && n.status === 'online' && !n.maintenance);
}
function installNode() {
    return nodes.find(n => n.id === installTargetId) || selected;
}
function startInstall(nodeId) {
    const servers = installServers();
    installTargetId = servers.some(n => n.id === nodeId) ? nodeId : servers[0]?.id || null;
    if (!installTargetId) return modal('暂无可安装的服务器', '<p>需要已接管、在线且未在维护中的服务器。请先添加服务器，或等待服务器上线、结束维护。</p>');
    install();
}
function installServerField(protocol) {
    const current = installNode();
    return `<div class="inline-field install-server"><label for="install-server">服务器</label><select id="install-server">${installServers().map(n => {
        const ok = !protocol || installCombinations(n).some(k => k.split(':')[1] === protocol);
        return `<option value="${esc(n.id)}"${n.id === current.id ? ' selected' : ''}${ok ? '' : ' disabled'}>${esc(n.name)}${ok ? '' : '（不支持此协议）'}</option>`;
    }).join('')}</select></div>`;
}
function bindInstallServer(next) {
    $('#install-server').addEventListener('change', e => { installTargetId = e.target.value; next(); });
}

function installCombinations(node = installNode()) {
    const legacy = ['xray:vless','singbox:hy2','xray:snell','xray:snell-v5','xray:snell-v6'];
    const combinations = node.snapshot.task_api_version === 2
        ? (node.snapshot.write_capabilities || []).map(c=>`${c.core}:${c.protocol}`)
        : legacy;
    // Only render combinations with an implemented installation form.
    const supported = ['singbox:ss-legacy', 'singbox:ss2022', 'xray:vless', 'singbox:vless', 'singbox:hy2', 'xray:trojan',
        'singbox:trojan', 'singbox:anytls', 'xray:snell', 'xray:snell-v5', 'xray:snell-v6'];
    combinations.splice(0, combinations.length, ...combinations.filter(k => supported.includes(k)));
    return [...new Set(combinations)];
}

const INSTALL_CARD_META = {vless: 'Reality · TCP', hy2: 'QUIC · UDP', trojan: 'TLS · TCP', anytls: 'TLS · TCP', 'ss-legacy': 'TCP + UDP',
    ss2022: 'TCP + UDP', snell: 'PSK · TCP', 'snell-v5': 'PSK · TCP', 'snell-v6': 'PSK · TCP'};

function installCoreLabel(core, protocol) {
    return protocol.startsWith('snell') ? '独立核心' : core === 'xray' ? 'Xray' : 'Sing-box';
}

function install() {
    const combinations = installCombinations();
    const instances = installNode().snapshot.instances || [];
    const protocols = [...new Set(combinations.map(k=>k.split(':')[1]))];
    const cards = protocols.map(p=>{
        const cores = [...new Set(combinations.filter(k=>k.split(':')[1]===p).map(k=>installCoreLabel(k.split(':')[0], p)))].join(' / ');
        const count = instances.filter(i=>i.protocol===p).length;
        return `<button type="submit" class="protocol-card" value="${esc(p)}"><strong>${esc(names[p]||p)}</strong><span class="protocol-card-cores">${esc(cores)}</span><span class="protocol-card-meta">${esc(INSTALL_CARD_META[p]||'')}</span>${count?`<span class="protocol-card-count">已安装 ${count} 个</span>`:''}</button>`;
    }).join('');
    modal('选择要安装的协议', `<form id="protocol-choice-form"><div class="install-scroll"><div class="install-top">${installServerField()}</div><p>选择协议后填写端口等参数；新实例使用独立端口，不影响已有配置。</p>${combinations.length ? `<div class="protocol-grid">${cards}</div>` : '<p class="notice">此服务器的节点程序未声明可用写入能力，请先升级节点程序，或选择其他服务器。</p>'}</div><div class="modal-foot"><button type="button" data-action="close">取消</button></div></form>`, false, 'install');
    bindInstallServer(install);
    $('#protocol-choice-form .protocol-card')?.focus();
    $('#protocol-choice-form').addEventListener('submit', e=>{
        e.preventDefault();
        const protocol = e.submitter?.value;
        if (protocols.includes(protocol)) installForm(protocol);
    });
}

function installForm(protocol) {
    const node = installNode();
    const combinations = installCombinations(node).filter(k=>k.split(':')[1]===protocol);
    if (!combinations.length) return install();
    modal(`安装 ${names[protocol]||protocol}`, `<form id="install-form"><div class="install-scroll"><div class="install-top">${installServerField(protocol)}<div class="inline-field" id="install-core-field"><label for="protocol">内核</label><select id="protocol" name="protocol">${combinations.map(k=>{const [core,p]=k.split(':');return `<option value="${esc(k)}">${installCoreLabel(core, p)}</option>`;}).join('')}</select></div></div><p id="protocol-guidance" class="install-guidance"></p>
<div class="install-grid">
<div><label for="port">端口</label><div class="input-action"><input id="port" name="port" type="number" min="1" max="65535" required><button type="button" id="generate-port" class="install-generate">生成</button></div></div>
<div id="sni-field"><label for="sni" id="sni-label">SNI 域名</label><div class="input-action"><input id="sni" name="sni" value="www.cloudflare.com" required><button type="button" id="generate-sni" class="install-generate">生成</button></div></div>
<div id="ss-method-field"><label for="ss-method">加密方式</label><select id="ss-method" disabled></select></div>
<div id="credential-fields"><label id="credential-label" for="credential">访问凭据</label><div class="input-action"><input id="credential" type="password" autocomplete="new-password" maxlength="128" placeholder="留空自动生成"><button type="button" id="generate-credential" class="install-generate">生成</button></div></div>
<div id="certificate-fields" class="install-group"><div><label for="certificate-mode">证书</label><select id="certificate-mode"><option value="self">自签证书</option><option value="acme">自有域名 · Let’s Encrypt（HTTP）</option><option value="existing">节点已有证书</option></select></div><div id="acme-email-field"><label for="acme-email">证书邮箱</label><input id="acme-email" type="email" maxlength="254"></div><p id="certificate-help" class="helper install-wide"></p></div>
<div id="reality-fields" class="install-group"><div><label for="reality-private">Reality 私钥</label><input id="reality-private" type="password" autocomplete="new-password" maxlength="43" placeholder="留空自动生成"></div><div><label for="reality-short-id">Short ID</label><div class="input-action"><input id="reality-short-id" maxlength="16" pattern="([0-9a-fA-F]{2}){1,8}" placeholder="留空自动生成"><button type="button" id="generate-short-id" class="install-generate">生成</button></div></div></div>
<div id="snell-fields" class="install-group"><div><label for="snell-mode">混淆模式</label><select id="snell-mode"><option value="default">default</option><option value="unshaped">unshaped</option><option value="unsafe-raw">unsafe-raw</option></select></div><div><label for="tfo">TCP Fast Open</label><select id="tfo"><option value="true">启用</option><option value="false">关闭</option></select></div><div><label for="dns">DNS 服务器</label><input id="dns" maxlength="512" placeholder="留空使用系统 DNS"></div><div><label for="dns-preference">DNS IP 偏好</label><select id="dns-preference"><option value="default">default</option><option value="prefer-ipv4">prefer-ipv4</option><option value="prefer-ipv6">prefer-ipv6</option><option value="ipv4-only">ipv4-only</option><option value="ipv6-only">ipv6-only</option></select></div></div>
</div></div><div class="install-status"><p id="install-options-status" class="helper"></p><p id="generation-feedback" class="helper" role="status" aria-live="polite"></p><div class="error" role="alert"></div></div><div class="modal-foot"><p class="install-warning">${protocol.startsWith('snell')?'安装可能需要数分钟。':'安装可能需要数分钟，共享核心会短暂重启。'}请在防火墙放行端口。</p><button type="submit" class="primary">安装实例</button></div></form>`, false, 'install', install);
    bindInstallServer(() => installForm(protocol));
    $('#install-core-field').hidden = combinations.length === 1;
    const updateFields = () => {
        const p = $('#protocol').value.split(':')[1], snell = p.startsWith('snell'), ss = ['ss-legacy','ss2022'].includes(p), noSni = snell || ss;
        const methods = p==='ss2022' ? ['2022-blake3-aes-128-gcm','2022-blake3-aes-256-gcm'] : ['aes-256-gcm','aes-128-gcm','chacha20-ietf-poly1305'];
        const method = methods.includes($('#ss-method').value) ? $('#ss-method').value : methods[0];
        $('#ss-method').innerHTML = methods.map(m=>`<option value="${m}">${m}</option>`).join('');
        $('#ss-method').value = method; $('#ss-method').disabled = !ss;
        const advanced = [1, 2].includes(node.snapshot.install_options_version);
        for (const id of ['reality-private', 'reality-short-id', 'generate-short-id'])
            $('#'+id).disabled = !(p === 'vless' && node.snapshot.install_options_version === 2);
        const tls = ['hy2', 'trojan', 'anytls'].includes(p);
        $('#sni').disabled = noSni;
        $('#sni').required = !noSni;
        $('#sni-field').hidden = noSni;
        $('#generate-sni').disabled = noSni;
        $('#sni-label').textContent = p === 'vless' ? 'Reality 目标 SNI' : '证书域名 / SNI';
        $('#protocol-guidance').textContent = installProtocolGuidance(p);
        for (const id of ['credential', 'generate-credential']) $('#'+id).disabled = !advanced;
        $('#certificate-mode').disabled = !(advanced && tls);
        for (const id of ['snell-mode', 'dns', 'dns-preference', 'tfo']) $('#'+id).disabled = !(advanced && p === 'snell-v6');
        $('#ss-method-field').hidden = !ss;
        $('#credential-fields').hidden = !advanced;
        $('#certificate-fields').hidden = !(advanced && tls);
        $('#reality-fields').hidden = !(p === 'vless' && node.snapshot.install_options_version === 2);
        $('#snell-fields').hidden = !(advanced && p === 'snell-v6');
        $('#credential-label').textContent = p === 'vless' ? 'UUID' : snell ? 'PSK' : p === 'ss2022' ? 'Base64 密钥' : '密码';
        const certificate = $('#certificate-mode').value;
        $('#acme-email-field').hidden = !(advanced && tls && certificate === 'acme');
        $('#acme-email').disabled = !(advanced && tls && certificate === 'acme');
        $('#acme-email').required = !$('#acme-email').disabled;
        $('#generate-sni').disabled = noSni || (tls && advanced && certificate !== 'self');
        $('#install-options-status').textContent = advanced
            ? ''
            : '此节点 Agent 尚未支持高级参数，请先升级 Agent；当前仅可使用基础安装。';
        $('#install-options-status').hidden = advanced;
        $('#certificate-help').hidden = !(advanced && tls && certificate !== 'self');
        $('#certificate-help').textContent = !tls ? '此协议不使用 TLS 证书。' : certificate === 'acme'
            ? '使用自己的域名，先解析到节点并放行 TCP 80。使用 HTTP 验证申请 Let’s Encrypt 证书并配置续期；端口占用时拒绝，不自动停止网站。DNS 验证尚未接入。'
            : certificate === 'existing' ? '使用节点 /etc/vless-reality/certs/server.crt 与 server.key；验证域名、有效期及密钥匹配。'
            : '可填写自有域名或生成候选域名。节点生成带 SAN 的自签证书，无需域名解析；客户端需跳过证书验证。';
        $('#generation-feedback').textContent = '';
    };
    $('#protocol').addEventListener('change', updateFields);
    $('#generate-short-id').onclick = () => {
        $('#reality-short-id').value = Array.from(crypto.getRandomValues(new Uint8Array(4)),
            n => n.toString(16).padStart(2, '0')).join('');
        $('#generation-feedback').textContent = '已生成 Short ID，尚未安装。';
    };
    $('#certificate-mode').addEventListener('change', updateFields);
    $('#generate-credential').onclick = () => {
        $('#credential').value = $('#protocol').value.split(':')[1] === 'vless'
            ? crypto.randomUUID()
            : Array.from(crypto.getRandomValues(new Uint8Array(24)), n => n.toString(16).padStart(2, '0')).join('');
        if ($('#protocol').value.split(':')[1] === 'ss2022') $('#credential').value = btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array($('#ss-method').value.includes('128') ? 16 : 32))));
        $('#generation-feedback').textContent = '已生成凭据，尚未安装；也可清空以在节点自动生成。';
    };
    updateFields();
    // Open on a free random high port rather than a fixed default.
    try { $('#port').value = installPortCandidate(node.snapshot.instances || [], $('#port').value); } catch (err) { /* keep the field for manual input */ }
    $('#port').focus();
    $('#generate-port').onclick = () => {
        try {
            $('#port').value = installPortCandidate(node.snapshot.instances || [], $('#port').value);
            $('#generation-feedback').textContent = '已生成推荐端口；尚未安装，请核对后提交。';
        } catch (err) { formError(err); }
    };
    $('#generate-sni').onclick = () => {
        $('#sni').value = installSniCandidate($('#sni').value);
        $('#generation-feedback').textContent = '已从脚本候选列表生成 SNI，可手动修改；仍需确认节点可访问该域名。';
    };
    if (typeof installUserPicker === 'function') installUserPicker(node);
    $('#install-form').addEventListener('submit', async e => {
        e.preventDefault();
        const b = $('[type=submit]', e.target);
        b.disabled = true;
        const [core, p] = $('#protocol').value.split(':');
        try {
            // The account name is generated, never typed: platform nodes ignore it (empty instance),
            // script-mode and older nodes get a name unused by this protocol.
            const name = installNameCandidate(node.snapshot.instances || [], p, Number($('#port').value));
            const params = (p.startsWith('snell') || ['ss-legacy','ss2022'].includes(p)) ? {name} : {sni: $('#sni').value};
            if (node.snapshot.install_options_version === 2 && p === 'vless') {
                if ($('#reality-private').value) params.private_key = $('#reality-private').value;
                if ($('#reality-short-id').value) params.short_id = $('#reality-short-id').value;
            }
            if ([1, 2].includes(node.snapshot.install_options_version)) {
                params.name = name;
                if ($('#credential').value) params.credential = $('#credential').value;
                if (['hy2', 'trojan', 'anytls'].includes(p)) {
                    params.certificate_mode = $('#certificate-mode').value;
                    if (params.certificate_mode === 'acme') params.acme_email = $('#acme-email').value;
                }
                if (p === 'snell-v6') Object.assign(params, {
                    mode: $('#snell-mode').value, dns: $('#dns').value,
                    dns_ip_preference: $('#dns-preference').value, tfo: $('#tfo').value === 'true'
                });
            }
            if (['ss-legacy','ss2022'].includes(p)) params.method = $('#ss-method').value;
            const placeUsers = typeof installPickedUsers === 'function' ? installPickedUsers() : [];
            await submitTask('install', {
                protocol: p,
                core,
                port: Number($('#port').value)
            }, params, node);
            if (placeUsers.length) await installPlaceUsers(placeUsers, node.id);
        } catch (err) {
            formError(err);
            b.disabled = false;
        }
    });
}

function editUser(index, userIndex) {
    const p = selected.snapshot.instances[index],
        u = userIndex == null ? null : p.users[userIndex];
    modal(u ? '编辑用户' : '新增用户', `<form id="user-form"><label for="username">用户名</label><input id="username" value="${esc(u?.name||'')}" pattern="[A-Za-z0-9_\\-]{1,32}" maxlength="32" required ${u?'readonly':''}><label for="expiry">到期日期</label><input id="expiry" type="date" value="${esc(u?.expire_date||'')}"><p class="helper">留空表示永不过期。按节点本地日期判断，每分钟检查。</p>${u?`<label class="field-check"><input id="enabled" type="checkbox" ${u.enabled?'checked':''}>启用此用户</label>`:''}<p class="helper">凭据自动生成。${['ss-legacy','ss2022'].includes(p.protocol)?'SS 系列一用户一端口，增加用户请新增实例。':''}${p.protocol.startsWith('snell')?'Snell 每个用户对应独立端口；增加用户请新增实例。':''}</p><div class="error" role="alert"></div><div class="modal-foot">${u&&u.name!=='default'&&!p.protocol.startsWith('snell')&&!['ss-legacy','ss2022'].includes(p.protocol)?`<button type="button" class="danger" data-action="delete-user" data-index="${index}" data-user="${userIndex}">删除用户</button>`:''}<button type="submit" class="primary">${u?'保存修改':'创建用户'}</button></div></form>`);
    if (selected.snapshot.billing_version === 1 && !['ss-legacy','ss2022'].includes(p.protocol)) {
        $('#user-form .error').insertAdjacentHTML('beforebegin', `<label for="quota">流量配额（GiB）</label><input id="quota" type="number" min="0" max="999999" step="1" value="${Math.ceil((u?.quota||0)/1073741824)}" required><label for="reset-day">每月重置日</label><input id="reset-day" type="number" min="0" max="28" step="1" value="${u?.reset_day||0}" required><p class="helper">配额 0 表示不限，重置日 0 表示累计不重置。按节点本地日期执行；修改设置保留当前用量。月度重置不会启用手动停用或到期用户。${p.traffic_state!=='ready'?' 当前统计不可用，请修复节点统计任务后再设置非零配额。':''}</p>`);
    }
    if (u && selected.snapshot.task_api_version === 2) {
        $('#user-form .error').insertAdjacentHTML('beforebegin', '<label class="field-check"><input id="reset-credentials" type="checkbox">重置此用户凭据（旧连接将失效）</label><p class="helper">不清空流量、配额或 TG 绑定；保存后请重新导出连接。</p>');
    }
    $('#user-form').addEventListener('submit', async e => {
        e.preventDefault();
        const b = $('[type=submit]', e.target);
        b.disabled = true;
        try {
            const params = {
                name: $('#username').value,
                expire_date: $('#expiry').value
            };
            if ($('#quota')) {
                if (!u || Number($('#quota').value) !== Math.ceil(u.quota/1073741824)) params.quota_gb=Number($('#quota').value);
                if (!u || Number($('#reset-day').value) !== (u.reset_day||0)) params.reset_day=Number($('#reset-day').value);
            }
            if (u) params.enabled = $('#enabled').checked;
            if ($('#reset-credentials')?.checked) params.reset_credentials = true;
            await submitTask(u ? 'user_update' : 'user_add', p, params);
        } catch (err) {
            formError(err);
            b.disabled = false;
        }
    });
}

function confirmTask(action, p, params = {}) {
    const affected = selected.snapshot.instances.filter(i => i.service === p.service);
    modal(actions[action], `<p>目标：<strong>${esc(names[p.protocol]||p.protocol)} · ${p.port}</strong></p><div class="notice warn">${action==='delete'?'将删除此端口实例及其用户。':'操作会修改节点运行状态。'}${affected.length>1?` 该服务共承载 ${affected.length} 个实例，服务启停影响全部实例；应用配置会短暂重启共享服务。`:''}</div><p>节点会保存配置备份；请核对目标后执行。</p><div class="error" role="alert"></div><div class="modal-foot"><button data-action="close">取消</button><button id="confirm-task" class="${action.includes('delete')?'danger':'primary'}">确认${actions[action]}</button></div>`);
    $('#confirm-task').addEventListener('click', async e => {
        e.target.disabled = true;
        try {
            await submitTask(action, p, params);
        } catch (err) {
            formError(err);
            e.target.disabled = false;
        }
    });
}
document.addEventListener('click', async e => {
    const b = e.target.closest('[data-action]');
    if (!b || b.disabled) return;
    const action = b.dataset.action,
        index = Number(b.dataset.index),
        p = selected?.snapshot.instances?.[index];
    try {
        if (action === 'close') {
            $('#modal').close();
            activeTaskId = null;
        } else if (action.startsWith('pu-')) await userAction(action, b);
        else if (action.startsWith('me-')) await portalAction(action, b);
        else if (action.startsWith('fw-')) await forwardAction(action, b);
        else if (action.startsWith('rl-')) await relayAction(action, b);
        else if (action.startsWith('pa-')) await panelAddressAction(action, b);
        else if (action === 'node-instance') {
            // Instance dialogs act on `selected`; point it at the instance's server first.
            selected = nodes.find(n => n.id === b.dataset.node);
            if (selected) showInstance(Number(b.dataset.index));
        }
        else if (action === 'logout') {
            await post('/logout');
            authenticated = false;
            portalState = null;
            csrf = '';
            $('#modal').close();
            login();
        } else if (action === 'refresh') await refresh();
        else if (action === 'history') await historyDialog();
        else if (action === 'monitor-settings') await notificationSettings();
        else if (action === 'notification-test') { await post('/monitor/test'); toast('测试消息已排队，稍后在 Telegram 查收'); }
        else if (action === 'backup-create') { b.disabled=true; try { await post('/backups'); await backupSettings(); } finally { b.disabled=false; } }
        else if (action === 'backup-verify') { b.disabled=true; try { const r=await post('/backups/verify', {name:b.dataset.name}); toast(`恢复副本校验通过：${r.nodes} 个节点，${r.tasks} 条任务`); } finally { b.disabled=false; } }
        else if (action === 'trash') await showTrash();
        else if (action === 'restore-node') { await post('/nodes/'+b.dataset.id+'/restore'); await refresh(); await showTrash(); }
        else if (action === 'delete-node') deleteNode();
        else if (action === 'authority') authorityDialog(selected);
        else if (action === 'upgrade-agent' && selected.snapshot.upgrade_version === 1 && selected.status === 'online') upgradeDialog(selected);
        else if (action === 'upgrade-agent') { currentCommand=selected.update_command; modal('升级节点程序', `<p>在节点以 root 执行，升级前自动检查任务，保留节点身份、现有协议与用户；新版未上线会恢复旧程序。</p><textarea readonly rows="5">${esc(currentCommand)}</textarea><p class="helper">维护中断时，请在节点核对状态后运行 vaio-agent resume。此操作不会更新代理内核。</p><div class="modal-foot"><button class="primary" data-action="copy-command">复制升级命令</button></div>`); }
        else if (action === 'resolve-task') resolveTask(b.dataset.id);
        else if (action === 'settings') await accountSettings();
        else if (action === 'settings-tab') await ({address: panelAddressDialog, backup: backupSettings}[b.dataset.tab] || accountSettings)();
        else if (action === 'panel-update') await panelUpdateDialog(true);
        else if (action === 'panel-update-start') await panelUpdateStart(b);
        else if (action === 'upgrade-all') upgradeAllDialog();
        else if (action.startsWith('core-')) await coreAction(action, b);
        else if (action === 'upgrade-all-confirm') await upgradeAllStart(b);
        else if (action === 'add-node') addNode();
        else if (action === 'task') showTask(b.dataset.id);
        else if (action === 'cancel-task') {
            await post('/tasks/' + b.dataset.id + '/cancel');
            await refresh();
        } else if (action === 'tab') {
            detailTab = b.dataset.tab;
            detail(selected);
        } else if (action === 'instance') showInstance(index);
        else if (action === 'install') startInstall(selected?.id);
        else if (action === 'instance-create') startInstall(instanceFilter.node);
        else if (action === 'renew') {
            enrollment(await post('/nodes/' + selected.id + '/enrollment'));
            await refresh();
        } else if (action === 'adopt') {
            const sn = selected.snapshot, switching = sn.authority_version === 1 && sn.accounts_version === 1 && sn.user_authority !== 'platform';
            const users = (sn.instances || []).reduce((n, i) => n + (i.users || []).length, 0);
            modal('确认接管节点', `<p>面板已识别 ${(sn.instances || []).length} 个协议实例。接管后可在面板安装、修改和卸载，现有协议配置不变。</p>${switching ? `<p>接管后用户统一由平台管理（以平台为准），节点脚本菜单只读。</p>${users ? `<div class="notice warn">将删除节点上现有的 ${users} 个脚本用户及其凭据、配额、到期和 TG 配置，现有客户端会失效。之后在「用户管理」中新建平台用户。</div>` : ''}` : sn.user_authority === 'platform' ? '' : '<p class="helper">节点程序版本较旧，接管后用户暂由节点脚本管理；升级节点后可切换为平台管理。</p>'}<p class="helper">接管期间请避免同时在 SSH 菜单中修改配置。</p><div class="error"></div><div class="modal-foot"><button data-action="close">取消</button><button id="confirm-adopt" class="primary">${switching ? '确认接管并切到平台管理' : '确认接管'}</button></div>`);
            $('#confirm-adopt').onclick = async e => {
                e.target.disabled = true;
                try {
                    const r = await post('/nodes/' + selected.id + '/adopt', {revision: sn.revision, ...(switching && users ? {clear_users: true} : {})});
                    if (r.task_id) { activeTaskId = r.task_id; await refresh(); showTask(r.task_id); toast('节点已接管，正在切换为平台管理'); }
                    else { $('#modal').close(); toast(r.message || '节点已接管'); await refresh(); }
                } catch (err) {
                    formError(err);
                    e.target.disabled = false;
                }
            };
        } else if (action === 'node-settings') {
            nodeSettings();
        } else if (action === 'revoke') {
            modal('撤销节点身份', `<p>撤销后该节点无法继续连接面板，等待中的任务会取消。已在节点执行的任务无法远程中止。</p><div class="modal-foot"><button data-action="close">取消</button><button class="danger" id="confirm-revoke">确认撤销</button></div>`);
            $('#confirm-revoke').onclick = async () => {
                try {
                    await post('/nodes/' + selected.id + '/revoke');
                    $('#modal').close();
                    await refresh();
                } catch (err) {
                    toast(err.message);
                }
            };
        } else if (action === 'copy-command') {
            await navigator.clipboard.writeText(currentCommand);
            toast('安装命令已复制');
        } else if (action === 'download-script') {
            const url = URL.createObjectURL(new Blob([currentScript], {
                type: 'text/x-shellscript'
            }));
            const a = document.createElement('a');
            a.href = url;
            a.download = 'vaio-agent-install.sh';
            a.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        } else if (action === 'copy-connection') {
            await navigator.clipboard.writeText($('#connection').value);
            toast('连接信息已复制');
        } else if (action === 'add-user') editUser(index, null);
        else if (action === 'edit-user') editUser(index, Number(b.dataset.user));
        else if (action === 'delete-user') confirmTask('user_delete', p, {
            name: p.users[Number(b.dataset.user)].name
        });
        else if (['delete', 'restart', 'start', 'stop'].includes(action)) confirmTask(action, p);
        else if (action === 'edit-port') {
            modal('修改监听端口', `<form id="port-form"><p>此修改会重启 ${esc(p.service)}，影响同服务上的其他实例。</p><label for="new-port">新端口</label><input id="new-port" type="number" min="1" max="65535" required value="${p.port}"><div class="error"></div><div class="modal-foot"><button type="submit" class="primary">保存并应用</button></div></form>`);
            $('#port-form').onsubmit = async e => {
                e.preventDefault();
                const b = $('[type=submit]', e.target);
                b.disabled = true;
                try {
                    await submitTask('update', p, {
                        port: Number($('#new-port').value)
                    });
                } catch (err) {
                    formError(err);
                    b.disabled = false;
                }
            };
        } else if (action === 'traffic-node') {
            trafficNodeId = b.dataset.id;
            trafficPage();
            await userTraffic();
        } else if (action === 'copy-config-details') {
            await navigator.clipboard.writeText($('#config-details').value);
            toast('配置详情已复制');
        } else if (action === 'share') {
            const user = p.users[Number(b.dataset.user)];
            if (selected.snapshot.config_details_version !== 2) {
                modal('请先升级节点程序', '<p>此节点尚不支持自动读取完整配置，请先在节点设置中升级节点程序。</p>');
                return;
            }
            b.disabled = true;
            try { await submitTask('share', p, {name: user.name}); }
            finally { b.disabled = false; }

        }
    } catch (err) {
        toast(err.message);
    }
});
$('#modal').addEventListener('close', () => {
    activeTaskId = null;
    currentScript = '';
    currentCommand = '';
});
window.addEventListener('hashchange', () => {
    if (authenticated) render().catch(e => toast(e.message));
});
async function boot() {
    try {
        const session = await api('/session');
        csrf = session.csrf;
        panelVersion = session.version;
        authenticated = true;
        await refresh();
    } catch {
        // Not an admin: a signed-in platform user gets their own page.
        try { await portal(); } catch { login(); }
    }
}
let refreshTicks = 0;
setInterval(() => {
    refreshTicks++;
    const task = tasks.find(t=>t.id===activeTaskId);
    if (authenticated && (refreshTicks % 10 === 0 || ($('#modal').open && task && ['queued','running'].includes(task.status)))) refresh();
}, 1000);
boot();


async function backupSettings() {
    const data = await api('/backups');
    modal('系统设置', `${settingsTabs('backup')}<div class="action-row settings-actions"><button class="primary" data-action="backup-create">立即备份</button></div><p class="helper">每天自动备份面板数据库，保留最近 7 份。校验会恢复到临时副本并检查完整性，不影响在线面板；实际恢复需在服务器执行 vaio-panel restore，恢复后排队任务取消、执行中任务标记结果未知。节点代理配置使用节点本地备份。</p><div class="table-wrap"><table><thead><tr><th>备份</th><th>时间</th><th class="num">大小</th><th>操作</th></tr></thead><tbody>${data.backups.map(b=>`<tr><td class="mono">${esc(b.name)}</td><td class="muted">${date(b.at)}</td><td class="num">${bytes(b.size)}</td><td><button class="small" data-action="backup-verify" data-name="${esc(b.name)}">恢复校验</button></td></tr>`).join('')||'<tr><td colspan="4">首次自动备份尚未完成，可以立即创建备份。</td></tr>'}</tbody></table></div>`, true);
}

async function historyDialog() {
    const data = await api('/nodes/'+selected.id+'/history');
    data.samples.forEach((sample, i) => {
        const prior = data.samples[i-1], dt = prior ? sample.at-prior.at : 0;
        for (const field of ['network_rx','network_tx']) sample[field+'_rate'] = prior && dt>0 && dt<=120 && Number.isFinite(prior[field]) && Number.isFinite(sample[field]) && sample[field]>=prior[field] ? (sample[field]-prior[field])*8/dt/1000000 : null;
    });
    const charts = [['系统负载', x=>x.load], ['内存使用率（%）', x=>x.memory_total?100*x.memory_used/x.memory_total:null], ['磁盘使用率（%）',x=>x.disk_total?100*x.disk_used/x.disk_total:null], ['网卡接收速率（Mbps）',x=>x.network_rx_rate], ['网卡发送速率（Mbps）',x=>x.network_tx_rate]];
    const end = Date.now()/1000, start=end-86400;
    const tick = n => String(Number(n.toFixed(n >= 100 ? 0 : n >= 1 ? 1 : 2)));
    const stamp = t => new Date(t * 1000).toLocaleString('zh-CN', {hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'});
    const content=charts.map(([title,value])=>{
        const points=data.samples.filter(x=>Number.isFinite(value(x))), peak=Math.max(0,...points.map(value)), max=Math.max(1,peak);
        let d='',previous=0;
        const segments=[];
        for(const x of points) { const px=((x.at-start)/86400*600).toFixed(2), py=(105-value(x)/max*90).toFixed(2); if(x.at-previous>120) segments.push([]); segments[segments.length-1].push([px,py]); d+=(x.at-previous>120?'M':'L')+px+','+py+' ';previous=x.at; }
        // Area under each continuous run, closed to the baseline separately so gaps stay empty.
        const area=segments.map(seg=>`M${seg[0][0]},105 ${seg.map(([px,py])=>'L'+px+','+py).join(' ')} L${seg[seg.length-1][0]},105 Z`).join(' ');
        const unit=(title.match(/（(.+)）/)||[])[1]||'';
        return `<section class="history-chart"><div class="chart-head"><div><h3>${title}</h3>${points.length?`<p class="helper">最新 ${value(points[points.length-1]).toFixed(2)} · 最高 ${peak.toFixed(2)} · ${points.length} 个采样点</p>`:''}</div>${points.length?`<div class="chart-reading">${reading(value(points[points.length-1]).toFixed(2), unit)}</div>`:''}</div>${points.length?`<div class="chart-plot"><svg viewBox="0 0 600 120" preserveAspectRatio="none" role="img" aria-label="${title}过去24小时变化"><path class="chart-area" d="${area}"/><g class="chart-grid"><line x1="0" x2="600" y1="15" y2="15"/><line x1="0" x2="600" y1="60" y2="60"/><line class="chart-base" x1="0" x2="600" y1="105" y2="105"/></g><path class="chart-line" d="${d}"/></svg><span class="chart-tick tick-max">${tick(max)}</span><span class="chart-tick tick-half">${tick(max/2)}</span><span class="chart-tick tick-zero">0</span></div><div class="chart-time"><span>${stamp(start)}</span><span>${stamp(end)}</span></div>`:'<p>暂无采样数据</p>'}</section>`;
    }).join('');
    modal('历史曲线 · '+selected.name, `<p class="helper">过去 24 小时，每分钟采样一次；保留 7 天数据。断线时间段留空。</p>${content}<p class="helper">${date(start)} — ${date(end)}</p>`, true);
}

// ---------------------------------------------------------------- 用户管理（平台用户）
let platformData = {users: []}, currentUser = null;
const userStates = {'': ['running', '正常'], manual: ['stopped', '已停用'], expired: ['blocked', '已到期'], quota: ['blocked', '流量已用尽'], platform_quota: ['blocked', '平台总流量已用尽']};
const syncStates = {synced: ['succeeded', '已同步'], pending: ['pending', '待同步'], offline: ['offline', '节点离线'], failed: ['failed', '同步失败'], unknown: ['unknown', '待核对'], removing: ['pending', '解除中']};
const stateBadge = (map, key) => { const [cls, text] = map[key] || ['pending', key || '—']; return `<span class="badge ${cls}">${esc(text)}</span>`; };
const SINGLE_USER = ['ss-legacy', 'ss2022', 'snell', 'snell-v5', 'snell-v6'];
const quotaText = (used, quota) => `${bytes(used || 0)} / ${quota ? bytes(quota) : '不限'}`;
const memberText = m => `${esc(names[m.protocol] || m.protocol)} · <span class="mono">${m.port}</span>${m.name ? ' · ' + esc(m.name) : ''}`;
const userSync = u => {
    if (!u.links.length) return '<span class="muted">未关联节点</span>';
    const bad = u.links.filter(l => l.sync !== 'synced');
    return bad.length ? stateBadge(syncStates, bad.find(l => ['failed', 'unknown'].includes(l.sync))?.sync || bad[0].sync) + ` <span class="muted">${bad.length}/${u.links.length}</span>` : stateBadge(syncStates, 'synced');
};
const usersReady = node => node.adopted && node.status === 'online' && !node.maintenance && node.snapshot.authority_version === 1 && node.snapshot.accounts_version === 1 && node.snapshot.user_authority === 'platform';
const authorityText = s => s.authority_version !== 1 ? '旧版节点（需升级）' : s.user_authority === 'platform' ? '以平台为准' : '以节点脚本为准';

async function usersPage() {
    platformData = await api('/users');
    const rows = platformData.users.map(u => `<tr><td><a href="#users/${esc(u.id)}"><strong>${esc(u.name)}</strong></a>${u.note ? `<br><span class="muted">${esc(u.note)}</span>` : ''}</td><td>${stateBadge(userStates, u.state)}${u.deleting ? '<br><span class="muted">删除中</span>' : ''}</td><td>${meter('用量', u.quota ? u.used / u.quota * 100 : null)}<span class="muted">${quotaText(u.used, u.quota)}</span></td><td>${esc(u.expire_date || '永不过期')}</td><td class="num">${u.links.length}</td><td>${userSync(u)}</td></tr>`).join('');
    shell(`<div class="heading"><div><h1>用户管理</h1></div><button class="primary" data-action="pu-create">${icon('plus')}新建用户</button></div>
    <div class="panel table-wrap"><table><thead><tr><th>用户</th><th>状态</th><th>本周期用量</th><th>到期</th><th class="num">节点</th><th>同步</th></tr></thead><tbody>${rows || '<tr><td colspan="6">暂无平台用户。新建用户后关联节点即可使用。</td></tr>'}</tbody></table></div>
    <p class="helper">只有用户管理方式为「以平台为准」的节点可以关联，可在节点详情中切换。跨节点总流量达到配额后，所有节点上的该用户都会停用，到重置日或调高配额后自动恢复。</p>`, 'users');
}

async function userDetail(id) {
    const {user} = await api('/users/' + encodeURIComponent(id));
    currentUser = user;
    const links = user.links.map(l => `<tr><td><a href="#nodes/${esc(l.node_id)}">${esc(l.node_name)}</a></td><td>${(l.members || []).map(m => `<div>${memberText(m)} ${m.enabled === false ? '<span class="muted">已停用</span>' : ''} <button class="small quiet" data-action="pu-share" data-link="${esc(l.id)}" data-core="${esc(m.core)}" data-protocol="${esc(m.protocol)}" data-port="${m.port}" data-name="${esc(m.name)}">连接信息</button></div>`).join('') || '<span class="muted">' + (l.account ? '暂无协议' : '等待节点创建') + '</span>'}</td><td>${stateBadge(syncStates, l.sync)}${l.notice ? `<br><span class="muted">${esc(l.notice)}</span>` : ''}</td><td class="num">${bytes(l.cycle_used)}</td><td><button class="small" data-action="pu-members" data-link="${esc(l.id)}" ${l.account && l.online && l.sync !== 'removing' ? '' : 'disabled'}>协议</button><button class="small" data-action="pu-unlink" data-link="${esc(l.id)}" ${l.sync === 'removing' ? 'disabled' : ''}>解除</button></td></tr>`).join('');
    shell(`<div class="heading"><div><a class="back-link" href="#users">返回用户管理</a><h1>${esc(user.name)} ${stateBadge(userStates, user.state)}</h1><div class="detail-info"><span>到期 ${esc(user.expire_date || '永不过期')}</span><span>${user.reset_day ? '每月 ' + user.reset_day + ' 日重置' : '累计不重置'}</span>${user.note ? `<span>${esc(user.note)}</span>` : ''}</div></div><div class="action-row"><button data-action="pu-edit">编辑</button><button data-action="pu-reset-usage">重置用量</button><button data-action="pu-reset-credentials" ${user.links.length ? '' : 'disabled'}>重置全部凭据</button><button class="danger" data-action="pu-delete">删除</button></div></div>
    ${user.deleting ? '<div class="notice warn">正在从各节点解除，完成后删除此用户。</div>' : ''}
    <div class="stats">${stat('本周期用量', bytes(user.used).split(' ')[0], user.quota ? '配额 ' + bytes(user.quota) : '不限流量', bytes(user.used).split(' ')[1] || '')}${stat('剩余', user.quota ? bytes(Math.max(0, user.quota - user.used)).split(' ')[0] : '不限', user.quota ? '达到配额后停用全部节点' : '未设置配额', user.quota ? bytes(Math.max(0, user.quota - user.used)).split(' ')[1] || '' : '')}${stat('关联节点', user.links.length, user.links.filter(l => l.sync === 'synced').length + ' 个已同步')}${stat('统计周期', user.cycle === 'total' ? '累计' : esc(user.cycle), user.reset_day ? '按面板时区切换' : '不自动重置')}</div>
    <div class="panel"><div class="panel-head"><h2>关联节点 <span class="count">${user.links.length}</span></h2><button class="primary small" data-action="pu-link" ${user.deleting ? 'disabled' : ''}>${icon('plus')}关联节点</button></div><div class="table-wrap"><table><thead><tr><th>节点</th><th>协议</th><th>同步</th><th class="num">本周期用量</th><th>操作</th></tr></thead><tbody>${links || '<tr><td colspan="5">尚未关联节点。关联后会在节点上创建统一用户，或认领节点上已有的统一用户。</td></tr>'}</tbody></table></div></div>
    <p class="helper">每个协议的凭据独立。同步任务出现在任务记录中，结果未确认时不会自动重试，请核对后标记已核对。</p>`, 'users');
}

function userForm(user) {
    modal(user ? '编辑用户' : '新建用户', `<form id="pu-form"><label for="pu-name">用户名</label><input id="pu-name" value="${esc(user?.name || '')}" pattern="[A-Za-z0-9_\\-]{1,32}" maxlength="32" required><label for="pu-quota">总流量配额（GiB）</label><input id="pu-quota" type="number" min="0" max="999999" step="1" required value="${Math.ceil((user?.quota || 0) / 1073741824)}"><label for="pu-reset">每月重置日</label><input id="pu-reset" type="number" min="0" max="28" step="1" required value="${user?.reset_day || 0}"><label for="pu-expire">到期日期</label><input id="pu-expire" type="date" value="${esc(user?.expire_date || '')}"><label for="pu-note">备注</label><input id="pu-note" maxlength="200" value="${esc(user?.note || '')}"><label for="pu-password">登录密码</label><div class="input-action"><input id="pu-password" type="text" minlength="8" maxlength="128" ${user ? 'placeholder="留空不修改"' : 'required'} autocomplete="off" spellcheck="false"><button type="button" data-action="pu-password-random">随机生成</button></div><p class="helper">用户用用户名和此密码登录自己的页面，8–128 位。${user ? '填写即重置密码，该用户已登录的设备会退出。' : ''}</p>${user ? `<label class="field-check"><input id="pu-enabled" type="checkbox" ${user.enabled ? 'checked' : ''}>启用此用户</label>` : ''}<p class="helper">配额 0 表示不限，重置日 0 表示累计不重置；周期按面板时区切换，修改设置保留本周期用量。到期日期留空表示永不过期。</p><div class="error" role="alert"></div><div class="modal-foot"><button type="submit" class="primary">${user ? '保存修改' : '创建用户'}</button></div></form>`);
    $('#pu-form').onsubmit = async e => {
        e.preventDefault();
        const button = $('[type=submit]', e.target); button.disabled = true;
        const data = {name: $('#pu-name').value, quota_gb: Number($('#pu-quota').value), reset_day: Number($('#pu-reset').value), expire_date: $('#pu-expire').value, note: $('#pu-note').value};
        const password = $('#pu-password').value;
        if (password) data.password = password;
        try {
            if (user) {
                data.enabled = $('#pu-enabled').checked;
                if (data.quota_gb === Math.ceil(user.quota / 1073741824)) delete data.quota_gb;
                await post('/users/' + user.id, data);
                $('#modal').close(); toast(password ? '已保存，登录密码已重置' : '已保存，正在同步到各节点'); await userDetail(user.id);
            } else {
                const created = await post('/users', data);
                location.hash = 'users/' + created.id;
                // Shown once so the admin can pass it on; only its hash is stored.
                modal('用户已创建', `<p>用户 <strong>${esc(data.name)}</strong> 可以用以下信息登录：</p><div class="kv"><span>登录地址</span><span class="mono">${esc(location.origin)}</span></div><div class="kv"><span>用户名</span><span class="mono">${esc(data.name)}</span></div><label for="connection">登录密码</label><textarea id="connection" readonly rows="1">${esc(password)}</textarea><button data-action="copy-connection">复制密码</button><p class="helper">密码只显示这一次，之后可在「编辑用户」中重置。</p><div class="modal-foot"><button class="primary" data-action="close">完成</button></div>`);
            }
        } catch (err) { formError(err); button.disabled = false; }
    };
}

function linkDialog() {
    const user = currentUser;
    const options = nodes.filter(n => !n.deleted).map(n => `<option value="${esc(n.id)}" ${usersReady(n) && !user.links.some(l => l.node_id === n.id) ? '' : 'disabled'}>${esc(n.name)}${usersReady(n) ? '' : '（' + (n.snapshot.authority_version !== 1 ? '需升级节点程序' : n.snapshot.user_authority !== 'platform' ? '由节点脚本管理' : '离线或未接管') + '）'}</option>`).join('');
    modal('关联节点', `<form id="pu-link-form"><label for="pu-node">节点</label><select id="pu-node" required><option value="">选择节点</option>${options}</select><label>协议实例</label><div id="pu-instances" class="check-list"></div><p class="helper">在节点上为该用户新建统一用户，并在所选实例中新建协议账号，凭据自动生成。一用户一实例的协议只能选择空实例，选中后该实例归此用户。</p><div class="error" role="alert"></div><div class="modal-foot"><button type="submit" class="primary">关联</button></div></form>`);
    const update = () => {
        const node = nodes.find(n => n.id === $('#pu-node').value);
        $('#pu-instances').innerHTML = node ? (node.snapshot.instances || []).map(i => `<label class="field-check"><input type="checkbox" value="${esc(i.core + '|' + i.protocol + '|' + i.port)}" ${memberAddable(i) ? '' : 'disabled'}>${esc(names[i.protocol] || i.protocol)} · ${i.port}<span class="muted">（${esc(userModeText(i))}）</span></label>`).join('') || '<p class="muted">该节点没有协议实例</p>' : '<p class="muted">请先选择节点</p>';
    };
    $('#pu-node').onchange = update; update();
    $('#pu-link-form').onsubmit = async e => {
        e.preventDefault();
        const button = $('[type=submit]', e.target); button.disabled = true;
        try {
            const members = [...document.querySelectorAll('#pu-instances input:checked')].map(c => { const [core, protocol, port] = c.value.split('|'); return {core, protocol, port: Number(port)}; });
            await post('/users/' + user.id + '/links', {node_id: $('#pu-node').value, members});
            $('#modal').close(); toast('已提交，节点在线时自动同步'); await userDetail(user.id);
        } catch (err) { formError(err); button.disabled = false; }
    };
}

// 节点的用户管理方式（二选一）与一键升级
// 接管的服务器统一由平台管理用户：没有脚本用户时面板自动切换；有脚本用户时提示确认清空。
function authorityNotice(node) {
    const s = node.snapshot;
    if (!node.adopted || s.authority_version !== 1 || s.user_authority === 'platform') return '';
    const users = (s.instances || []).reduce((n, i) => n + (i.users || []).length, 0);
    const last = (typeof tasks !== 'undefined' ? tasks : []).filter(t => t.node_id === node.id && t.action === 'platform_apply'
        && t.request?.params?.ops?.[0]?.op === 'set_authority').sort((a, b) => b.created - a.created)[0];
    if (!users && last && ['failed', 'unknown'].includes(last.status)) {
        const ready = node.status === 'online' && !node.maintenance;
        return `<div class="notice warn"><span>切换为平台管理失败：${esc(last.message || '原因未知')}。可升级节点程序后重试，自动切换每小时重试一次。</span><button data-action="authority" ${ready ? '' : 'disabled'}>重试切换</button></div>`;
    }
    if (!users) return '<div class="notice"><span>正在把该服务器切换为平台统一管理用户，完成后在「用户管理」中新建用户。</span></div>';
    const ready = node.status === 'online' && !node.maintenance;
    return `<div class="notice warn"><span>该服务器仍有 ${users} 个脚本用户，尚未由平台统一管理。清空这些用户后切换为平台管理，现有客户端会失效。</span><button data-action="authority" ${ready ? '' : 'disabled'}>清空并切到平台管理</button></div>`;
}

function authorityBlock(node) {
    const upgrade = node.snapshot.last_upgrade;
    return upgrade ? `<section class="info-block"><h3>节点程序</h3><div class="kv"><span>上次升级</span><span>${esc({succeeded: '成功', rolled_back: '已回滚', failed: '失败'}[upgrade.status] || upgrade.status)}</span></div><p class="helper">${date(upgrade.at)} · ${esc(upgrade.to || '')} ${esc(upgrade.message || '')}</p></section>` : '';
}

function authorityDialog(node) {
    const s = node.snapshot, toPlatform = s.user_authority !== 'platform';
    const users = (s.instances || []).reduce((n, i) => n + (i.users || []).length, 0);
    modal(toPlatform ? '切换为平台管理' : '切回脚本管理', `<form id="authority-form">${toPlatform ? `<div class="notice warn">切换后将删除该节点上的全部 ${users} 个用户及其凭据、统一用户、TG 绑定、用户路由、配额与到期，现有客户端全部失效。协议实例保留，之后在「用户管理」中新建用户。</div><label for="authority-confirm">输入节点名称「${esc(node.name)}」确认</label><input id="authority-confirm" autocomplete="off" required>` : '<p>切回后面板停止管理该节点的用户，节点上现有的用户和凭据保留，改由节点脚本管理；平台用户在其他节点上的关联不受影响。</p>'}<div class="error" role="alert"></div><div class="modal-foot"><button type="button" data-action="close">取消</button><button type="submit" class="${toPlatform ? 'danger' : 'primary'}">确认切换</button></div></form>`);
    $('#authority-form').onsubmit = async e => {
        e.preventDefault();
        const button = $('[type=submit]', e.target); button.disabled = true;
        try {
            const data = await post('/nodes/' + node.id + '/authority', toPlatform ? {mode: 'platform', confirm: $('#authority-confirm').value} : {mode: 'script'});
            activeTaskId = data.id; await refresh(); showTask(data.id);
        } catch (err) { formError(err); button.disabled = false; }
    };
}

function upgradeDialog(node) {
    modal('一键升级节点', `<p>节点程序将从 ${esc(node.snapshot.agent_version || '—')} 升级到 ${esc(node.panel_version)}，节点脚本一并更新为同版本。</p><p class="helper">节点在独立进程中下载并校验安装包，期间进入维护模式；新版未按时上线会自动恢复旧程序和旧脚本。现有协议、用户和节点身份保留。升级结果显示在节点详情的「用户管理」一栏。</p><div class="error" role="alert"></div><div class="modal-foot"><button data-action="close">取消</button><button class="primary" id="confirm-upgrade">开始升级</button></div>`);
    $('#confirm-upgrade').onclick = async e => {
        e.target.disabled = true;
        try { const data = await post('/nodes/' + node.id + '/upgrade', {}); activeTaskId = data.id; await refresh(); showTask(data.id); }
        catch (err) { formError(err); e.target.disabled = false; }
    };
}

function membersDialog(linkId) {
    const link = currentUser.links.find(l => l.id === linkId), node = nodes.find(n => n.id === link.node_id);
    const instances = node?.snapshot.instances || [];
    const claimable = instances.filter(i => !i.user_mode || i.user_available).flatMap(i => (i.users || []).filter(u => !u.account_id).map(u => ({core: i.core, protocol: i.protocol, port: i.port, name: u.name})));
    modal('协议 · ' + link.node_name, `<form id="pu-member-form"><label for="pu-member-action">操作</label><select id="pu-member-action"><option value="add">新建协议账号</option><option value="claim">归入已有协议用户</option><option value="remove">移除协议</option></select><label for="pu-member-target">目标</label><select id="pu-member-target"></select><div id="pu-remove-set" hidden><label class="field-check"><input type="radio" name="pu-remove-mode" value="release" checked>保留为普通协议用户</label><label class="field-check"><input type="radio" name="pu-remove-mode" value="delete">同时删除该协议用户（旧连接失效）</label></div><p class="helper" id="pu-member-help"></p><div class="error" role="alert"></div><div class="modal-foot"><button type="submit" class="primary">提交</button></div></form>`);
    const update = () => {
        const action = $('#pu-member-action').value;
        const list = action === 'add' ? instances.filter(memberAddable).map(i => ({core: i.core, protocol: i.protocol, port: i.port, single: i.user_mode === 'single'}))
            : action === 'claim' ? claimable : link.members;
        $('#pu-member-target').innerHTML = list.map(t => `<option value="${esc(JSON.stringify(t))}">${memberText(t)}${t.single ? '（分配空实例）' : ''}</option>`).join('') || '<option value="">没有可选目标</option>';
        $('#pu-remove-set').hidden = action !== 'remove';
        $('#pu-member-help').textContent = action === 'add' ? '凭据自动生成，用户名与平台用户相同。一用户一实例的协议只列出空实例，分配后该实例归此用户。' : action === 'claim' ? '保留原凭据；该协议用户原有的配额与到期由此用户统一管理，已用流量计入本周期。SS 和 Snell 用户请先安装实例再归入。' : 'Snell 成员只能保留实例。';
    };
    $('#pu-member-action').onchange = update; update();
    $('#pu-member-form').onsubmit = async e => {
        e.preventDefault();
        const button = $('[type=submit]', e.target); button.disabled = true;
        try {
            const action = $('#pu-member-action').value, target = JSON.parse($('#pu-member-target').value || 'null');
            if (!target) throw new Error('没有可选目标');
            const data = {action, target: {core: target.core, protocol: target.protocol, port: target.port}};
            if (target.name) data.name = target.name;
            if (action === 'remove') data.mode = $('[name=pu-remove-mode]:checked').value;
            await post('/links/' + linkId + '/members', data);
            $('#modal').close(); toast('已提交，节点在线时自动同步'); await userDetail(currentUser.id);
        } catch (err) { formError(err); button.disabled = false; }
    };
}

function choiceDialog(title, text, choices, submit) {
    modal(title, `<form id="pu-choice-form"><p>${text}</p>${choices.map(([value, label], i) => `<label class="field-check"><input type="radio" name="pu-choice" value="${value}" ${i ? '' : 'checked'}>${label}</label>`).join('')}<div class="error" role="alert"></div><div class="modal-foot"><button data-action="close" type="button">取消</button><button type="submit" class="danger">确认</button></div></form>`);
    $('#pu-choice-form').onsubmit = async e => {
        e.preventDefault();
        const button = $('[type=submit]', e.target); button.disabled = true;
        try { await submit($('[name=pu-choice]:checked')?.value); $('#modal').close(); } catch (err) { formError(err); button.disabled = false; }
    };
}

async function userAction(action, b) {
    if (action.startsWith('pu-tg-')) return notifyAction(action, b);
    if (action === 'pu-create') userForm(null);
    else if (action === 'pu-edit') userForm(currentUser);
    else if (action === 'pu-link') linkDialog();
    else if (action === 'pu-members') membersDialog(b.dataset.link);
    else if (action === 'pu-password-random') { $('#pu-password').value = randomPassword(); $('#pu-password').focus(); }
    else if (action === 'pu-reset-usage') choiceDialog('重置用量', '清零该用户在所有节点上的本周期用量，超额停用的节点会自动恢复。', [], async () => { await post('/users/' + currentUser.id + '/reset-usage'); toast('用量已清零'); await userDetail(currentUser.id); });
    else if (action === 'pu-reset-credentials') choiceDialog('重置全部凭据', '为该用户在所有节点的每个协议生成新凭据，旧连接全部失效，之后请重新导出连接信息。', [], async () => { await post('/users/' + currentUser.id + '/reset-credentials', {}); toast('已提交，节点在线时自动同步'); await userDetail(currentUser.id); });
    else if (action === 'pu-unlink') choiceDialog('解除节点关联', '解除后面板不再管理该节点上的这个用户。', [['release', '保留节点上的统一用户，改为在节点本地管理'], ['delete', '删除节点上的统一用户和全部协议账号（旧连接失效）']], async mode => { await post('/links/' + b.dataset.link + '/remove', {mode}); toast('已提交，节点在线时自动执行'); await userDetail(currentUser.id); });
    else if (action === 'pu-delete') choiceDialog('删除用户', currentUser.links.length ? '先从所有关联节点解除，完成后删除此平台用户。' : '删除此平台用户。', currentUser.links.length ? [['release', '保留各节点上的统一用户（改为本地管理）'], ['delete', '同时删除各节点上的统一用户和协议账号']] : [['release', '确认删除']], async mode => { const r = await post('/users/' + currentUser.id + '/delete', {mode}); if (r.deleted) location.hash = 'users'; else await userDetail(currentUser.id); });
    else if (action === 'pu-share') {
        const link = currentUser.links.find(l => l.id === b.dataset.link), node = nodes.find(n => n.id === link.node_id);
        const instance = node?.snapshot.instances?.find(i => i.core === b.dataset.core && i.protocol === b.dataset.protocol && i.port === Number(b.dataset.port));
        if (!node || !instance || node.status !== 'online') throw new Error('节点离线或协议实例不存在');
        selected = node;
        await submitTask('share', instance, {name: b.dataset.name});
    }
}

async function userTraffic() {
    const main = $('.main');
    if (!main || $('#user-traffic')) return;
    const data = await api('/users');
    main.insertAdjacentHTML('beforeend', `<section id="user-traffic"><div class="section-label"><h2>按用户 · 跨节点合计</h2><a href="#users">用户管理 →</a></div><div class="panel table-wrap"><table><thead><tr><th>用户</th><th class="num">本周期合计</th><th class="num">配额</th><th class="num">剩余</th><th>各节点</th><th>状态</th></tr></thead><tbody>${data.users.map(u => `<tr><td><a href="#users/${esc(u.id)}">${esc(u.name)}</a></td><td class="num">${bytes(u.used)}</td><td class="num">${u.quota ? bytes(u.quota) : '不限'}</td><td class="num">${u.quota ? bytes(Math.max(0, u.quota - u.used)) : '不限'}</td><td>${u.links.map(l => esc(l.node_name) + ' ' + bytes(l.cycle_used)).join('<br>') || '—'}</td><td>${stateBadge(userStates, u.state)}</td></tr>`).join('') || '<tr><td colspan="6">暂无平台用户</td></tr>'}</tbody></table></div><p class="helper traffic-note">合计为各节点本周期用量之和，按面板时区和用户的重置日切换周期；离线节点按最后一次快照计算。</p></section>`);
}

// 协议的用户模式（节点快照 user_mode；旧节点没有该字段时沿用原规则）
function userModeText(i) {
    if (!i.user_mode) return SINGLE_USER.includes(i.protocol) ? '一用户一端口' : '多用户';
    if (i.user_mode === 'none') return '不支持用户管理';
    if (!i.user_available) return '暂未接入用户管理';
    if (i.user_mode === 'multi') return '多用户';
    return '一用户一实例，按' + (i.user_stats === 'inbound' ? '入站' : '端口') + '统计' + ((i.users || []).length ? '，已有用户' : '，空实例');
}
function memberAddable(i) {
    if (!i.user_mode) return !SINGLE_USER.includes(i.protocol) && i.managed !== false;
    return i.user_available && (i.user_mode === 'multi' || (i.user_mode === 'single' && !(i.users || []).length));
}

// 安装协议时选择平台用户（仅以平台为准的节点）
async function installUserPicker(node = selected) {
    if (!node || !usersReady(node) || $('#install-users')) return;
    const data = await api('/users').catch(() => ({users: []}));
    const box = $('#install-form .install-scroll');
    if (!box || $('#install-users')) return;
    const users = data.users.filter(u => !u.deleting);
    box.insertAdjacentHTML('beforeend', `<fieldset id="install-users" class="install-users"><legend>平台用户</legend><div class="install-user-list">${users.map(u => `<label class="field-check"><input type="checkbox" value="${esc(u.id)}">${esc(u.name)}</label>`).join('') || '<span class="muted">暂无平台用户</span>'}</div><p class="helper">可不选，之后在「用户管理」中关联；一用户一实例的协议只能选一个。</p></fieldset>`);
}
function installPickedUsers() {
    return [...document.querySelectorAll('#install-users input:checked')].map(c => c.value);
}
async function installPlaceUsers(users, nodeId = selected.id) {
    try {
        await post('/nodes/' + nodeId + '/install-users', {task_id: activeTaskId, user_ids: users});
        toast('安装完成后将为 ' + users.length + ' 个用户新建协议账号');
    } catch (err) {
        toast('实例已提交安装，但未能登记用户：' + err.message);
    }
}

// ---------------------------------------------------------------- 通知配置（TG 通知、用户查询机器人与绑定码）
async function monitorPage() {
    const data = await api('/monitor'), c = data.config, bound = data.users.filter(u => u.bound).length;
    shell(`<div class="heading"><div><h1>通知配置</h1></div><button data-action="monitor-settings" class="primary">通知设置</button></div>
    <div class="panel status-panel"><div class="status-main"><h2 class="status-title ${c.enabled ? 'on' : 'off'}">${c.enabled ? 'TG 通知已启用' : 'TG 通知未启用'}</h2><p>Bot Token：${c.token_configured ? '已配置' : '未配置'} · Chat ID：${c.chat_id ? esc(c.chat_id) : '未配置'} · 每日报告：${c.daily_enabled ? '每天 ' + esc(c.daily_time) : '关闭'}</p><p class="helper">节点离线超过 2 分钟、任务异常、到期前 3 天、流量达到 ${Number(c.quota_percent)}% 和用尽时提醒，恢复后再通知一次。监控检查：${date(Number(data.heartbeat) || 0)}。发送失败的消息不重发，也不保留发送记录。</p></div><button data-action="notification-test" ${c.enabled ? '' : 'disabled'}>测试发送</button></div>
    <div class="panel status-panel"><div class="status-main"><h2 class="status-title ${c.bot_enabled ? 'on' : 'off'}">${c.bot_enabled ? '用户查询机器人已启用' : '用户查询机器人未启用'}</h2><p>已绑定用户：${bound} / ${data.users.length}</p><p class="helper">复用上面的 Bot Token，启用时移除该 Bot 的 webhook，由面板轮询消息。已绑定的用户私聊机器人可查询所有节点合计流量与到期，并收到自己的流量和到期提醒。命令：/bind 绑定码、/traffic、/status、/unbind、/help。</p></div><button data-action="pu-tg-bot" data-enabled="${c.bot_enabled ? '' : '1'}" ${c.token_configured ? '' : 'disabled'}>${c.bot_enabled ? '禁用机器人' : '启用机器人'}</button></div>
    <div class="section-label"><h2>用户绑定 <span class="count">${data.users.length}</span></h2></div>
    <div class="panel">${data.users.length ? `<div class="table-wrap"><table><thead><tr><th>平台用户</th><th>Telegram</th><th>绑定时间</th><th>操作</th></tr></thead><tbody>${data.users.map(u => `<tr><td><a href="#users/${esc(u.id)}"><strong>${esc(u.name)}</strong></a>${u.note ? `<br><span class="muted">${esc(u.note)}</span>` : ''}</td><td>${u.bound ? (u.username ? '@' + esc(u.username) : '已绑定') : `<span class="muted">${u.code_pending ? '绑定码待使用' : '未绑定'}</span>`}</td><td class="muted">${u.bound ? date(u.bound_at) : '—'}</td><td><div class="action-row"><button class="small" data-action="pu-tg-code" data-id="${esc(u.id)}" data-name="${esc(u.name)}">${u.bound || u.code_pending ? '重新生成绑定码' : '生成绑定码'}</button>${u.bound ? `<button class="small" data-action="pu-tg-unbind" data-id="${esc(u.id)}" data-name="${esc(u.name)}">解除绑定</button>` : ''}</div></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty"><p>暂无平台用户。先在「用户管理」中创建用户，再为其生成绑定码。</p></div>'}</div>`, 'monitor');
}

async function notificationSettings() {
    const {config: c} = await api('/monitor');
    modal('通知设置', `<form id="notification-form"><label class="field-check"><input id="notify-enabled" type="checkbox" ${c.enabled ? 'checked' : ''}>启用 TG 通知</label><label for="bot-token">Bot Token</label><input id="bot-token" type="password" autocomplete="new-password" placeholder="${c.token_configured ? '已设置，留空保留' : '从 @BotFather 获取'}"><label class="field-check"><input id="clear-token" type="checkbox">清除 Bot Token（同时停用用户机器人）</label><label for="chat-id">Chat ID</label><input id="chat-id" value="${esc(c.chat_id || '')}" placeholder="从 @userinfobot 获取，群组以 - 开头"><label for="quota-percent">流量告警阈值（%）</label><input id="quota-percent" type="number" min="50" max="99" step="1" value="${Number(c.quota_percent) || 80}" required><label class="field-check"><input id="daily-enabled" type="checkbox" ${c.daily_enabled ? 'checked' : ''}>每日流量报告</label><label for="daily-time">报告时间（面板服务器时区）</label><input id="daily-time" type="time" value="${esc(c.daily_time || '09:00')}" required><p class="helper">更换 Bot Token 后需要重新启用用户机器人。报告在设定时间后一小时内发送一次。</p><div class="error" role="alert"></div><div class="modal-foot"><button type="button" data-action="close">取消</button><button type="submit" class="primary">保存设置</button></div></form>`);
    $('#notification-form').onsubmit = async e => {
        e.preventDefault();
        const button = $('[type=submit]', e.target);
        button.disabled = true;
        try {
            await post('/monitor', {enabled: $('#notify-enabled').checked, bot_token: $('#clear-token').checked ? '' : $('#bot-token').value,
                chat_id: $('#chat-id').value.trim(), clear_token: $('#clear-token').checked, quota_percent: Number($('#quota-percent').value),
                daily_enabled: $('#daily-enabled').checked, daily_time: $('#daily-time').value});
            $('#modal').close();
            await monitorPage();
        } catch (err) { formError(err); } finally { button.disabled = false; }
    };
}

async function notifyAction(action, b) {
    if (action === 'pu-tg-bot') {
        const enabled = b.dataset.enabled === '1';
        b.disabled = true;
        try {
            const r = await post('/monitor/bot', {enabled});
            toast(enabled ? '用户查询机器人已启用' + (r.username ? '：@' + r.username : '') : '用户查询机器人已禁用，绑定关系保留');
            await monitorPage();
        } finally { b.disabled = false; }
    } else if (action === 'pu-tg-code') {
        const r = await post('/users/' + b.dataset.id + '/tg-code');
        await monitorPage();
        modal('绑定码 · ' + b.dataset.name, `<p>请用户私聊用户查询机器人，发送下面的命令完成绑定：</p><label for="bind-command">绑定命令</label><input id="bind-command" class="mono" readonly value="/bind ${esc(r.code)}"><p class="helper">有效期至 ${date(r.expires)}，只能使用一次，此处只显示一次；重新生成会使旧码失效。已绑定的用户用新码绑定后改为新的 Telegram。用户查询机器人未启用时无法绑定。</p><div class="modal-foot"><button type="button" data-action="close">完成</button></div>`);
        $('#bind-command').select?.();
    } else if (action === 'pu-tg-unbind') {
        choiceDialog('解除 Telegram 绑定', '解除后该用户不再收到个人提醒，也不能通过机器人查询；之后可以重新生成绑定码。', [], async () => {
            await post('/users/' + b.dataset.id + '/tg-unbind');
            toast('已解除 ' + b.dataset.name + ' 的 Telegram 绑定');
            await monitorPage();
        });
    }
}

// ---------------------------------------------------------------- 面板地址（绑定域名切换 HTTPS、节点改用新地址、关闭旧地址）
const panelMigrationText = {succeeded: '已切换', failed: '失败', unknown: '结果未知', queued: '等待节点', running: '切换中', missing: '未通知'};
async function panelAddressDialog() {
    const d = await api('/panel-address'), st = d.status, m = d.migration;
    const busy = d.pending || st?.state === 'running';
    const statusLine = busy ? '<div class="notice">正在处理地址变更（申请证书、配置 Nginx、重启面板），请稍候…</div>'
        : st?.state === 'failed' ? `<div class="notice warn">上次操作失败：${esc(st.message)}</div>`
        : st?.state === 'succeeded' ? `<div class="notice">${esc(st.message)}</div>` : '';
    const failedNodes = (m?.nodes || []).filter(n => !['succeeded', 'queued', 'running'].includes(n.status));
    const migration = m && m.total ? `<section class="pa-migration"><h3>节点改用新地址 <span class="count">${m.done} / ${m.total}</span></h3>${m.nodes.map(n => `<div class="kv"><span>${esc(n.name)}</span><span>${esc(panelMigrationText[n.status] || n.status)}${n.status === 'failed' && n.message ? `<br><span class="muted">${esc(n.message)}</span>` : ''}</span></div>`).join('')}<div class="action-row">${failedNodes.length ? '<button type="button" data-action="pa-retry">重新通知未切换的节点</button>' : ''}${d.legacy_open ? '<button type="button" data-action="pa-close">关闭旧地址</button>' : ''}</div><p class="helper">节点需升级到 1.1.0 及以上才能自动改用新地址；旧地址（未加密的 IP 地址或原域名）在关闭前继续可用。</p></section>` : (d.legacy_open ? '<div class="action-row"><button type="button" data-action="pa-close">关闭旧地址</button></div>' : '');
    modal('系统设置', `${settingsTabs('address')}<div class="kv"><span>当前地址</span><span class="mono">${esc(d.url)}</span></div><div class="kv"><span>连接</span><span>${d.secure ? 'HTTPS 加密' : 'HTTP 未加密'}</span></div>${statusLine}
<form id="pa-form"><div class="install-grid"><div><label for="pa-domain">域名</label><input id="pa-domain" maxlength="253" placeholder="panel.example.com" required></div><div><label for="pa-port">HTTPS 端口</label><input id="pa-port" type="number" min="1" max="65535" value="443" required></div></div>
<p class="helper">先把域名解析到本服务器，并放行 TCP 80（申请证书）与该端口。提交后自动申请证书、配置 Nginx 并重启面板，失败会恢复原配置；完成后请用新地址访问，节点会自动收到新地址。</p>
${d.helper ? '' : '<div class="notice warn">此面板缺少地址辅助服务（升级到 1.1.0 后自动安装）。也可在服务器以 root 执行：vaio-panel domain 域名 端口</div>'}
<div class="error" role="alert"></div><div class="modal-foot"><button type="button" data-action="close">关闭</button><button type="submit" class="primary"${busy || !d.helper ? ' disabled' : ''}>${d.secure ? '更换域名' : '绑定域名并切换 HTTPS'}</button></div></form>${migration}`);
    $('#pa-form').onsubmit = async e => {
        e.preventDefault();
        const button = $('[type=submit]', e.target);
        button.disabled = true;
        try {
            await post('/panel-address', {domain: $('#pa-domain').value.trim(), port: Number($('#pa-port').value)});
            toast('已提交，正在申请证书并切换地址');
            await panelAddressDialog();
        } catch (err) { formError(err); button.disabled = false; }
    };
    if (busy) setTimeout(() => { if ($('#modal').open && $('#pa-form')) panelAddressDialog().catch(() => {}); }, 4000);
}
async function panelAddressAction(action) {
    if (action === 'pa-open') return panelAddressDialog();
    if (action === 'pa-retry') {
        const r = await post('/panel-address/retry');
        toast(r.queued ? '已重新通知 ' + r.queued + ' 个节点' : '没有需要重新通知的节点');
        return panelAddressDialog();
    }
    if (action === 'pa-close') {
        const d = await api('/panel-address');
        const waiting = (d.migration?.nodes || []).filter(n => n.status !== 'succeeded').map(n => n.name);
        choiceDialog('关闭旧地址', waiting.length ? `以下节点尚未改用新地址：${waiting.map(esc).join('、')}。关闭后它们将无法连接面板，需要在节点重新执行安装命令。确定关闭？`
            : '关闭未加密的 IP 地址（或原域名），之后只能通过当前 HTTPS 地址访问面板。', [], async () => {
            await post('/panel-address/close-legacy', waiting.length ? {force: true} : {});
            toast('正在关闭旧地址');
        });
    }
}

// ---------------------------------------------------------------- 用户自助（平台用户登录后只看自己的账号）
let portalState = null;
const relayStateText = {creating: '创建中', active: '正常', partial: '部分失败', removing: '删除中'};

function randomPassword() {
    const chars = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789', bytes = crypto.getRandomValues(new Uint8Array(14));
    return Array.from(bytes, n => chars[n % chars.length]).join('');
}

async function portal() {
    const me = await api('/me');
    csrf = me.csrf;
    panelVersion = me.version;
    portalState = me;
    if ($('#modal').open && $('#me-share')) return;          // keep an open connection dialog
    $('#app').innerHTML = portalPage(me);
    clearTimeout(portal.timer);
    portal.timer = setTimeout(() => { if (portalState) portal().catch(() => {}); }, 30000);
}

function portalPage(me) {
    const quota = me.quota ? bytes(me.quota) : '不限流量';
    const left = me.quota ? bytes(Math.max(0, me.quota - me.used)) : '不限';
    const percent = me.quota ? Math.min(100, me.used / me.quota * 100) : null;
    const links = me.links.map(l => `<tr><td data-label="服务器"><span>${esc(l.node_name)}${l.online ? '' : ' <span class="muted">离线</span>'}</span></td><td data-label="协议 · 端口"><div>${l.members.map(m => `<div class="portal-member"><span>${esc(names[m.protocol] || m.protocol)} <span class="muted mono">${m.port}</span>${m.enabled ? '' : ' <span class="muted">已停用</span>'}</span>${m.enabled ? `<button class="small" data-action="me-share" data-link="${esc(l.id)}" data-core="${esc(m.core)}" data-protocol="${esc(m.protocol)}" data-port="${m.port}"${l.online ? '' : ' disabled'}>连接信息</button>` : ''}</div>`).join('') || '<span class="muted">等待服务器创建</span>'}</div></td><td class="num" data-label="本周期用量">${bytes(l.cycle_used)}</td></tr>`).join('');
    const relays = me.relays.map(r => `<tr><td class="relay-chain" data-label="线路"><span>${r.chain.map(esc).join('<span class="relay-chain-arrow" aria-hidden="true">→</span>')}</span></td><td class="mono" data-label="入口">${esc(r.entry || '—')}</td><td data-label="落地协议">${r.port_only ? '仅转发端口' : esc(names[r.protocol] || r.protocol)}</td><td data-label="状态">${r.blocked ? `<span class="badge blocked">${esc(r.blocked)}</span>` : `<span class="badge ${r.state === 'active' ? 'running' : 'stopped'}">${esc(relayStateText[r.state] || r.state)}</span>`}</td><td>${r.state === 'active' && !r.port_only && !r.blocked ? `<button class="small" data-action="me-share-relay" data-id="${esc(r.id)}">连接信息</button>` : ''}</td></tr>`).join('');
    return `<div class="portal"><header class="portal-head">${brand}<div class="portal-account"><span class="muted">${esc(me.name)}</span><button class="quiet small" data-action="me-password">修改密码</button><button class="quiet small" data-action="logout">退出</button></div></header><main class="portal-main">
<div class="heading"><div><h1>${esc(me.name)} ${stateBadge(userStates, me.state)}</h1><p class="subtext">我的账号 · 用量每分钟同步</p></div></div>
<div class="stats">${stat('本周期用量', bytes(me.used).split(' ')[0], '配额 ' + quota, bytes(me.used).split(' ')[1] || '')}${stat('剩余', left.split(' ')[0], percent == null ? '未设置配额' : '已用 ' + percent.toFixed(0) + '%', me.quota ? left.split(' ')[1] || '' : '')}${stat('到期', me.expire_date || '永久', me.expire_date ? '到期后所有协议停用' : '不会到期')}${stat('流量重置', me.reset_day ? me.reset_day + ' 日' : '不重置', me.reset_day ? '每月该日清零用量' : '累计计算')}</div>
<div class="section-label"><h2>我的协议 <span class="count">${me.links.reduce((n, l) => n + l.members.length, 0)}</span></h2></div><div class="panel table-wrap"><table><thead><tr><th>服务器</th><th>协议 · 端口</th><th class="num">本周期用量</th></tr></thead><tbody>${links || '<tr><td colspan="3">还没有可用的协议，请联系管理员。</td></tr>'}</tbody></table></div>
${me.relays.length ? `<div class="section-label"><h2>中转线路 <span class="count">${me.relays.length}</span></h2></div><div class="panel table-wrap"><table><thead><tr><th>线路</th><th>入口</th><th>落地协议</th><th>状态</th><th></th></tr></thead><tbody>${relays}</tbody></table></div><p class="helper">经中转的流量计入落地服务器上的协议用量。</p>` : ''}
${telegramCard(me.telegram)}</main></div>`;
}

function telegramCard(tg) {
    const bot = tg.bot || {};
    const botLine = bot.enabled ? (bot.username ? `<a href="https://t.me/${encodeURIComponent(bot.username)}" target="_blank" rel="noopener">@${esc(bot.username)}</a>` : '已启用') : '未启用';
    let body;
    if (!bot.enabled) body = '<p class="muted">管理员尚未启用 Telegram 机器人，启用后可以在这里绑定，用机器人查询流量和到期时间。</p>';
    else if (tg.bound) body = `<div class="kv"><span>绑定状态</span><span>已绑定${tg.username ? ' @' + esc(tg.username) : ''}</span></div>${tg.bound_at ? `<div class="kv"><span>绑定时间</span><span>${date(tg.bound_at)}</span></div>` : ''}<div class="action-row"><button data-action="me-tg-unbind">解除绑定</button></div>`;
    else body = `<div class="kv"><span>绑定状态</span><span>未绑定${tg.code_pending ? '（已生成绑定码，尚未使用）' : ''}</span></div><p class="helper">生成绑定码后，私聊机器人发送 <span class="mono">/bind 绑定码</span>；绑定后可发送 /traffic 查询流量，/status 查询到期时间。</p><div class="action-row"><button class="primary" data-action="me-tg-code">${tg.code_pending ? '重新生成绑定码' : '生成绑定码'}</button></div>`;
    return `<div class="section-label"><h2>Telegram</h2></div><section class="panel portal-card"><div class="kv"><span>机器人</span><span>${botLine}</span></div>${body}</section>`;
}

async function portalShare(payload) {
    const r = await post('/me/share', payload);
    modal('连接信息', `<div id="me-share"><p class="muted">正在从服务器读取连接信息…</p></div><div class="modal-foot"><button data-action="close">关闭</button></div>`, true);
    await portalShareWait(r.id, Date.now());
}
async function portalShareWait(id, started) {
    if (!$('#modal').open || !$('#me-share')) return;
    const t = await api('/me/tasks/' + encodeURIComponent(id));
    const box = $('#me-share');
    if (t.status === 'succeeded' && t.connection) {
        box.innerHTML = `<label for="connection">连接信息</label><textarea id="connection" readonly>${esc(t.connection)}</textarea><button data-action="copy-connection">复制连接信息</button><p>连接二维码</p><img class="connection-qr" src="/api/me/tasks/${encodeURIComponent(id)}/qr" alt="连接信息二维码" width="240" height="240"><p class="helper">10 分钟后失效，需要时重新读取。</p>`;
    } else if (['failed', 'unknown', 'cancelled'].includes(t.status) || t.status === 'succeeded') {
        box.innerHTML = `<p class="error">读取失败：${esc(t.message || '服务器没有返回连接信息')}</p>`;
    } else if (Date.now() - started > 90000) {
        box.innerHTML = '<p class="error">服务器暂未响应，请稍后再试。</p>';
    } else {
        setTimeout(() => portalShareWait(id, started).catch(err => { if ($('#me-share')) $('#me-share').innerHTML = `<p class="error">${esc(err.message)}</p>`; }), 2000);
    }
}

function portalPasswordDialog() {
    modal('修改密码', `<form id="me-password-form"><label for="me-current">当前密码</label><input id="me-current" type="password" required autocomplete="current-password"><label for="me-new">新密码</label><input id="me-new" type="password" minlength="8" maxlength="128" required autocomplete="new-password"><label for="me-confirm">确认新密码</label><input id="me-confirm" type="password" maxlength="128" required autocomplete="new-password"><p class="helper">8–128 位。保存后所有设备需要重新登录。</p><div class="error" role="alert"></div><div class="modal-foot"><button type="button" data-action="close">取消</button><button class="primary" type="submit">保存</button></div></form>`);
    $('#me-password-form').onsubmit = async e => {
        e.preventDefault();
        if ($('#me-new').value !== $('#me-confirm').value) return formError(new Error('两次输入的新密码不一致'));
        const button = $('[type=submit]', e.target); button.disabled = true;
        try {
            await post('/me/password', {current_password: $('#me-current').value, new_password: $('#me-new').value, confirm_password: $('#me-confirm').value});
            portalState = null; csrf = '';
            $('#modal').close(); login(); toast('密码已修改，请重新登录');
        } catch (err) { formError(err); button.disabled = false; }
    };
}

async function portalAction(action, b) {
    if (action === 'me-share') await portalShare({link_id: b.dataset.link, core: b.dataset.core, protocol: b.dataset.protocol, port: Number(b.dataset.port)});
    else if (action === 'me-share-relay') await portalShare({relay_id: b.dataset.id});
    else if (action === 'me-password') portalPasswordDialog();
    else if (action === 'me-tg-code') {
        const r = await post('/me/tg-code');
        const bot = portalState?.telegram?.bot?.username;
        modal('Telegram 绑定码', `<p>私聊${bot ? ` <a href="https://t.me/${encodeURIComponent(bot)}" target="_blank" rel="noopener">@${esc(bot)}</a>` : '机器人'}，发送：</p><textarea id="connection" readonly rows="1">/bind ${esc(r.code)}</textarea><button data-action="copy-connection">复制</button><p class="helper">24 小时内有效，只能使用一次；重新生成后旧绑定码失效。</p><div class="modal-foot"><button class="primary" data-action="close">完成</button></div>`);
        await portal();
    } else if (action === 'me-tg-unbind') choiceDialog('解除 Telegram 绑定', '解除后不再收到提醒，也不能用机器人查询；之后可以重新生成绑定码绑定。', [], async () => { await post('/me/tg-unbind'); toast('已解除绑定'); await portal(); });
}

// ---------------------------------------------------------------- 系统设置、面板更新、一键更新节点程序
function settingsTabs(active) {
    return `<div class="tabs settings-tabs">${[['account', '账号'], ['address', '面板地址'], ['backup', '备份恢复']].map(([id, text]) => `<button type="button" data-action="settings-tab" data-tab="${id}" class="${active === id ? 'active' : ''}"${active === id ? ' aria-current="page"' : ''}>${text}</button>`).join('')}</div>`;
}

// Node program version against the panel's (nodes upgrade to the panel's own version).
function nodeVersion(node) {
    const v = node.snapshot.agent_version;
    if (!v) return '<div class="node-version"><span class="muted">节点程序 —</span></div>';
    return `<div class="node-version${node.upgrade_available ? ' outdated' : ''}"><span>节点程序 <span class="mono">${esc(v)}</span></span><span class="muted">${node.upgrade_available ? '最新 <span class="mono">' + esc(node.panel_version) + '</span>' : '已是最新'}</span></div>`;
}

let panelUpdate = null, panelUpdateChecked = false;
function panelUpdateLabel() {
    if (panelUpdate?.pending || panelUpdate?.status?.state === 'running') return '面板更新<span class="update-dot">更新中</span>';
    return panelUpdate?.newer ? `面板更新<span class="update-dot">新版本 ${esc(panelUpdate.latest)}</span>` : '面板更新';
}
function setPanelUpdate(d) {
    panelUpdate = d;
    const button = document.querySelector('[data-action="panel-update"]');
    if (button) button.innerHTML = panelUpdateLabel();
    watchPanelUpdate();
}
// While an update runs (the panel restarts during it), keep the sidebar label current even with the dialog closed.
function watchPanelUpdate() {
    if (watchPanelUpdate.timer || !(panelUpdate?.pending || panelUpdate?.status?.state === 'running')) return;
    watchPanelUpdate.timer = setTimeout(() => {
        watchPanelUpdate.timer = null;
        api('/panel-update').then(setPanelUpdate).catch(() => watchPanelUpdate());
    }, 5000);
}

// Once per page load, in the background: the server caches the GitHub answer, so this stays cheap.
function checkPanelUpdate() {
    if (panelUpdateChecked) return;
    panelUpdateChecked = true;
    api('/panel-update').then(setPanelUpdate).catch(() => {});
}

const panelUpdateRelease = 'https://github.com/mozisen/vaio-panel/releases';
// refresh: opened by the admin, so ask GitHub now instead of the cached answer.
async function panelUpdateDialog(refresh = false) {
    let d;
    try { d = await api('/panel-update' + (refresh ? '?refresh=1' : '')); } catch (err) {
        // The panel restarts during an update; keep waiting while the dialog is open.
        if (panelUpdate?.status?.state === 'running' || panelUpdate?.pending) {
            if ($('#modal').open && $('#pu-update')) setTimeout(() => { if ($('#modal').open && $('#pu-update')) panelUpdateDialog().catch(() => {}); }, 4000);
            return;
        }
        throw err;
    }
    setPanelUpdate(d);
    const st = d.status, busy = d.pending || st?.state === 'running';
    const reload = d.current !== panelVersion;
    const statusLine = busy ? `<div class="notice">${esc(st?.state === 'running' ? st.message : '已提交更新，等待开始…')}</div>`
        : reload ? `<div class="notice"><div>面板已更新到 ${esc(d.current)}，请刷新页面加载新界面。</div><button type="button" onclick="location.reload()">刷新页面</button></div>`
        : st?.state === 'failed' ? `<div class="notice warn">${esc(st.message)}</div>` : '';
    const latest = d.latest ? `<span class="mono">${esc(d.latest)}</span>` : '<span class="muted">未知</span>';
    const checked = d.reachable ? date(d.checked) : '暂时无法连接 GitHub，稍后自动重试';
    let foot = '<button type="button" data-action="close">关闭</button>';
    let manual = '';
    if (d.newer && !busy && !reload) {
        if (d.helper) foot += `<button type="button" class="primary" data-action="panel-update-start" data-version="${esc(d.latest)}">更新到 ${esc(d.latest)}</button>`;
        else {
            currentCommand = 'vaio-panel update --ref ' + d.latest;
            manual = `<div class="notice warn">${d.installing ? '正在自动安装更新辅助服务，稍后重新打开即可在面板中直接更新。也可' : '此面板缺少更新辅助服务。请'}在面板服务器以 root 执行：</div><textarea readonly rows="1">${esc(currentCommand)}</textarea>`;
            foot += '<button type="button" class="primary" data-action="copy-command">复制更新命令</button>';
        }
    }
    modal('面板更新', `<div id="pu-update"><div class="kv"><span>当前版本</span><span class="mono">${esc(d.current)}</span></div><div class="kv"><span>最新版本</span><span>${latest}${d.newer ? ' <span class="badge running">可更新</span>' : d.latest ? ' <span class="muted">已是最新</span>' : ''}</span></div><div class="kv"><span>检查时间</span><span>${esc(checked)}</span></div><div class="kv"><span>版本说明</span><span><a href="${panelUpdateRelease}" target="_blank" rel="noopener">GitHub Releases</a></span></div>${statusLine}${manual}
<p class="helper">打开面板时在后台检查 ${esc(d.repository)} 的正式版本，打开此窗口时立即重新检查。更新前自动备份数据并运行测试，新版无法启动会恢复原版本；更新期间面板会短暂重启，节点代理不受影响。有节点任务未完成时无法更新。</p><div class="error" role="alert"></div><div class="modal-foot">${foot}</div></div>`);
    if (busy) setTimeout(() => { if ($('#modal').open && $('#pu-update')) panelUpdateDialog().catch(() => {}); }, 4000);
}
async function panelUpdateStart(b) {
    b.disabled = true;
    try {
        await post('/panel-update', {version: b.dataset.version});
        setPanelUpdate({...panelUpdate, pending: true});
        toast('已开始更新面板到 ' + b.dataset.version);
        await panelUpdateDialog();
    } catch (err) { formError(err); b.disabled = false; }
}

function upgradeAllDialog() {
    const outdated = nodes.filter(n => n.adopted && n.upgrade_available);
    modal('一键更新节点程序', `<p>将以下 ${outdated.length} 台服务器的节点程序与节点脚本更新到面板版本 <span class="mono">${esc(panelVersion)}</span>：</p><div class="upgrade-list">${outdated.map(n => `<div class="kv"><span>${esc(n.name)}</span><span class="mono">${esc(n.snapshot.agent_version)} → ${esc(n.panel_version)}</span></div>`).join('')}</div><p class="helper">更新会保留节点身份、协议与用户，新版未上线会自动恢复旧程序；不会更新代理内核。离线、维护中或有未完成任务的服务器会跳过。</p><div class="error" role="alert"></div><div class="modal-foot"><button type="button" data-action="close">取消</button><button type="button" class="primary" data-action="upgrade-all-confirm">开始更新</button></div>`);
}
async function upgradeAllStart(b) {
    b.disabled = true;
    let r;
    try { r = await post('/nodes/upgrade-all'); } catch (err) { formError(err); b.disabled = false; return; }
    const queued = r.queued.length ? `<p>已为 ${r.queued.length} 台服务器创建更新任务：${r.queued.map(esc).join('、')}。进度见任务记录。</p>` : '<p>没有服务器可以立即更新。</p>';
    const skipped = r.skipped.length ? `<h3>已跳过</h3>${r.skipped.map(x => `<div class="kv"><span>${esc(x.name)}</span><span>${esc(x.reason)}</span></div>`).join('')}` : '';
    modal('一键更新节点程序', `${queued}${skipped}<div class="modal-foot"><button type="button" data-action="close" onclick="location.hash='tasks'">查看任务</button><button type="button" class="primary" data-action="close">完成</button></div>`);
    await refresh();
}

// ---------------------------------------------------------------- 内核（Xray / Sing-box / Snell）版本与一键更新
const vkey = v => (v || '').split('.').map(Number);
const newer = (a, b) => { const x = vkey(a), y = vkey(b); for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); return false; };
// Updatable: a newer latest version, or Sing-box without per-user statistics (the statistics build replaces it).
function coreUpdatable(core, item) {
    // Snell v5 and v6 are separate cores: a version of the other major line is never an update.
    const major = {'snell-v5': '5.', 'snell-v6': '6.'}[core];
    if (major && !String(item?.latest || '').startsWith(major)) return false;
    return !!item?.latest && (newer(item.latest, item.current) || (core === 'singbox' && !item.stats));
}
// "current → latest", "1.14.2 → 统计版" (same version, statistics build), or "current · 已是最新".
function coreVersionText(core, item) {
    const major = {'snell-v5': '5.', 'snell-v6': '6.'}[core];
    if (!item.latest || (major && !item.latest.startsWith(major))) return `${esc(item.current)} · 最新版本获取中`;
    if (!coreUpdatable(core, item)) return `${esc(item.current)} · 已是最新`;
    return `${esc(item.current)} → ${item.latest === item.current ? '统计版' : esc(item.latest)}`;
}
function coreBlock(node) {
    const s = node.snapshot;
    if (!node.adopted) return '';
    if (s.core_update_version !== 1) return '<section class="info-block"><h3>内核</h3><p class="helper">节点程序更新到 1.4.0 及以上后，可在这里查看并更新 Xray、Sing-box 与 Snell 内核。</p></section>';
    const cores = s.cores || {};
    const rows = Object.keys(coreLabels).filter(c => cores[c]).map(c => {
        const item = cores[c], can = coreUpdatable(c, item);
        const state = `<span class="core-version${can ? '' : ' muted'}">${coreVersionText(c, item)}</span>`;
        const notes = [];
        if (c === 'singbox' && !item.stats) notes.push('当前核心不带用户统计，更新后恢复统计');
        if (c === 'singbox' && item.official && newer(item.official, item.latest || item.current)) notes.push(`官方已有 ${esc(item.official)}，统计版待发布`);
        return `<div class="kv core-row"><span>${coreLabels[c]}</span><span>${state}${can ? ` <button class="small" data-action="core-update" data-core="${c}"${node.status === 'online' && !node.maintenance ? '' : ' disabled'}>更新</button>` : ''}</span></div>${notes.map(n => `<p class="helper">${n}</p>`).join('')}`;
    }).join('');
    return `<section class="info-block"><h3>内核</h3>${rows || '<p class="helper">未安装 Xray、Sing-box 或 Snell 内核。</p>'}</section>`;
}
function coreUpdatableNodes(core) {
    return nodes.filter(n => n.adopted && !n.deleted && n.snapshot.core_update_version === 1 && coreUpdatable(core, (n.snapshot.cores || {})[core]));
}
// One-click core updates: every server's installed cores with current and latest versions; update one server or all.
function coreAllDialog() {
    const busyNode = n => tasks.some(t => t.node_id === n.id && ['queued', 'running', 'unknown'].includes(t.status));
    const updating = (n, c) => tasks.some(t => t.node_id === n.id && t.action === 'core_update' && t.request.params?.core === c && ['queued', 'running'].includes(t.status));
    const servers = nodes.filter(n => n.adopted && !n.deleted);
    const batch = Object.entries(coreLabels).map(([c, label]) => [c, label, coreUpdatableNodes(c).filter(n => n.status === 'online' && !n.maintenance && !busyNode(n)).length]);
    const rows = servers.map(n => {
        const s = n.snapshot, cores = s.cores || {};
        let body;
        if (s.core_update_version !== 1) body = '<p class="helper">节点程序需更新到 1.4.0 及以上</p>';
        else if (!Object.keys(coreLabels).some(c => cores[c])) body = '<p class="helper">未安装 Xray、Sing-box 或 Snell 内核</p>';
        else body = Object.keys(coreLabels).filter(c => cores[c]).map(c => {
            const item = cores[c], can = coreUpdatable(c, item);
            const action = updating(n, c) ? '<span class="muted">更新中</span>'
                : can ? `<button class="small" data-action="core-update-one" data-node="${esc(n.id)}" data-core="${c}"${n.status === 'online' && !n.maintenance && !busyNode(n) ? '' : ' disabled'}>更新</button>` : '';
            return `<div class="kv core-row"><span>${coreLabels[c]}</span><span><span class="core-version${can ? '' : ' muted'}">${coreVersionText(c, item)}</span>${action}</span></div>`;
        }).join('');
        return `<section class="core-server"><h3>${esc(n.name)} ${badge(n.status)}</h3>${body}</section>`;
    }).join('');
    modal('一键更新内核', `<div id="core-list"><div class="action-row core-batch">${batch.map(([c, label, count]) => `<button class="small" data-action="core-update-batch" data-core="${c}"${count ? '' : ' disabled'}>全部更新 ${label}（${count}）</button>`).join('')}</div>${rows || '<p class="muted">还没有接管的服务器。</p>'}<p class="helper">更新时先同步用户流量，再备份并更新内核、重启使用它的服务，失败自动恢复旧版本；该内核上的协议会短暂中断。Sing-box 更新为带用户统计的预编译版本。离线、维护中或有未完成任务的服务器不能更新。</p></div><div class="modal-foot"><button type="button" class="primary" data-action="close">完成</button></div>`, true);
}

async function coreAction(action, b) {
    if (action === 'core-update-all') return coreAllDialog();
    if (action === 'core-update-one') {
        const node = nodes.find(n => n.id === b.dataset.node);
        b.disabled = true;
        await post('/nodes/' + b.dataset.node + '/core-update', {core: b.dataset.core});
        toast(`已排队更新 ${node ? node.name : ''} 的 ${coreLabels[b.dataset.core]}，进度见任务记录`);
        await refresh();
        if ($('#modal').open && $('#core-list')) coreAllDialog();
        return;
    }
    if (action === 'core-update-batch') {
        b.disabled = true;
        const r = await post('/nodes/core-update-all', {core: b.dataset.core});
        toast(r.queued.length ? `已为 ${r.queued.length} 台服务器排队更新 ${coreLabels[b.dataset.core]}` : '没有服务器可以立即更新' + (r.skipped.length ? '：' + r.skipped.map(x => x.name + ' ' + x.reason).join('；') : ''));
        await refresh();
        if ($('#modal').open && $('#core-list')) coreAllDialog();
        return;
    }
    if (action !== 'core-update') return;
    const core = b.dataset.core, item = selected?.snapshot.cores?.[core];
    if (!selected || !item) throw new Error('内核信息不存在，请刷新后重试');
    const node = selected;
    modal('更新 ' + coreLabels[core] + ' 内核', `<form id="core-form"><p>将 ${esc(node.name)} 的 ${coreLabels[core]} 从 <span class="mono">${esc(item.current)}</span> 更新到 <span class="mono">${esc(item.latest)}</span>${core === 'singbox' ? '（带用户统计的预编译版本）' : ''}。</p><p class="helper">先同步用户流量，再备份并更新内核；更新时使用该内核的协议会短暂中断，失败自动恢复旧版本。</p><div class="error" role="alert"></div><div class="modal-foot"><button type="button" data-action="close">取消</button><button type="submit" class="primary">开始更新</button></div></form>`);
    $('#core-form').onsubmit = async e => {
        e.preventDefault();
        const button = $('[type=submit]', e.target); button.disabled = true;
        try {
            const r = await post('/nodes/' + node.id + '/core-update', {core});
            activeTaskId = r.id;
            await refresh();
            showTask(r.id);
        } catch (err) { formError(err); button.disabled = false; }
    };
}

// ---------------------------------------------------------------- 中转管理（用户 → 中转服务器 … → 落地协议）
let relayFilter = {node: '', q: ''}, relayData = [];
const relayStates = {creating: '创建中', active: '正常', partial: '部分失败', removing: '删除中'};
const relayHopStates = {pending: '创建中', active: '', failed: '失败', removing: '删除中', remove_failed: '删除失败', removed: '已删除'};
function relayMatches(line, f) {
    const q = f.q.trim().toLowerCase();
    return (!f.node || line.landing.node_id === f.node || line.hops.some(h => h.node_id === f.node))
        && (!q || [line.user_name, line.landing.node_name, ...line.hops.map(h => h.node_name)].some(v => String(v || '').toLowerCase().includes(q)));
}
function relayChain(line) {
    const arrow = '<span class="relay-chain-arrow" aria-hidden="true">→</span>';
    return line.hops.map(h => `<span>${esc(h.node_name)}<span class="muted"> · ${esc(forwardBackends[h.backend] || h.backend)}</span>${relayHopStates[h.status] ? ` <span class="muted">${esc(relayHopStates[h.status])}</span>` : ''}</span>`).join(arrow)
        + arrow + `<strong>${esc(line.landing.node_name)}</strong>`;
}
function relayTable(lines) {
    if (!lines.length) return '<div class="empty"><p>没有符合条件的中转线路。</p></div>';
    return `<div class="table-wrap"><table><thead><tr><th>用户</th><th>线路</th><th>入口</th><th>落地协议</th><th>状态</th><th>操作</th></tr></thead><tbody>${lines.map(line => {
        const data = `data-id="${esc(line.id)}"`;
        return `<tr><td>${line.user_id ? `<a href="#users/${esc(line.user_id)}">${esc(line.user_name)}</a>` : '<span class="muted">—</span>'}</td><td class="relay-chain">${relayChain(line)}</td><td class="mono">${esc(line.entry.host || '—')}:${line.entry.port}</td><td>${line.port_only ? '仅转发端口' : esc(names[line.landing.protocol] || line.landing.protocol)}<br><span class="muted mono">${esc(line.landing.host)}:${line.landing.port}</span></td><td>${line.blocked && line.state === 'active' ? `<span class="badge blocked">${esc(line.blocked)}</span>` : `<span class="badge ${line.state === 'active' ? 'running' : 'stopped'}">${esc(relayStates[line.state] || line.state)}</span>`}</td><td><div class="action-row">${line.state === 'active' && !line.port_only && !line.blocked ? `<button class="small" data-action="rl-share" ${data}>连接信息</button>` : ''}${line.state === 'partial' ? `<button class="small" data-action="rl-retry" ${data}>重试</button>` : ''}<button class="small" data-action="rl-delete" ${data}${['creating', 'removing'].includes(line.state) ? ' disabled' : ''}>删除</button></div></td></tr>`;
    }).join('')}</tbody></table></div>`;
}
async function relaysPage() {
    relayData = (await api('/relays')).relays;
    const servers = nodes.filter(n => !n.deleted);
    shell(`<div class="heading"><div><h1>中转管理</h1></div><div class="action-row"><button data-action="refresh">${icon('refresh')}刷新</button><button class="primary" data-action="rl-add">${icon('plus')}添加中转线路</button></div></div>
    <div class="section-label"><h2>线路 <span class="count" id="relay-count"></span></h2><div class="tools instance-filters">
    ${filterMenu('relay-node', '筛选服务器', [['', '全部服务器'], ...servers.map(n => [n.id, n.name])], relayFilter.node)}
    <div class="search">${icon('search')}<input id="relay-search" type="search" aria-label="搜索中转线路" placeholder="搜索用户或服务器" value="${esc(relayFilter.q)}"></div></div></div>
    <div class="panel" id="relay-results"></div>
    <p class="helper">转发协议按落地协议自动选择（Hysteria2、TUIC 为 UDP；SS、Snell 为 TCP+UDP；其余 TCP；nftables 固定 TCP+UDP）。多层中转时每一层转发到下一层的公网 IP 与入口端口。修改线路请删除后重建。</p>`, 'relays');
    const update = () => {
        const shown = relayData.filter(line => relayMatches(line, relayFilter));
        $('#relay-results').innerHTML = relayTable(shown);
        $('#relay-count').textContent = shown.length === relayData.length ? String(relayData.length) : shown.length + ' / ' + relayData.length;
    };
    $('#relay-node').onchange = e => { relayFilter.node = e.target.value; update(); };
    $('#relay-search').addEventListener('input', e => { relayFilter.q = e.target.value; update(); });
    update();
}
function relayMembers(user, nodeId) {
    return (user?.links || []).filter(l => l.node_id === nodeId).flatMap(l => l.members || []);
}
// 落地协议选项：已关联 / 将关联；不支持用户或被其他用户占用的一用户一实例不可选；最后是「仅转发端口」
function relayLandingOptions(node, user) {
    const members = relayMembers(user, node?.id);
    const items = (node?.snapshot.instances || []).map(i => {
        const member = members.some(m => m.protocol === i.protocol && m.port === i.port && m.core === i.core);
        const occupied = !member && i.user_mode === 'single' && (i.users || []).length > 0;
        const note = member ? '已关联' : i.user_available === false ? '不支持用户' : occupied ? '已被其他用户使用' : user ? '将为该用户关联' : '需选择用户';
        return {value: `${i.core}:${i.protocol}:${i.port}`, label: `${names[i.protocol] || i.protocol} · ${i.port}（${note}）`,
                disabled: i.user_available === false || occupied || !user, port: i.port};
    });
    return [...items, {value: 'port-only', label: '仅转发端口（出口机）', disabled: false, port: null}];
}
async function relayDialog() {
    const users = (await api('/users')).users.filter(u => !u.deleting);
    const relayServers = nodes.filter(n => !n.deleted && forwardWritable(n));
    const landingServers = nodes.filter(n => !n.deleted && n.adopted);
    if (!relayServers.length || !landingServers.length) return modal('暂无可用服务器', '<p>需要至少一台支持端口转发的在线服务器作为中转（节点程序需升级到最新版），以及一台已接管的服务器作为落地。</p>');
    const option = (v, label, current, disabled) => `<option value="${esc(v)}"${v === current ? ' selected' : ''}${disabled ? ' disabled' : ''}>${esc(label)}</option>`;
    // 默认取两台不同的服务器：中转优先选不是落地候选第一位的那台
    const firstRelay = relayServers.find(n => landingServers.some(l => l.id !== n.id)) || relayServers[0];
    const hops = [{node_id: firstRelay.id, backend: 'realm', listen_port: ''}];
    const firstLanding = landingServers.find(x => x.id !== firstRelay.id) || landingServers[0];
    modal('添加中转线路', `<form id="relay-form"><div class="install-top"><div class="inline-field"><label for="relay-user">用户</label><select id="relay-user">${users.map(u => option(u.id, u.name, users[0]?.id)).join('')}${option('', '不指定用户', users.length ? null : '')}</select></div></div>
<div class="relay-flow"><section class="relay-box"><h3>中转服务器</h3><div id="relay-hops"></div><button type="button" class="small" id="relay-add-hop">${icon('plus')}添加一层中转</button></section>
<div class="relay-arrow" aria-hidden="true">${icon('arrow')}</div>
<section class="relay-box"><h3>落地服务器</h3><label for="relay-landing-node">服务器</label><select id="relay-landing-node">${landingServers.map(n => option(n.id, n.name, firstLanding.id)).join('')}</select><label for="relay-landing-protocol">协议</label><select id="relay-landing-protocol"></select><div id="relay-port-only-fields" hidden><div class="relay-hop-row"><div><label for="relay-landing-port">落地端口</label><input id="relay-landing-port" type="number" min="1" max="65535"></div><div><label for="relay-landing-transport">转发协议</label><select id="relay-landing-transport">${option('tcp+udp', 'TCP + UDP', 'tcp+udp')}${option('tcp', 'TCP', '')}${option('udp', 'UDP', '')}</select></div></div></div><label for="relay-landing-host">落地地址</label><input id="relay-landing-host" maxlength="253" required placeholder="IP 或域名"><p class="helper" id="relay-landing-help"></p></section></div>
<div class="error" role="alert"></div><div class="modal-foot"><button type="button" data-action="close">取消</button><button type="submit" class="primary">创建线路</button></div></form>`, true);
    const user = () => users.find(u => u.id === $('#relay-user').value) || null;
    const nodeById = id => nodes.find(n => n.id === id);
    const portOnly = () => $('#relay-landing-protocol').value === 'port-only';
    // 入口端口默认等于落地协议（或仅转发时的落地端口）的端口，仍可手动修改。
    const landingPort = () => portOnly() ? Number($('#relay-landing-port').value) || '' : Number(($('#relay-landing-protocol').value || '').split(':')[2]) || '';
    const renderHops = () => {
        $('#relay-hops').innerHTML = hops.map((h, i) => `<div class="relay-hop"><div class="relay-hop-head"><span>第 ${i + 1} 层</span>${hops.length > 1 ? `<button type="button" class="quiet small" data-hop-remove="${i}" aria-label="删除第 ${i + 1} 层">删除</button>` : ''}</div><label for="relay-hop-node-${i}">服务器</label><select id="relay-hop-node-${i}" data-hop="${i}" data-field="node_id">${relayServers.map(n => option(n.id, n.name, h.node_id)).join('')}</select><div class="relay-hop-row"><div><label for="relay-hop-backend-${i}">转发方式</label><select id="relay-hop-backend-${i}" data-hop="${i}" data-field="backend">${option('realm', 'Realm', h.backend)}${option('nftables', 'nftables', h.backend)}</select></div><div><label for="relay-hop-port-${i}">入口端口</label><input id="relay-hop-port-${i}" data-hop="${i}" data-field="listen_port" type="number" min="1" max="65535" value="${esc(h.listen_port)}" required></div></div></div>`).join('<div class="relay-hop-arrow" aria-hidden="true">↓</div>');
        document.querySelectorAll('#relay-hops select').forEach(enhanceSelect);
        $('#relay-add-hop').disabled = hops.length >= 5;
    };
    // 同一条线路里服务器不能重复：下拉不互斥（只有两台服务器时也能自由选择），提交时提示
    const relayDuplicate = () => {
        const ids = [...hops.map(h => h.node_id), $('#relay-landing-node').value];
        return new Set(ids).size !== ids.length;
    };
    const followPort = () => { hops.forEach(h => { h.listen_port = landingPort(); }); renderHops(); };
    const renderProtocol = () => {
        const only = portOnly();
        $('#relay-port-only-fields').hidden = !only;
        $('#relay-landing-port').required = only;
        followPort();
    };
    const renderLanding = () => {
        const node = nodeById($('#relay-landing-node').value), previous = $('#relay-landing-protocol').value;
        const items = relayLandingOptions(node, user());
        const keep = items.find(o => o.value === previous && !o.disabled) || items.find(o => !o.disabled);
        $('#relay-landing-protocol').innerHTML = items.map(o => option(o.value, o.label, keep.value, o.disabled)).join('');
        $('#relay-landing-protocol').value = keep.value;
        $('#relay-landing-host').value = node?.snapshot.addresses?.ipv4 || node?.snapshot.addresses?.ipv6 || '';
        $('#relay-landing-help').textContent = $('#relay-landing-host').value ? '默认为该服务器上报的公网 IP，可改为内网地址或域名。' : '该服务器未上报公网 IP（节点程序需升级），请手动填写。';
        renderProtocol();
    };
    renderLanding();
    $('#relay-hops').addEventListener('change', e => {
        const i = Number(e.target.dataset.hop), field = e.target.dataset.field;
        if (!field) return;
        hops[i][field] = field === 'listen_port' ? Number(e.target.value) : e.target.value;
        if (field === 'node_id') renderHops();
    });
    $('#relay-hops').addEventListener('click', e => {
        const i = e.target.closest('[data-hop-remove]')?.dataset.hopRemove;
        if (i == null) return;
        hops.splice(Number(i), 1);
        renderHops();
    });
    $('#relay-add-hop').onclick = () => {
        const free = relayServers.find(n => !hops.some(h => h.node_id === n.id) && n.id !== $('#relay-landing-node').value) || relayServers[0];
        hops.push({node_id: free.id, backend: 'realm', listen_port: landingPort()});
        renderHops();
    };
    $('#relay-landing-node').addEventListener('change', renderLanding);
    $('#relay-user').addEventListener('change', renderLanding);
    $('#relay-landing-protocol').addEventListener('change', renderProtocol);
    $('#relay-landing-port').addEventListener('input', followPort);
    $('#relay-form').onsubmit = async e => {
        e.preventDefault();
        const button = $('[type=submit]', e.target);
        button.disabled = true;
        const host = $('#relay-landing-host').value.trim(), nodeId = $('#relay-landing-node').value;
        try {
            if (relayDuplicate()) throw new Error('同一条线路中服务器不能重复，中转服务器也不能是落地服务器，请重新选择');
            let landing;
            if (portOnly()) landing = {node_id: nodeId, port: Number($('#relay-landing-port').value), host, transport: $('#relay-landing-transport').value};
            else {
                const [core, protocol, port] = ($('#relay-landing-protocol').value || '::').split(':');
                if (!protocol) throw new Error('请选择落地协议');
                if (!user()) throw new Error('落地协议需要选择用户；只转发端口请选择「仅转发端口」');
                landing = {node_id: nodeId, core, protocol, port: Number(port), host};
            }
            await post('/relays', {user_id: user()?.id || null, hops: hops.map(h => ({node_id: h.node_id, backend: h.backend, listen_port: Number(h.listen_port)})), landing});
            $('#modal').close();
            toast('线路已提交，正在各中转服务器建立转发');
            await relaysPage();
        } catch (err) { formError(err); button.disabled = false; }
    };
}
// The relay table appears on its own page and on the overview.
async function relaysView() {
    if (location.hash.replace('#', '') === 'relays') return relaysPage();
    await loadOverviewRelays();
}
async function loadOverviewRelays() {
    const data = await api('/relays');
    relayData = data.relays;
    const box = $('#overview-relays');
    if (box) {
        box.innerHTML = relayTable(relayData);
        $('#overview-relay-count').textContent = relayData.length;
    }
}
async function relayAction(action, b) {
    if (action === 'rl-add') return relayDialog();
    const line = relayData.find(l => l.id === b.dataset.id);
    if (!line) throw new Error('中转线路不存在，请刷新后重试');
    if (action === 'rl-share') {
        const r = await post('/relays/' + line.id + '/share');
        activeTaskId = r.id;
        await refresh();
        showTask(r.id);
    } else if (action === 'rl-retry') {
        await post('/relays/' + line.id + '/retry');
        toast('已重新提交失败的中转服务器');
        await relaysView();
    } else if (action === 'rl-delete') {
        choiceDialog('删除中转线路', `删除 ${esc(line.user_name)} 经 ${line.hops.map(h => esc(h.node_name)).join(' → ')} 到 ${esc(line.landing.node_name)} 的线路，并删除各中转服务器上的转发规则。用户在落地协议上的账号保留。`, [], async () => {
            await post('/relays/' + line.id + '/delete');
            toast('正在删除各中转服务器上的转发规则');
            await relaysView();
        });
    }
}

// ---------------------------------------------------------------- 端口转发（所有服务器的 Realm / nftables 规则）
let forwardFilter = {node: '', backend: '', q: ''};
const forwardBackends = {realm: 'Realm', nftables: 'nftables'};
const forwardStates = {running: '运行中', stopped: '未运行', disabled: '已停用'};
function forwardRows() {
    return nodes.filter(n => !n.deleted).flatMap(n => (n.snapshot.forwards || []).map(r => ({node: n, r})));
}
function forwardMatches({node, r}, f) {
    const q = f.q.trim().toLowerCase();
    return (!f.node || node.id === f.node) && (!f.backend || r.backend === f.backend)
        && (!q || [r.remark, String(r.listen_port), r.remote_host, String(r.remote_port), node.name].some(v => String(v || '').toLowerCase().includes(q)));
}
function forwardWritable(node) {
    return node.adopted && node.status === 'online' && !node.maintenance && node.snapshot.forward_version === 1;
}
function forwardTable(rows) {
    if (!rows.length) return '<div class="empty"><p>没有符合条件的转发规则。</p></div>';
    return `<div class="table-wrap"><table><thead><tr><th>服务器</th><th>备注</th><th>类型</th><th>监听</th><th>目标</th><th>状态</th><th class="num">流量</th><th>操作</th></tr></thead><tbody>${rows.map(({node, r}) => {
        const off = !forwardWritable(node) ? ' disabled' : '', data = `data-node="${esc(node.id)}" data-id="${esc(r.id)}"`;
        return `<tr><td><a href="#nodes/${esc(node.id)}">${esc(node.name)}</a>${node.status !== 'online' ? `<br><span class="muted">${esc(states[node.status] || node.status)}</span>` : ''}</td><td>${r.remark ? esc(r.remark) : '<span class="muted">未命名</span>'}</td><td><strong>${esc(forwardBackends[r.backend] || r.backend)}</strong><br><span class="muted">${esc(r.transport.toUpperCase())}</span></td><td class="mono">${esc(r.listen_host === '0.0.0.0' ? '' : r.listen_host + ':')}${r.listen_port}</td><td class="mono">${esc(r.remote_host)}:${r.remote_port}</td><td><span class="badge ${r.status === 'running' ? 'running' : 'stopped'}">${esc(forwardStates[r.status] || r.status)}</span></td><td class="num">${r.bytes == null ? '—' : bytes(r.bytes)}</td><td><div class="action-row"><button class="small" data-action="fw-edit" ${data}${off}>修改</button><button class="small" data-action="fw-toggle" ${data}${off}>${r.enabled ? '停用' : '启用'}</button><button class="small" data-action="fw-delete" ${data}${off}>删除</button></div></td></tr>`;
    }).join('')}</tbody></table></div>`;
}
function forwardsPage() {
    const rows = forwardRows(), f = forwardFilter, servers = nodes.filter(n => !n.deleted);
    const outdated = servers.filter(n => n.adopted && n.snapshot.forward_version !== 1).length;
    shell(`<div class="heading"><div><h1>端口转发</h1></div><div class="action-row"><button data-action="refresh">${icon('refresh')}刷新</button><button class="primary" data-action="fw-add">${icon('plus')}新建转发</button></div></div>
    ${outdated ? `<div class="notice">${outdated} 台服务器的节点程序版本较旧，升级后才能查看和管理端口转发。</div>` : ''}
    <div class="section-label"><h2>规则 <span class="count" id="forward-count"></span></h2><div class="tools instance-filters">
    ${filterMenu('forward-node', '筛选服务器', [['', '全部服务器'], ...servers.map(n => [n.id, n.name])], f.node)}
    ${filterMenu('forward-backend', '筛选转发类型', [['', '全部类型'], ...Object.entries(forwardBackends)], f.backend)}
    <div class="search">${icon('search')}<input id="forward-search" type="search" aria-label="搜索转发规则" placeholder="搜索备注、端口或目标" value="${esc(f.q)}"></div></div></div>
    <div class="panel" id="forward-results"></div>
    <p class="helper">Realm 支持 TCP / UDP，目标可为域名；nftables 为内核转发，固定 TCP+UDP，目标须为 IPv4，并会开启服务器的 IPv4 转发。流量为节点上报的累计值，节点重启后清零。</p>`, 'forwards');
    const update = () => {
        const shown = rows.filter(row => forwardMatches(row, forwardFilter));
        $('#forward-results').innerHTML = forwardTable(shown);
        $('#forward-count').textContent = shown.length === rows.length ? String(rows.length) : shown.length + ' / ' + rows.length;
    };
    $('#forward-node').onchange = e => { forwardFilter.node = e.target.value; update(); };
    $('#forward-backend').onchange = e => { forwardFilter.backend = e.target.value; update(); };
    $('#forward-search').addEventListener('input', e => { forwardFilter.q = e.target.value; update(); });
    update();
}
function forwardDialog(nodeId, rule) {
    const editing = !!rule, servers = nodes.filter(n => !n.deleted && forwardWritable(n));
    if (!servers.length) return modal('暂无可配置的服务器', '<p>需要已接管、在线、未维护，且节点程序支持端口转发的服务器。请先升级节点程序。</p>');
    const node = nodes.find(n => n.id === nodeId) || servers.find(n => n.id === forwardFilter.node) || servers[0];
    const r = rule || {backend: 'realm', remark: '', transport: 'tcp', listen_host: '0.0.0.0', listen_port: '', remote_host: '', remote_port: '', enabled: true};
    const option = (v, label, current) => `<option value="${esc(v)}"${v === current ? ' selected' : ''}>${esc(label)}</option>`;
    modal(editing ? '修改转发 · ' + node.name : '新建转发', `<form id="fw-form"><div class="install-top">${editing ? '' : `<div class="inline-field"><label for="fw-node">服务器</label><select id="fw-node">${servers.map(n => option(n.id, n.name, node.id)).join('')}</select></div>`}<div class="inline-field"><label for="fw-backend">类型</label><select id="fw-backend">${option('realm', 'Realm', r.backend)}${option('nftables', 'nftables', r.backend)}</select></div></div>
<div class="install-grid">
<div><label for="fw-remark">备注</label><input id="fw-remark" maxlength="64" value="${esc(r.remark)}" placeholder="可选"></div>
<div><label for="fw-transport">协议</label><select id="fw-transport">${option('tcp', 'TCP', r.transport)}${option('udp', 'UDP', r.transport)}${option('tcp+udp', 'TCP + UDP', r.transport)}</select></div>
<div id="fw-listen-host-field"><label for="fw-listen-host">监听地址</label><input id="fw-listen-host" value="${esc(r.listen_host)}" required></div>
<div><label for="fw-listen-port">监听端口</label><div class="input-action"><input id="fw-listen-port" type="number" min="1" max="65535" value="${esc(r.listen_port)}" required><button type="button" id="fw-generate-port" class="install-generate">生成</button></div></div>
<div><label for="fw-remote-host" id="fw-remote-label">目标地址</label><input id="fw-remote-host" maxlength="253" value="${esc(r.remote_host)}" required></div>
<div><label for="fw-remote-port">目标端口</label><input id="fw-remote-port" type="number" min="1" max="65535" value="${esc(r.remote_port)}" required></div>
</div><label class="field-check"><input id="fw-enabled" type="checkbox"${r.enabled ? ' checked' : ''}>启用</label><p class="helper" id="fw-help"></p><div class="error" role="alert"></div><div class="modal-foot"><button type="button" data-action="close">取消</button><button type="submit" class="primary">${editing ? '保存修改' : '创建转发'}</button></div></form>`);
    const target = () => nodes.find(n => n.id === ($('#fw-node')?.value || node.id)) || node;
    const updateFields = () => {
        const nft = $('#fw-backend').value === 'nftables';
        if (nft) { $('#fw-transport').value = 'tcp+udp'; $('#fw-listen-host').value = '0.0.0.0'; }
        $('#fw-transport').disabled = nft;
        $('#fw-listen-host-field').hidden = nft;
        $('#fw-remote-label').textContent = nft ? '目标 IPv4' : '目标地址';
        $('#fw-remote-host').placeholder = nft ? '例如 203.0.113.10' : 'IP 或域名';
        $('#fw-help').textContent = nft ? 'nftables 为内核转发：固定 TCP+UDP、监听所有地址，目标须为 IPv4；保存后会开启服务器的 IPv4 转发。' : 'Realm 支持 TCP / UDP，目标可为域名或 IP。';
    };
    $('#fw-backend').addEventListener('change', updateFields);
    updateFields();
    $('#fw-generate-port').onclick = () => {
        const used = [...(target().snapshot.instances || []), ...(target().snapshot.forwards || []).map(x => ({port: x.listen_port}))];
        try { $('#fw-listen-port').value = installPortCandidate(used, $('#fw-listen-port').value); } catch (err) { formError(err); }
    };
    if (!editing && !r.listen_port) $('#fw-generate-port').onclick();
    $('#fw-form').onsubmit = async e => {
        e.preventDefault();
        const button = $('[type=submit]', e.target);
        button.disabled = true;
        const data = {rule: {backend: $('#fw-backend').value, remark: $('#fw-remark').value.trim(), transport: $('#fw-transport').value,
            listen_host: $('#fw-listen-host').value.trim(), listen_port: Number($('#fw-listen-port').value), remote_host: $('#fw-remote-host').value.trim(),
            remote_port: Number($('#fw-remote-port').value), enabled: $('#fw-enabled').checked}};
        try {
            const result = await post('/nodes/' + target().id + '/forwards', editing ? {op: 'update', id: rule.id, ...data} : {op: 'add', ...data});
            activeTaskId = result.id;
            await refresh();
            showTask(result.id);
        } catch (err) { formError(err); button.disabled = false; }
    };
}
async function forwardAction(action, b) {
    const node = nodes.find(n => n.id === b.dataset.node), rule = node?.snapshot.forwards?.find(r => r.id === b.dataset.id);
    if (action === 'fw-add') return forwardDialog(forwardFilter.node, null);
    if (!rule) throw new Error('转发规则不存在，请刷新后重试');
    if (action === 'fw-edit') return forwardDialog(node.id, rule);
    const submit = async op => { const r = await post('/nodes/' + node.id + '/forwards', {op, id: rule.id}); activeTaskId = r.id; await refresh(); showTask(r.id); };
    if (action === 'fw-toggle') {
        b.disabled = true;
        try { await submit(rule.enabled ? 'disable' : 'enable'); } finally { b.disabled = false; }
    } else if (action === 'fw-delete') {
        choiceDialog('删除转发规则', `删除 ${esc(node.name)} 上监听 ${rule.listen_port} 的${esc(forwardBackends[rule.backend])}转发，到 ${esc(rule.remote_host)}:${rule.remote_port} 的流量将中断。`, [], () => submit('delete'));
    }
}

// ---------------------------------------------------------------- 节点管理（所有服务器的协议实例）
// 筛选菜单：紧凑按钮 + 弹出菜单面板，替代原生下拉框。选择后更新按钮并调用容器的 onchange({target: {value}})。
const filterChevron = '<svg class="filter-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg>';
const filterCheck = '<svg class="filter-check" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>';
function filterMenu(id, label, options, value, kind = '') {
    const current = options.find(([v]) => v === value) || options[0];
    return `<div class="filter-menu${kind ? ' ' + kind : ''}${current[0] && !kind ? ' active' : ''}"${id ? ` id="${esc(id)}"` : ''} data-value="${esc(current[0])}">`
        + `<button type="button" class="filter-trigger" aria-haspopup="menu" aria-expanded="false" title="${esc(label)}"><span class="filter-text">${esc(current[1])}</span>${filterChevron}</button>`
        + `<div class="filter-pop" role="menu" aria-label="${esc(label)}" hidden>${options.map(([v, text, disabled]) =>
            `<button type="button" role="menuitemradio" class="filter-option" data-value="${esc(v)}" aria-checked="${v === current[0]}"${disabled ? ' disabled' : ''}><span>${esc(text)}</span>${filterCheck}</button>`).join('')}</div></div>`;
}
function filterMenuOpen(menu, open) {
    menu.classList.toggle('open', open);
    menu.querySelector('.filter-pop').hidden = !open;
    menu.querySelector('.filter-trigger').setAttribute('aria-expanded', String(open));
    if (!open) return;
    const pop = menu.querySelector('.filter-pop');
    menu.classList.remove('align-end');
    if (menu.classList.contains('select-menu')) {
        selectMenuPlace(menu, pop);
        menu.dataset.opened = String(Date.now());
    } else if (pop.getBoundingClientRect?.().right > (window.innerWidth || Infinity) - 8) menu.classList.add('align-end');
    (pop.querySelector('[aria-checked="true"]:not(:disabled)') || pop.querySelector('.filter-option:not(:disabled)'))?.focus?.({preventScroll: true});
}
function closeFilterMenus(except) {
    document.querySelectorAll('.filter-menu.open').forEach(m => m !== except && filterMenuOpen(m, false));
}
function filterMenuPick(menu, option) {
    const value = option.dataset.value;
    menu.dataset.value = value;
    menu.classList.toggle('active', value !== '' && !menu.classList.contains('select-menu'));
    menu.querySelector('.filter-text').textContent = option.textContent;
    menu.querySelectorAll('.filter-option').forEach(o => o.setAttribute('aria-checked', String(o === option)));
    filterMenuOpen(menu, false);
    menu.querySelector('.filter-trigger').focus?.();
    menu.onchange?.({target: {value}});
}
function filterMenuClick(e) {
    const menu = e.target.closest?.('.filter-menu');
    closeFilterMenus(menu);
    if (!menu) return;
    const option = e.target.closest('.filter-option');
    if (option) filterMenuPick(menu, option);
    else if (e.target.closest('.filter-trigger')) filterMenuOpen(menu, !menu.classList.contains('open'));
}
function filterMenuKey(e) {
    const menu = e.target.closest?.('.filter-menu');
    if (!menu) return;
    const open = menu.classList.contains('open');
    if (e.key === 'Escape' && open) {
        e.preventDefault();
        filterMenuOpen(menu, false);
        menu.querySelector('.filter-trigger').focus?.();
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (!open) return filterMenuOpen(menu, true);
        const items = [...menu.querySelectorAll('.filter-option:not(:disabled)')], at = items.indexOf(e.target);
        items[(at + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus?.();
    } else if (e.key === 'Tab' && open) filterMenuOpen(menu, false);
}
document.addEventListener('click', filterMenuClick);
document.addEventListener('keydown', filterMenuKey);

// 弹窗里的下拉框：原生 select 保留为数据源（取值、change 事件、表单校验），隐藏在同样的按钮 + 弹出菜单下面。
// 弹窗内容区会滚动，菜单用 fixed 定位以免被裁切；滚动或改变窗口大小时关闭。
function selectMenuOptions(select) {
    const options = [...select.options].map(o => [o.value, o.textContent, o.disabled]);
    return options.length ? options : [['', '—', true]];
}
function selectMenuPlace(menu, pop) {
    const rect = menu.querySelector('.filter-trigger').getBoundingClientRect(), gap = 6, edge = 8;
    const below = window.innerHeight - rect.bottom - gap - edge, above = rect.top - gap - edge;
    Object.assign(pop.style, {left: rect.left + 'px', minWidth: rect.width + 'px', maxHeight: '', top: rect.bottom + gap + 'px'});
    const height = pop.offsetHeight;
    if (height > below && above > below) {
        pop.style.maxHeight = Math.min(300, above) + 'px';
        pop.style.top = rect.top - gap - pop.offsetHeight + 'px';
    } else pop.style.maxHeight = Math.min(300, below) + 'px';
    const right = pop.getBoundingClientRect().right;
    if (right > window.innerWidth - edge) pop.style.left = Math.max(edge, rect.left - (right - window.innerWidth + edge)) + 'px';
}
function enhanceSelect(select) {
    if (select.dataset.menu) return;
    select.dataset.menu = '1';
    const field = document.createElement('div');
    field.className = 'select-field';
    select.before(field);
    field.append(select);
    select.classList.add('select-native');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    const label = select.id ? document.querySelector('label[for="' + select.id + '"]') : null;
    let signature = '';
    const render = () => {
        const options = selectMenuOptions(select);
        signature = JSON.stringify(options);
        field.querySelector('.filter-menu')?.remove();
        field.insertAdjacentHTML('afterbegin', filterMenu('', label?.textContent || '选择', options, select.value, 'select-menu'));
        const menu = field.querySelector('.filter-menu'), trigger = menu.querySelector('.filter-trigger');
        if (select.id) {
            trigger.id = select.id + '-menu';
            if (label) label.htmlFor = trigger.id;
        }
        trigger.disabled = select.disabled;
        menu.onchange = e => {
            select.value = e.target.value;
            select.dispatchEvent(new Event('change', {bubbles: true}));
        };
    };
    const sync = () => {
        if (JSON.stringify(selectMenuOptions(select)) !== signature) return render();
        const menu = field.querySelector('.filter-menu'), value = select.value;
        const option = [...menu.querySelectorAll('.filter-option')].find(o => o.dataset.value === value);
        menu.dataset.value = value;
        menu.querySelector('.filter-text').textContent = option ? option.textContent : '—';
        menu.querySelectorAll('.filter-option').forEach(o => o.setAttribute('aria-checked', String(o === option)));
        menu.querySelector('.filter-trigger').disabled = select.disabled;
    };
    // Code sets select.value directly (no change event): mirror it.
    const property = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
    Object.defineProperty(select, 'value', {configurable: true, get() { return property.get.call(this); }, set(v) { property.set.call(this, v); sync(); }});
    select.addEventListener('change', sync);
    new MutationObserver(sync).observe(select, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['disabled']});
    render();
}
function closeSelectMenus(e) {
    if (e?.target?.closest?.('.filter-pop')) return;
    // A scroll that brings the trigger into view arrives a frame after opening: keep the menu.
    document.querySelectorAll('.select-menu.open').forEach(m => (!e || Date.now() - Number(m.dataset.opened) > 200) && filterMenuOpen(m, false));
}
document.addEventListener('scroll', closeSelectMenus, true);
window.addEventListener('resize', () => closeSelectMenus());

let instanceFilter = {node: '', protocol: '', status: '', mode: '', q: ''};
const instanceModes = {multi: '多用户', single: '一用户一实例', none: '不支持用户管理'};
function instanceRows() {
    return nodes.filter(n => !n.deleted).flatMap(n => (n.snapshot.instances || []).map((p, index) => ({node: n, p, index})));
}
function instanceMatches(row, f) {
    const {node, p} = row, q = f.q.trim().toLowerCase();
    return (!f.node || node.id === f.node) && (!f.protocol || p.protocol === f.protocol) && (!f.status || p.status === f.status)
        && (!f.mode || (p.user_mode || '') === f.mode)
        && (!q || [node.name, node.group_name, names[p.protocol] || p.protocol, p.protocol, String(p.port)].some(v => String(v || '').toLowerCase().includes(q)));
}
function instanceTable(rows) {
    if (!rows.length) return '<div class="empty"><p>没有符合条件的节点。</p></div>';
    return `<div class="table-wrap"><table><thead><tr><th>服务器</th><th>协议 / 内核</th><th class="num">端口</th><th>服务状态</th><th class="num">用户</th><th>用户模式</th><th class="num">用量合计</th><th>管理</th></tr></thead><tbody>${rows.map(({node, p, index}) => {
        const used = (p.users || []).reduce((sum, u) => sum + (Number.isFinite(u.used) && u.used >= 0 ? u.used : 0), 0);
        return `<tr><td><a href="#nodes/${esc(node.id)}">${esc(node.name)}</a>${node.status !== 'online' ? `<br><span class="muted">${esc(states[node.status] || node.status)}</span>` : ''}</td><td><strong>${esc(names[p.protocol] || p.protocol)}</strong><br><span class="muted">${esc(p.protocol.startsWith('snell') || ['snell-shadowtls', 'snell-v5-shadowtls', 'ss2022-shadowtls', 'naive'].includes(p.protocol) ? '独立进程' : p.core === 'singbox' ? 'Sing-box' : 'Xray')}</span></td><td class="num mono">${p.port}</td><td>${badge(p.status)}</td><td class="num">${(p.users || []).length}</td><td>${p.user_mode ? esc(userModeText(p)) : '<span class="muted">—</span>'}</td><td class="num">${p.traffic_state === 'unsupported' ? '—' : bytes(used)}</td><td><button class="small" data-action="node-instance" data-node="${esc(node.id)}" data-index="${index}">${p.managed ? '管理实例' : '查看实例'}</button></td></tr>`;
    }).join('')}</tbody></table></div>`;
}
function instancesPage() {
    const rows = instanceRows(), f = instanceFilter;
    const servers = nodes.filter(n => !n.deleted);
    const protocols = [...new Set(rows.map(r => r.p.protocol))].sort();
    shell(`<div class="heading"><div><h1>节点管理</h1></div><div class="action-row"><button data-action="refresh">${icon('refresh')}刷新</button><button class="primary" data-action="instance-create">${icon('plus')}新建协议</button></div></div>
    <div class="section-label"><h2>节点 <span class="count" id="instance-count"></span></h2><div class="tools instance-filters">
    ${filterMenu('instance-node', '筛选服务器', [['', '全部服务器'], ...servers.map(n => [n.id, n.name])], f.node)}
    ${filterMenu('instance-protocol', '筛选协议', [['', '全部协议'], ...protocols.map(p => [p, names[p] || p])], f.protocol)}
    ${filterMenu('instance-status', '筛选服务状态', [['', '全部状态'], ['running', '运行中'], ['stopped', '已停止'], ['unknown', '未知']], f.status)}
    ${filterMenu('instance-mode', '筛选用户模式', [['', '全部用户模式'], ...Object.entries(instanceModes)], f.mode)}
    <div class="search">${icon('search')}<input id="instance-search" type="search" aria-label="搜索节点" placeholder="搜索服务器、协议或端口" value="${esc(f.q)}"></div></div></div>
    <div class="panel" id="instance-results"></div>
    <p class="helper">节点即服务器上的一个协议实例（协议 + 端口）。共享核心的协议启停或修改会影响同一服务器上的其他实例；离线服务器显示最后一次快照。</p>`, 'instances');
    const update = () => {
        const shown = rows.filter(r => instanceMatches(r, instanceFilter));
        $('#instance-results').innerHTML = instanceTable(shown);
        $('#instance-count').textContent = shown.length === rows.length ? String(rows.length) : shown.length + ' / ' + rows.length;
    };
    for (const [id, key] of [['instance-node', 'node'], ['instance-protocol', 'protocol'], ['instance-status', 'status'], ['instance-mode', 'mode']])
        $('#' + id).onchange = e => { instanceFilter[key] = e.target.value; update(); };
    $('#instance-search').addEventListener('input', e => { instanceFilter.q = e.target.value; update(); });
    update();
}
