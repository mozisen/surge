// 用户管理界面：在 node:vm 中运行 app.js 的用户管理段落，检查渲染、转义与提交参数。
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync(__dirname + '/../web/app.js', 'utf8');
const code = source.slice(source.indexOf('// ---------------------------------------------------------------- 用户管理（平台用户）'));

const html = {shell: '', modal: '', title: ''};
const elements = {};
const element = (id, extra = {}) => (elements[id] = {id, value: '', checked: false, hidden: false, disabled: false, innerHTML: '', textContent: '', ...extra});
const posts = [];
const context = {
    esc: v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])),
    bytes: n => n == null ? '—' : (n / 1073741824).toFixed(1) + ' GiB',
    date: n => n ? 'T' + n : '—',
    badge: s => `<badge>${s}</badge>`, states: {online: '在线', offline: '离线'},
    names: {vless: 'VLESS Reality', hy2: 'Hysteria2', ss2022: 'SS2022', 'snell-v5': 'Snell v5'},
    icon: () => '<svg></svg>',
    meter: (label, percent) => `<meter>${percent == null ? '—' : percent.toFixed(0)}</meter>`,
    stat: (title, value, foot) => `<stat>${title}:${value}:${foot}</stat>`,
    shell: (content, section) => { html.shell = content; html.section = section; },
    modal: (title, body) => { html.title = title; html.modal = body; },
    toast: () => {}, formError: e => { throw e; },
    location: {hash: ''},
    nodes: [], selected: null,
    submitTask: async () => {},
    $: selector => elements[selector.replace(/^#/, '')] || elements[selector],
    document: {querySelectorAll: selector => (context.openMenus && selector === '.filter-menu.open' ? context.openMenus() : Object.values(elements).filter(e => e.matches && e.matches(selector))),
               addEventListener: (type, fn) => { context.listeners[type] = fn; }},
    listeners: {}, window: {innerWidth: 1280, addEventListener() {}},
    console,
};
context.api = async path => context.responses[path];
context.post = async (path, data) => { posts.push([path, data]); return {id: 'new-user', deleted: true}; };
vm.createContext(context);
vm.runInContext(code + '\nthis.usersPage=usersPage;this.userDetail=userDetail;this.userForm=userForm;this.membersDialog=membersDialog;this.linkDialog=linkDialog;this.authorityBlock=authorityBlock;this.authorityNotice=authorityNotice;this.authorityDialog=authorityDialog;this.upgradeDialog=upgradeDialog;this.userModeText=userModeText;this.memberAddable=memberAddable;this.installUserPicker=installUserPicker;this.installPickedUsers=installPickedUsers;this.installPlaceUsers=installPlaceUsers;this.instancesPage=instancesPage;this.instanceRows=instanceRows;this.instanceMatches=instanceMatches;this.instanceTable=instanceTable;this.filterMenu=filterMenu;this.forwardsPage=forwardsPage;this.relaysPage=relaysPage;this.relayMatches=relayMatches;this.relayTable=relayTable;this.relayAction=relayAction;this.relayDialog=relayDialog;this.relayLandingOptions=relayLandingOptions;this.forwardRows=forwardRows;this.forwardMatches=forwardMatches;this.forwardTable=forwardTable;this.forwardDialog=forwardDialog;this.forwardAction=forwardAction;this.selectMenuOptions=selectMenuOptions;this.monitorPage=monitorPage;this.notificationSettings=notificationSettings;this.notifyAction=notifyAction;this.userAction=userAction;', context);

const node = (id, extra = {}) => ({id, name: 'node-' + id, adopted: true, status: 'online', maintenance: false, deleted: null,
    snapshot: {accounts_version: 1, authority_version: 1, user_authority: 'platform', upgrade_version: 1, agent_version: '0.3.0-preview.11', instances: [
        {core: 'xray', protocol: 'vless', port: 443, managed: true, users: [{name: 'old', account_id: ''}, {name: 'alice', account_id: 'acc'}]},
        {core: 'singbox', protocol: 'ss2022', port: 9000, managed: true, users: [{name: 'solo', account_id: ''}]}]}, ...extra});
const user = {id: 'u1', name: 'alice', note: '<b>vip</b>', enabled: true, expire_date: '2099-01-01', quota: 10 * 1073741824, reset_day: 1,
    cycle: '2026-10-01', used: 4 * 1073741824, state: '', deleting: null,
    links: [{id: 'l1', node_id: 'a', node_name: 'node-a', account_id: 'acc', cycle_used: 4 * 1073741824, sync: 'synced', notice: '', online: true,
             account: {}, members: [{core: 'xray', protocol: 'vless', port: 443, name: 'alice', enabled: true}]},
            {id: 'l2', node_id: 'b', node_name: 'node-b', account_id: 'acc2', cycle_used: 0, sync: 'offline', notice: '同步失败：x', online: false, account: null, members: []}]};

(async () => {
    context.nodes = [node('a'), node('b', {status: 'offline'}), node('c', {snapshot: {accounts_version: 0, instances: []}}),
                     node('d', {snapshot: {accounts_version: 1, authority_version: 1, user_authority: 'script', instances: []}})];
    context.responses = {'/users': {users: [user, {...user, id: 'u2', name: '<script>', note: '', quota: 0, used: 0, state: 'quota', links: []}]},
        '/users/u1': {user}};
    await context.usersPage();
    assert.strictEqual(html.section, 'users');
    assert(html.shell.includes('href="#users/u1"') && html.shell.includes('&lt;b&gt;vip&lt;/b&gt;') && !html.shell.includes('<b>vip'));
    assert(html.shell.includes('&lt;script&gt;') && !html.shell.includes('<script>'));
    assert(html.shell.includes('<meter>40</meter>') && html.shell.includes('<meter>—</meter>'));
    assert(html.shell.includes('流量已用尽') && html.shell.includes('未关联节点'));
    assert(!html.shell.includes('未关联的统一用户') && html.shell.includes('以平台为准'));
    assert(html.shell.includes('1/2'), 'partial sync count');
    console.log('PASS users list: states, usage meter, escaping, authority hint');

    await context.userDetail('u1');
    assert(html.shell.includes('返回用户管理') && html.shell.includes('已同步') && html.shell.includes('节点离线'));
    assert(html.shell.includes('同步失败：x'));
    assert(/data-action="pu-members" data-link="l1" >/.test(html.shell) && /data-action="pu-members" data-link="l2" disabled/.test(html.shell));
    assert(html.shell.includes('data-action="pu-share" data-link="l1"') && html.shell.includes('等待节点创建'));
    console.log('PASS user detail: links, sync states, notices, offline actions disabled, per-member connection info');

    // 编辑：未改的配额不提交，启停与其他字段提交
    element('pu-name', {value: 'alice'}); element('pu-quota', {value: '10'}); element('pu-reset', {value: '5'});
    element('pu-expire', {value: '2099-02-01'}); element('pu-note', {value: 'n'}); element('pu-enabled', {checked: false});
    element('pu-form'); element('[type=submit]'); element('modal', {close() {}});
    context.userForm(user);
    assert(html.title === '编辑用户' && html.modal.includes('pu-enabled'));
    await elements['pu-form'].onsubmit({preventDefault() {}, target: {}});
    assert.deepStrictEqual(JSON.parse(JSON.stringify(posts.pop())), ['/users/u1', {name: 'alice', reset_day: 5, expire_date: '2099-02-01', note: 'n', enabled: false}]);
    elements['pu-quota'].value = '20';
    await elements['pu-form'].onsubmit({preventDefault() {}, target: {}});
    assert.strictEqual(posts.pop()[1].quota_gb, 20);
    context.userForm(null);
    assert(html.title === '新建用户' && !html.modal.includes('pu-enabled'));
    delete elements['pu-enabled'];
    await elements['pu-form'].onsubmit({preventDefault() {}, target: {}});
    assert.deepStrictEqual(JSON.parse(JSON.stringify(posts.pop())), ['/users', {name: 'alice', quota_gb: 20, reset_day: 5, expire_date: '2099-02-01', note: 'n'}]);
    assert.strictEqual(context.location.hash, 'users/new-user');
    console.log('PASS user form payloads: create, edit, unchanged quota omitted');

    // 协议对话框：新建只列多用户协议，归入只列未归属用户
    context.currentUser = user;
    vm.runInContext('currentUser = this.currentUser;', context);
    element('pu-member-action', {value: 'add'}); element('pu-member-target'); element('pu-remove-set'); element('pu-member-help'); element('pu-member-form');
    context.membersDialog('l1');
    assert(elements['pu-member-target'].innerHTML.includes('VLESS') && !elements['pu-member-target'].innerHTML.includes('SS2022'));
    elements['pu-member-action'].value = 'claim'; elements['pu-member-action'].onchange();
    const claim = elements['pu-member-target'].innerHTML;
    assert(claim.includes('old') && claim.includes('solo') && !claim.includes('alice'));
    elements['pu-member-action'].value = 'remove'; elements['pu-member-action'].onchange();
    assert(!elements['pu-remove-set'].hidden && elements['pu-member-target'].innerHTML.includes('alice'));
    console.log('PASS member dialog: add lists multi-user protocols, claim lists unowned users, remove lists members');

    // 关联对话框：已关联、离线、旧版和脚本管理的节点不可选
    element('pu-node', {value: ''}); element('pu-instances'); element('pu-link-form');
    context.linkDialog();
    assert(/value="a" disabled/.test(html.modal) && /value="b" disabled/.test(html.modal) && /value="c" disabled/.test(html.modal) && /value="d" disabled/.test(html.modal));
    assert(html.modal.includes('需升级节点程序') && html.modal.includes('由节点脚本管理') && !html.modal.includes('认领'));
    console.log('PASS link dialog: linked, offline, outdated and script-managed nodes are not selectable');

    // 用户管理方式与一键升级
    const block = context.authorityBlock(node('d', {snapshot: {authority_version: 1, user_authority: 'script', instances: [], last_upgrade: {status: 'rolled_back', at: 1, to: '0.3.0-preview.12', message: '新版未按时上线'}}}));
    assert(block.includes('上次升级') && block.includes('已回滚') && block.includes('新版未按时上线'));
    assert(!block.includes('用户管理') && !block.includes('管理方式') && !block.includes('data-action="authority"'), 'no user-management block on the detail page');
    assert.strictEqual(context.authorityBlock(node('c', {snapshot: {instances: []}})), '');
    // Notice: platform or old nodes show nothing; empty script nodes are switching; script users need confirmation.
    assert.strictEqual(context.authorityNotice(node('e', {snapshot: {authority_version: 1, user_authority: 'platform', instances: [{users: [{}]}]}})), '');
    assert.strictEqual(context.authorityNotice(node('c', {snapshot: {instances: [{users: [{}]}]}})), '');
    assert.strictEqual(context.authorityNotice(node('f', {adopted: false, snapshot: {authority_version: 1, user_authority: 'script', instances: [{users: [{}]}]}})), '');
    assert(context.authorityNotice(node('g', {snapshot: {authority_version: 1, user_authority: 'script', instances: []}})).includes('正在把该服务器切换为平台统一管理'));
    context.tasks = [{node_id: 'g', action: 'platform_apply', created: 2, status: 'failed', message: '节点数据库格式无效<x>', request: {params: {ops: [{op: 'set_authority', mode: 'platform'}]}}},
                     {node_id: 'g', action: 'platform_apply', created: 1, status: 'succeeded', message: '', request: {params: {ops: [{op: 'set_authority', mode: 'platform'}]}}}];
    vm.runInContext('tasks = this.tasks;', context);
    const failedNotice = context.authorityNotice(node('g', {snapshot: {authority_version: 1, user_authority: 'script', instances: []}}));
    assert(failedNotice.includes('切换为平台管理失败：节点数据库格式无效&lt;x&gt;') && failedNotice.includes('重试切换') && !failedNotice.includes('正在把'));
    vm.runInContext('tasks = [];', context);
    const withUsers = context.authorityNotice(node('h', {snapshot: {authority_version: 1, user_authority: 'script', instances: [{users: [{}, {}]}]}}));
    assert(withUsers.includes('仍有 2 个脚本用户') && withUsers.includes('data-action="authority" >清空并切到平台管理'));
    assert(context.authorityNotice(node('i', {status: 'offline', snapshot: {authority_version: 1, user_authority: 'script', instances: [{users: [{}]}]}})).includes('disabled'));
    element('authority-form'); element('authority-confirm', {value: 'node-a'});
    context.authorityDialog(context.nodes[0]);
    assert(html.title === '切回脚本管理' && !html.modal.includes('authority-confirm'));
    const toPlatform = node('d', {snapshot: {authority_version: 1, user_authority: 'script', instances: [{users: [{}, {}]}, {users: [{}]}]}});
    context.authorityDialog(toPlatform);
    assert(html.title === '切换为平台管理' && html.modal.includes('全部 3 个用户') && html.modal.includes('输入节点名称'));
    vm.runInContext('activeTaskId = null; refresh = async () => {}; showTask = () => {};', context);
    await elements['authority-form'].onsubmit({preventDefault() {}, target: {}});
    assert.deepStrictEqual(JSON.parse(JSON.stringify(posts.pop())), ['/nodes/d/authority', {mode: 'platform', confirm: 'node-a'}]);
    element('confirm-upgrade');
    context.upgradeDialog({...context.nodes[0], panel_version: '0.3.0-preview.12'});
    assert(html.modal.includes('0.3.0-preview.11') && html.modal.includes('0.3.0-preview.12') && html.modal.includes('自动恢复'));
    await elements['confirm-upgrade'].onclick({target: {}});
    assert.deepStrictEqual(JSON.parse(JSON.stringify(posts.pop())), ['/nodes/a/upgrade', {}]);
    console.log('PASS authority block, takeover confirmation payload and one-click upgrade');

    // 协议用户模式与安装时选择用户
    const inst = (mode, extra = {}) => ({core: 'xray', protocol: 'p', port: 1, user_mode: mode, user_available: true, users: [], ...extra});
    assert.strictEqual(context.userModeText(inst('multi')), '多用户');
    assert.strictEqual(context.userModeText(inst('single', {user_stats: 'inbound'})), '一用户一实例，按入站统计，空实例');
    assert.strictEqual(context.userModeText(inst('single', {user_stats: 'port', users: [{}]})), '一用户一实例，按端口统计，已有用户');
    assert.strictEqual(context.userModeText(inst('none')), '不支持用户管理');
    assert.strictEqual(context.userModeText(inst('single', {user_available: false})), '暂未接入用户管理');
    assert(context.memberAddable(inst('multi', {users: [{}]})) && context.memberAddable(inst('single')));
    assert(!context.memberAddable(inst('single', {users: [{}]})) && !context.memberAddable(inst('none')) && !context.memberAddable(inst('multi', {user_available: false})));
    assert(!context.memberAddable({protocol: 'ss2022', managed: true}) && context.memberAddable({protocol: 'vless', managed: true}));
    const scroll = {html: '', insertAdjacentHTML(_, h) { this.html += h; }};
    elements['#install-form .install-scroll'] = scroll;
    delete elements['install-users'];
    context.responses['/users'] = {users: [{id: 'u1', name: '<b>a</b>', note: ''}, {id: 'u2', name: 'b', deleting: 'release'}]};
    vm.runInContext('selected = this.nodes[0];', context);
    await context.installUserPicker();
    assert(scroll.html.includes('value="u1"') && !scroll.html.includes('value="u2"') && scroll.html.includes('&lt;b&gt;a&lt;/b&gt;'));
    const picked = [{value: 'u1', matches: s => s === '#install-users input:checked'}];
    Object.assign(elements, {pick1: picked[0]});
    assert.deepStrictEqual(JSON.parse(JSON.stringify(context.installPickedUsers())), ['u1']);
    vm.runInContext("activeTaskId = 't9';", context);
    await context.installPlaceUsers(['u1']);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(posts.pop())), ['/nodes/a/install-users', {task_id: 't9', user_ids: ['u1']}]);
    vm.runInContext('selected = this.nodes[3];', context);
    scroll.html = '';
    await context.installUserPicker();
    assert.strictEqual(scroll.html, '');
    console.log('PASS user mode labels, member targets, install user picker and placement payload');

    // 节点管理：所有服务器的协议实例与筛选
    context.nodes = [
        {id: 'a', name: '香港', group_name: '亚太', status: 'online', deleted: null, snapshot: {instances: [
            {core: 'xray', protocol: 'vless', port: 443, status: 'running', managed: true, user_mode: 'multi', user_available: true, users: [{used: 1073741824}]},
            {core: 'xray', protocol: 'snell-v5', port: 9001, status: 'stopped', managed: true, user_mode: 'single', user_available: true, user_stats: 'port', users: []}]}},
        {id: 'b', name: '<i>东京</i>', group_name: '', status: 'offline', deleted: null, snapshot: {instances: [
            {core: 'singbox', protocol: 'hy2', port: 8443, status: 'running', managed: true, users: []}]}},
        {id: 'c', name: '已删除', status: 'offline', deleted: 1, snapshot: {instances: [{core: 'xray', protocol: 'vless', port: 1, users: []}]}}];
    vm.runInContext('nodes = this.nodes;', context);
    const rows = context.instanceRows();
    assert.strictEqual(rows.length, 3);
    const match = f => rows.filter(r => context.instanceMatches(r, {node: '', protocol: '', status: '', mode: '', q: '', ...f})).map(r => r.p.port);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(match({node: 'a'}))), [443, 9001]);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(match({protocol: 'hy2'}))), [8443]);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(match({status: 'stopped'}))), [9001]);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(match({mode: 'single'}))), [9001]);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(match({q: '东京'}))), [8443]);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(match({q: '9001'}))), [9001]);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(match({q: 'snell v5'}))), [9001]);
    const table = context.instanceTable(rows);
    assert(table.includes('data-action="node-instance" data-node="b" data-index="0"') && table.includes('&lt;i&gt;东京&lt;/i&gt;') && !table.includes('<i>东京'));
    assert(table.includes('1.0 GiB') && table.includes('离线') && table.includes('一用户一实例'));
    assert(context.instanceTable([]).includes('没有符合条件的节点'));
    for (const id of ['instance-node', 'instance-protocol', 'instance-status', 'instance-mode', 'instance-search', 'instance-results', 'instance-count'])
        element(id, {addEventListener(type, fn) { this.listener = fn; }});
    context.instancesPage();
    assert.strictEqual(html.section, 'instances');
    assert(html.shell.includes('节点管理') && html.shell.includes('全部服务器') && !html.shell.includes('已删除'));
    assert(!html.shell.includes('<select') && html.shell.includes('id="instance-mode"') && html.shell.includes('aria-haspopup="menu"'));
    assert(html.shell.includes('data-action="instance-create"') && html.shell.includes('新建协议'));
    assert.strictEqual(elements['instance-count'].textContent, '3');
    elements['instance-mode'].onchange({target: {value: 'multi'}});
    assert.strictEqual(elements['instance-count'].textContent, '1 / 3');
    elements['instance-search'].listener({target: {value: 'zzz'}});
    assert(elements['instance-results'].innerHTML.includes('没有符合条件的节点'));
    console.log('PASS instances page: all servers, filters, search, escaping, manage action');

    // 筛选菜单：渲染、打开、选择、Esc 与点击外部关闭
    const menuHtml = context.filterMenu('m', '筛选<分组>', [['', '全部分组'], ['a', '<b>亚太</b>'], ['b', '欧洲']], 'a');
    assert(menuHtml.includes('class="filter-menu active"') && menuHtml.includes('data-value="a"') && menuHtml.includes('aria-label="筛选&lt;分组&gt;"'));
    assert(menuHtml.includes('<span class="filter-text">&lt;b&gt;亚太&lt;/b&gt;</span>') && !menuHtml.includes('<b>亚太'));
    assert(menuHtml.includes('data-value="a" aria-checked="true"') && menuHtml.includes('data-value="" aria-checked="false"'));
    assert(context.filterMenu('m', 'x', [['', '全部'], ['a', 'A']], 'missing').includes('class="filter-menu" id="m" data-value=""'));
    const classes = () => { const set = new Set(); return {add: c => set.add(c), remove: c => set.delete(c), contains: c => set.has(c), toggle: (c, on) => (on ? set.add(c) : set.delete(c))}; };
    const attrs = () => ({attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, focus() { focused = this; }});
    let focused = null;
    const fakeMenu = () => {
        const menu = {classList: classes(), dataset: {value: ''}, changes: []};
        const trigger = {...attrs(), cls: 'filter-trigger', closest: s => s === '.filter-trigger' ? trigger : s === '.filter-menu' ? menu : null};
        const text = {textContent: '全部'};
        const pop = {hidden: true, getBoundingClientRect: () => ({right: 100}), querySelector: () => options[0]};
        const options = ['', 'x', 'y'].map(v => ({...attrs(), dataset: {value: v}, textContent: v || '全部',
            closest: s => s === '.filter-option' ? options.find(o => o.dataset.value === v) : s === '.filter-menu' ? menu : null}));
        menu.querySelector = s => ({'.filter-pop': pop, '.filter-trigger': trigger, '.filter-text': text})[s];
        menu.querySelectorAll = () => options;
        menu.onchange = e => menu.changes.push(e.target.value);
        return {menu, trigger, text, pop, options};
    };
    const one = fakeMenu(), two = fakeMenu();
    context.openMenus = () => [one, two].map(x => x.menu).filter(m => m.classList.contains('open'));
    context.listeners.click({target: one.trigger});
    assert(one.menu.classList.contains('open') && !one.pop.hidden && one.trigger.attrs['aria-expanded'] === 'true' && focused === one.options[0]);
    context.listeners.click({target: two.trigger});
    assert(!one.menu.classList.contains('open') && one.pop.hidden && two.menu.classList.contains('open'), 'opening another closes the first');
    context.listeners.click({target: two.options[2]});
    assert(!two.menu.classList.contains('open') && two.menu.dataset.value === 'y' && two.text.textContent === 'y' && two.menu.classList.contains('active'));
    assert(two.options[2].attrs['aria-checked'] === 'true' && two.options[0].attrs['aria-checked'] === 'false' && focused === two.trigger);
    assert.deepStrictEqual(two.menu.changes.slice(), ['y']);
    context.listeners.click({target: two.trigger});
    let prevented = false;
    context.listeners.keydown({key: 'Escape', target: two.options[0], preventDefault: () => { prevented = true; }});
    assert(prevented && !two.menu.classList.contains('open') && focused === two.trigger, 'Escape closes');
    context.listeners.keydown({key: 'ArrowDown', target: two.trigger, preventDefault() {}});
    assert(two.menu.classList.contains('open'), 'ArrowDown opens');
    context.listeners.keydown({key: 'ArrowDown', target: two.options[0], preventDefault() {}});
    assert(focused === two.options[1], 'ArrowDown moves focus');
    context.listeners.keydown({key: 'ArrowUp', target: two.options[0], preventDefault() {}});
    assert(focused === two.options[2], 'ArrowUp wraps');
    context.listeners.click({target: {closest: () => null}});
    assert(!two.menu.classList.contains('open') && two.menu.changes.length === 1, 'outside click closes without change');
    one.pop.getBoundingClientRect = () => ({right: 1300});
    context.listeners.click({target: one.trigger});
    assert(one.menu.classList.contains('align-end'), 'flips to the right edge when it overflows');
    // 弹窗下拉框复用同一组件：不加选中高亮，禁用项不可选、键盘跳过
    const formMenu = context.filterMenu('', '服务器', [['a', 'A'], ['b', 'B（不支持此协议）', true]], 'a', 'select-menu');
    assert(formMenu.startsWith('<div class="filter-menu select-menu" data-value="a">') && !formMenu.includes('active') && !formMenu.includes(' id='));
    assert(formMenu.includes('data-value="b" aria-checked="false" disabled'));
    const native = {options: [{value: 'x', textContent: 'X', disabled: false}, {value: 'y', textContent: '<Y>', disabled: true}]};
    assert.deepStrictEqual(JSON.parse(JSON.stringify(context.selectMenuOptions(native))), [['x', 'X', false], ['y', '<Y>', true]]);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(context.selectMenuOptions({options: []}))), [['', '—', true]]);
    const three = fakeMenu();
    three.menu.classList.add('select-menu');
    three.options[1].matches = () => true;
    three.menu.querySelectorAll = sel => sel.includes(':not(:disabled)') ? [three.options[0], three.options[2]] : three.options;
    context.selectMenuPlace = () => {};
    vm.runInContext('selectMenuPlace = this.selectMenuPlace;', context);
    context.openMenus = () => [three.menu].filter(m => m.classList.contains('open'));
    context.listeners.click({target: three.trigger});
    context.listeners.keydown({key: 'ArrowDown', target: three.options[0], preventDefault() {}});
    assert(focused === three.options[2], 'ArrowDown skips disabled options');
    context.listeners.click({target: three.options[2]});
    assert(!three.menu.classList.contains('active'), 'form selects never show the filter highlight');
    console.log('PASS filter menu: render, open, pick, keyboard, outside close');

    // 通知配置：状态、机器人、用户绑定表、绑定码与解绑
    const toasts = [];
    context.toast = m => toasts.push(m);
    context.responses['/monitor'] = {heartbeat: '1', config: {enabled: true, token_configured: true, chat_id: '-100<1>', quota_percent: 75, daily_enabled: true, daily_time: '08:30', bot_enabled: false},
        users: [{id: 'u1', name: '<b>alice</b>', note: '', bound: true, username: 'al', bound_at: 5, code_pending: false},
                {id: 'u2', name: 'bob', note: 'n', bound: false, username: '', bound_at: null, code_pending: true}]};
    await context.monitorPage();
    assert.strictEqual(html.section, 'monitor');
    for (const text of ['<h1>通知配置</h1>', 'TG 通知已启用', '-100&lt;1&gt;', '每天 08:30', '流量达到 75%', '用户查询机器人未启用', '已绑定用户：1 / 2', '@al', '绑定码待使用', 'data-action="pu-tg-bot" data-enabled="1"', '&lt;b&gt;alice&lt;/b&gt;'])
        assert(html.shell.includes(text), text);
    assert(!html.shell.includes('<b>alice') && !html.shell.includes('最近通知') && !html.shell.includes('Webhook'));
    assert.strictEqual((html.shell.match(/data-action="pu-tg-unbind"/g) || []).length, 1);
    assert.strictEqual((html.shell.match(/重新生成绑定码/g) || []).length, 2);
    posts.length = 0;
    context.post = async (path, data) => { posts.push([path, data]); return path.endsWith('tg-code') ? {code: 'ABCDEF012345', expires: 99} : {username: 'vaio_bot'}; };
    await context.userAction('pu-tg-bot', {dataset: {enabled: '1'}, disabled: false});
    assert.deepStrictEqual(JSON.parse(JSON.stringify(posts[0])), ['/monitor/bot', {enabled: true}]);
    assert(toasts.at(-1).includes('@vaio_bot'));
    element('bind-command', {select() {}});
    await context.userAction('pu-tg-code', {dataset: {id: 'u2', name: '<i>bob</i>'}});
    assert.strictEqual(posts[1][0], '/users/u2/tg-code');
    assert(html.modal.includes('value="/bind ABCDEF012345"') && html.title.includes('<i>bob</i>'));
    element('pu-choice-form'); element('modal', {close() {}});
    await context.userAction('pu-tg-unbind', {dataset: {id: 'u1', name: 'alice'}});
    assert(html.modal.includes('解除后该用户不再收到个人提醒'));
    await elements['pu-choice-form'].onsubmit({preventDefault() {}, target: {}});
    assert.strictEqual(posts.at(-1)[0], '/users/u1/tg-unbind');
    // 设置弹窗：提交字段与类型
    element('notification-form'); for (const id of ['notify-enabled', 'bot-token', 'clear-token', 'chat-id', 'quota-percent', 'daily-enabled', 'daily-time']) element(id);
    await context.notificationSettings();
    assert(html.modal.includes('已设置，留空保留') && html.modal.includes('value="75"') && html.modal.includes('value="08:30"') && !html.modal.includes('Webhook'));
    Object.assign(elements['notify-enabled'], {checked: true}); elements['bot-token'].value = 'tok'; elements['chat-id'].value = ' 42 ';
    elements['quota-percent'].value = '90'; elements['daily-enabled'].checked = false; elements['daily-time'].value = '07:00';
    await elements['notification-form'].onsubmit({preventDefault() {}, target: {}});
    assert.deepStrictEqual(JSON.parse(JSON.stringify(posts.at(-1))), ['/monitor', {enabled: true, bot_token: 'tok', chat_id: '42', clear_token: false, quota_percent: 90, daily_enabled: false, daily_time: '07:00'}]);
    elements['clear-token'].checked = true;
    await elements['notification-form'].onsubmit({preventDefault() {}, target: {}});
    assert.strictEqual(posts.at(-1)[1].bot_token, '');
    assert.strictEqual(posts.at(-1)[1].clear_token, true);
    console.log('PASS notification page: status, bot toggle, bindings, bind code, unbind, settings payload');

    // 端口转发：列表、筛选、按钮可用性、弹窗字段联动与提交
    const realmRule = {id: 'abcdef012345', backend: 'realm', remark: '<b>web</b>', transport: 'tcp', listen_host: '0.0.0.0', listen_port: 20000, remote_host: 'example.com', remote_port: 80, enabled: true, status: 'running', bytes: 1073741824};
    const nftRule = {id: 'nft-30000', backend: 'nftables', remark: '', transport: 'tcp+udp', listen_host: '0.0.0.0', listen_port: 30000, remote_host: '1.2.3.4', remote_port: 53, enabled: false, status: 'disabled', bytes: null};
    context.nodes = [
        {id: 'a', name: '香港', adopted: true, status: 'online', maintenance: false, deleted: null, snapshot: {forward_version: 1, instances: [{port: 443}], forwards: [realmRule, nftRule]}},
        {id: 'b', name: '东京', adopted: true, status: 'offline', maintenance: false, deleted: null, snapshot: {forward_version: 1, instances: [], forwards: [{...realmRule, id: '0123456789ab', remark: 'tokyo'}]}},
        {id: 'c', name: '旧版', adopted: true, status: 'online', maintenance: false, deleted: null, snapshot: {instances: []}}];
    vm.runInContext('nodes = this.nodes;', context);
    const frows = context.forwardRows();
    assert.strictEqual(frows.length, 3);
    const fmatch = f => frows.filter(r => context.forwardMatches(r, {node: '', backend: '', q: '', ...f})).map(r => r.r.id);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(fmatch({backend: 'nftables'}))), ['nft-30000']);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(fmatch({node: 'b'}))), ['0123456789ab']);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(fmatch({q: '1.2.3.4'}))), ['nft-30000']);
    const ftable = context.forwardTable(frows);
    assert(ftable.includes('&lt;b&gt;web&lt;/b&gt;') && !ftable.includes('<b>web') && ftable.includes('1.0 GiB') && ftable.includes('已停用') && ftable.includes('example.com:80'));
    assert(ftable.includes('data-action="fw-toggle" data-node="a" data-id="nft-30000">启用') && ftable.includes('data-action="fw-edit" data-node="b" data-id="0123456789ab" disabled'));
    for (const id of ['forward-node', 'forward-backend', 'forward-search', 'forward-results', 'forward-count'])
        element(id, {addEventListener(type, fn) { this.listener = fn; }});
    context.forwardsPage();
    assert.strictEqual(html.section, 'forwards');
    assert(html.shell.includes('端口转发') && html.shell.includes('全部类型') && html.shell.includes('data-action="fw-add"') && html.shell.includes('1 台服务器的节点程序版本较旧'));
    assert.strictEqual(elements['forward-count'].textContent, '3');
    elements['forward-backend'].onchange({target: {value: 'realm'}});
    assert.strictEqual(elements['forward-count'].textContent, '2 / 3');
    elements['forward-search'].listener({target: {value: 'zzz'}});
    assert(elements['forward-results'].innerHTML.includes('没有符合条件的转发规则'));
    // 弹窗：nftables 固定 TCP+UDP 与监听地址；新建自动生成端口；提交载荷
    for (const id of ['fw-form', 'fw-node', 'fw-backend', 'fw-remark', 'fw-transport', 'fw-listen-host', 'fw-listen-host-field', 'fw-listen-port', 'fw-generate-port', 'fw-remote-host', 'fw-remote-label', 'fw-remote-port', 'fw-enabled', 'fw-help'])
        element(id, {addEventListener(type, fn) { this.events = {...(this.events || {}), [type]: fn}; }});
    context.crypto = {getRandomValues(a) { a[0] = 5; return a; }};
    vm.runInContext('crypto = this.crypto; installPortCandidate = (used, current) => 20005;', context);
    elements['fw-node'].value = 'a'; elements['fw-backend'].value = 'realm';
    context.forwardDialog('', null);
    assert(html.title === '新建转发' && html.modal.includes('id="fw-node"') && !html.modal.includes('旧版') && !html.modal.includes('东京'));
    assert.strictEqual(elements['fw-listen-port'].value, 20005);
    elements['fw-backend'].value = 'nftables'; elements['fw-backend'].events.change();
    assert(elements['fw-transport'].disabled && elements['fw-transport'].value === 'tcp+udp' && elements['fw-listen-host-field'].hidden && elements['fw-remote-label'].textContent === '目标 IPv4');
    Object.assign(elements['fw-remark'], {value: ' game '}); elements['fw-remote-host'].value = '5.6.7.8'; elements['fw-remote-port'].value = '443'; elements['fw-enabled'].checked = true;
    posts.length = 0;
    context.post = async (path, data) => { posts.push([path, data]); return {id: 'task-1'}; };
    vm.runInContext('refresh = async () => {}; showTask = () => {};', context);
    await elements['fw-form'].onsubmit({preventDefault() {}, target: {}});
    assert.deepStrictEqual(JSON.parse(JSON.stringify(posts[0])), ['/nodes/a/forwards', {op: 'add', rule: {backend: 'nftables', remark: 'game', transport: 'tcp+udp', listen_host: '0.0.0.0', listen_port: 20005, remote_host: '5.6.7.8', remote_port: 443, enabled: true}}]);
    await context.forwardAction('fw-edit', {dataset: {node: 'a', id: 'abcdef012345'}});
    assert(html.title === '修改转发 · 香港' && !html.modal.includes('id="fw-node"') && html.modal.includes('value="&lt;b&gt;web&lt;/b&gt;"'));
    await context.forwardAction('fw-toggle', {dataset: {node: 'a', id: 'nft-30000'}, disabled: false});
    assert.deepStrictEqual(JSON.parse(JSON.stringify(posts.at(-1))), ['/nodes/a/forwards', {op: 'enable', id: 'nft-30000'}]);
    await context.forwardAction('fw-delete', {dataset: {node: 'a', id: 'abcdef012345'}});
    assert(html.modal.includes('监听 20000') && html.modal.includes('example.com:80'));
    await elements['pu-choice-form'].onsubmit({preventDefault() {}, target: {}});
    assert.deepStrictEqual(JSON.parse(JSON.stringify(posts.at(-1))), ['/nodes/a/forwards', {op: 'delete', id: 'abcdef012345'}]);
    await assert.rejects(context.forwardAction('fw-edit', {dataset: {node: 'a', id: 'missing'}}), /不存在/);
    console.log('PASS port forwarding page: rows, filters, writable servers, dialog fields, add/toggle/delete payloads');

    // 中转管理：筛选、线路链与操作按钮、新建弹窗载荷
    const lineA = {id: 'l1', user_id: 'u1', user_name: '<b>alice</b>', state: 'active', entry: {host: '9.9.9.1', port: 30001},
        landing: {node_id: 'c', node_name: '落地', core: 'singbox', protocol: 'hy2', port: 8443, host: '8.8.4.9'},
        hops: [{node_id: 'a', node_name: '香港', backend: 'realm', transport: 'udp', listen_port: 30001, target: '9.9.9.2:30002', status: 'active'},
               {node_id: 'b', node_name: '东京', backend: 'nftables', transport: 'tcp+udp', listen_port: 30002, target: '8.8.4.9:8443', status: 'active'}]};
    const lineB = {...lineA, id: 'l2', user_name: 'bob', state: 'partial', hops: [{...lineA.hops[0], node_id: 'd', node_name: '洛杉矶', status: 'failed'}]};
    assert.deepStrictEqual([lineA, lineB].filter(l => context.relayMatches(l, {node: 'b', q: ''})).map(l => l.id), ['l1']);
    assert.deepStrictEqual([lineA, lineB].filter(l => context.relayMatches(l, {node: 'c', q: ''})).map(l => l.id), ['l1', 'l2']);
    assert.deepStrictEqual([lineA, lineB].filter(l => context.relayMatches(l, {node: '', q: 'BOB'})).map(l => l.id), ['l2']);
    const rtable = context.relayTable([lineA, lineB]);
    assert(rtable.includes('&lt;b&gt;alice&lt;/b&gt;') && !rtable.includes('<b>alice') && rtable.includes('9.9.9.1:30001') && rtable.includes('Hysteria2'));
    assert(rtable.includes('香港<span class="muted"> · Realm</span>') && rtable.includes('<strong>落地</strong>') && rtable.includes('失败'));
    assert(rtable.includes('data-action="rl-share" data-id="l1"') && rtable.includes('data-action="rl-retry" data-id="l2"') && !rtable.includes('data-action="rl-share" data-id="l2"'));
    for (const id of ['relay-node', 'relay-search', 'relay-results', 'relay-count']) element(id, {addEventListener(type, fn) { this.listener = fn; }});
    context.responses['/relays'] = {relays: [lineA, lineB]};
    await context.relaysPage();
    assert.strictEqual(html.section, 'relays');
    assert(html.shell.includes('<h1>中转管理</h1>') && html.shell.includes('data-action="rl-add"') && elements['relay-count'].textContent === '2');
    elements['relay-node'].onchange({target: {value: 'b'}});
    assert.strictEqual(elements['relay-count'].textContent, '1 / 2');
    elements['relay-node'].onchange({target: {value: ''}});
    posts.length = 0;
    context.post = async (path, data) => { posts.push([path, data]); return {id: 'task-9'}; };
    await context.relayAction('rl-retry', {dataset: {id: 'l2'}});
    assert.strictEqual(posts.at(-1)[0], '/relays/l2/retry');
    await context.relayAction('rl-delete', {dataset: {id: 'l1'}});
    assert(html.modal.includes('香港 → 东京') && html.modal.includes('用户在落地协议上的账号保留'));
    await elements['pu-choice-form'].onsubmit({preventDefault() {}, target: {}});
    assert.strictEqual(posts.at(-1)[0], '/relays/l1/delete');
    await context.relayAction('rl-share', {dataset: {id: 'l1'}});
    assert.strictEqual(posts.at(-1)[0], '/relays/l1/share');
    await assert.rejects(context.relayAction('rl-share', {dataset: {id: 'missing'}}), /不存在/);
    const portLine = {...lineA, id: 'l3', user_id: null, user_name: '', port_only: true, landing: {...lineA.landing, protocol: '', core: ''}};
    const ptable = context.relayTable([portLine]);
    assert(ptable.includes('仅转发端口') && ptable.includes('<span class="muted">—</span>') && !ptable.includes('rl-share'));
    // 落地选项：已关联、将关联、被占用的一用户一实例与不支持用户不可选、无用户时协议不可选；最后是仅转发端口
    const landNode = {id: 'c', snapshot: {instances: [
        {core: 'singbox', protocol: 'hy2', port: 8443, user_mode: 'multi', user_available: true, users: [{}]},
        {core: 'xray', protocol: 'vless', port: 443, user_mode: 'multi', user_available: true, users: []},
        {core: 'xray', protocol: 'snell-v6', port: 38915, user_mode: 'single', user_available: true, users: [{name: 'other'}]},
        {core: 'xray', protocol: 'naive', port: 4443, user_mode: 'none', user_available: false, users: []}]}};
    const owner = {id: 'u1', links: [{node_id: 'c', members: [{core: 'singbox', protocol: 'hy2', port: 8443}]}]};
    const opts = context.relayLandingOptions(landNode, owner).map(o => [o.label, o.disabled]);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(opts)), [['Hysteria2 · 8443（已关联）', false], ['VLESS Reality · 443（将为该用户关联）', false],
        ['snell-v6 · 38915（已被其他用户使用）', true], ['naive · 4443（不支持用户）', true], ['仅转发端口（出口机）', false]]);
    const noUser = context.relayLandingOptions(landNode, null);
    assert(noUser.slice(0, 2).every(o => o.disabled && o.label.includes('需选择用户')) && !noUser.at(-1).disabled);
    console.log('PASS relay page: server filter, chain, actions, retry/delete/share payloads');
})().catch(error => { console.error(error); process.exit(1); });
