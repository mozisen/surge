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
    document: {querySelectorAll: selector => Object.values(elements).filter(e => e.matches && e.matches(selector))},
    console,
};
context.api = async path => context.responses[path];
context.post = async (path, data) => { posts.push([path, data]); return {id: 'new-user', deleted: true}; };
vm.createContext(context);
vm.runInContext(code + '\nthis.usersPage=usersPage;this.userDetail=userDetail;this.userForm=userForm;this.membersDialog=membersDialog;this.linkDialog=linkDialog;this.authorityBlock=authorityBlock;this.authorityDialog=authorityDialog;this.upgradeDialog=upgradeDialog;', context);

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
    assert(block.includes('以节点脚本为准') && block.includes('切换为平台管理') && block.includes('已回滚') && block.includes('新版未按时上线'));
    assert(context.authorityBlock(node('c', {snapshot: {instances: []}})).includes('旧版节点'));
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
})().catch(error => { console.error(error); process.exit(1); });
