// 脚本安装（--api install）：协议卡片、按节点字段清单生成的表单、条件字段与提交内容。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const chunk = source.slice(source.indexOf('function installPortCandidate('), source.indexOf('function editUser('));
const schema = {version: 1, protocols: {'vless-vision': {name: 'VLESS-Vision', cores: ['xray'], fields: [
    {key: 'port', type: 'port', label: '端口', optional: true, placeholder: '留空使用推荐端口'},
    {key: 'cert.mode', type: 'enum', label: '证书', default: 'self', options: [{value: 'self', label: '自签证书'}, {value: 'acme', label: "Let's Encrypt"}]},
    {key: 'cert.domain', type: 'domain', label: '域名', optional: false, when: {'cert.mode': 'acme'}},
    {key: 'sni', type: 'host', label: 'SNI', optional: true, when: {'cert.mode': 'self'}}]}}};

// Minimal DOM over the modal markup: controls are found by id / data-key, boxes by data-field.
let markup = '', dom = {};
function render(html) {
    markup = html;
    dom = {byId: {}, boxes: {}, controls: {}, generators: []};
    const node = id => dom.byId[id] ||= {id, value: '', hidden: false, required: false, events: {}, disabled: false,
        addEventListener(event, handler) { this.events[event] = handler; }, focus() {}};
    for (const m of html.matchAll(/<(select|input|form|button)([^>]*)>/g)) {
        const id = /id="([^"]+)"/.exec(m[2])?.[1];
        const key = /data-key="([^"]+)"/.exec(m[2])?.[1];
        const generate = /data-generate="([^"]+)"/.exec(m[2])?.[1];
        if (generate) { const b = node('gen-' + generate); b.dataset = {generate}; dom.generators.push(b); }
        if (!id) continue;
        const el = node(id);
        el.tag = m[1];
        if (key) { el.key = key; dom.controls[key] = el; }
    }
    for (const m of html.matchAll(/<select[^>]*id="([^"]+)"[^>]*>(.*?)<\/select>/g)) {
        const options = [...m[2].matchAll(/<option value="([^"]*)"( selected)?/g)];
        dom.byId[m[1]].value = (options.find(o => o[2]) || options[0])[1];
    }
    for (const m of html.matchAll(/data-field="(\d+)"><label for="([^"]+)"/g)) {
        const control = dom.byId[m[2]];
        dom.boxes[m[1]] = {hidden: false, querySelector: () => control};
    }
    const form = dom.byId['script-install-form'];
    if (form) Object.assign(form, {
        querySelector(selector) {
            const field = /^\[data-field="(\d+)"\]$/.exec(selector), key = /^\[data-key="([^"]+)"\]$/.exec(selector);
            return field ? dom.boxes[field[1]] : key ? dom.controls[key[1]] : selector === '[type=submit]' ? node('submit') : null;
        },
        querySelectorAll(selector) {
            return selector === 'select[data-key]' ? Object.values(dom.controls).filter(c => c.tag === 'select') : selector === '[data-generate]' ? dom.generators : [];
        }
    });
}
const posts = [];
const node = (id, snapshot, extra = {}) => ({id, name: id, adopted: true, status: 'online', maintenance: false, deleted: null,
    snapshot: {task_api_version: 2, write_capabilities: [{core: 'xray', protocol: 'vless'}], instances: [{port: 20000, protocol: 'vless', users: []}], ...snapshot}, ...extra});
const context = vm.createContext({
    Uint32Array, Uint8Array, Set, Number, Error, Object, CSS: {escape: s => s},
    crypto: {getRandomValues(array) { array[0] = 0; return array; }},
    names: {vless: 'VLESS Reality', 'vless-vision': 'VLESS-Vision'},
    esc: value => String(value).replace(/</g, '&lt;').replace(/"/g, '&quot;'),
    modal: (_, html, wide, kind, back) => { render(html); context.back = back; },
    $: selector => selector.startsWith('#') ? dom.byId[selector.slice(1)] : selector === '[type=submit]' ? (dom.byId.submit ||= {}) : null,
    post: async (url, data) => { posts.push([url, data]); return {id: 't1'}; },
    refresh: async () => {}, showTask: id => { context.shown = id; },
    formError: error => { throw error; }
});
context.nodes = [node('a', {install_version: 1, install_schema: schema}), node('old', {})];
context.selected = context.nodes[0];
vm.runInContext('var activeTaskId = null;\n' + chunk, context);

async function main() {
    context.startInstall('a');
    assert(markup.includes('value="vless"') && markup.includes('value="script:vless-vision"'));
    assert(markup.includes('脚本安装 · 支持自有域名'));
    dom.byId['install-server'].events.change({target: {value: 'old'}});
    assert(markup.includes('value="vless"') && !markup.includes('script:')); // node without the schema
    dom.byId['install-server'].events.change({target: {value: 'a'}});
    dom.byId['protocol-choice-form'].events.submit({preventDefault() {}, submitter: {value: 'script:hy2'}});
    assert(markup.includes('protocol-choice-form')); // unknown script protocol does not open a form
    dom.byId['protocol-choice-form'].events.submit({preventDefault() {}, submitter: {value: 'script:vless-vision'}});
    assert(markup.includes('script-install-form'));
    assert(markup.includes('<option value="old" disabled>old（不支持此协议）</option>'));
    assert(!markup.includes('id="script-core"')); // one core: no picker
    const box = i => dom.boxes[i];
    // Self-signed by default: SNI shown, domain hidden and not required.
    assert.equal(dom.controls['cert.mode'].value, 'self');
    assert.deepEqual([box(2).hidden, box(3).hidden, dom.controls['cert.domain'].required, dom.controls.port.required], [true, false, false, false]);
    dom.generators[0].events.click();
    assert.equal(dom.controls.port.value, 20001); // free random high port
    dom.controls.sni.value = ' cdn.example.com ';
    await dom.byId['script-install-form'].events.submit({preventDefault() {}});
    assert.deepEqual(JSON.parse(JSON.stringify(posts.at(-1))), ['/nodes/a/script-install', {protocol: 'vless-vision', core: 'xray', answers: {port: 20001, 'cert.mode': 'self', sni: 'cdn.example.com'}}]);
    assert.equal(context.shown, 't1');
    // Let's Encrypt: domain shown and required, SNI hidden and not sent.
    dom.controls['cert.mode'].value = 'acme';
    dom.controls['cert.mode'].events.change();
    assert.deepEqual([box(2).hidden, box(3).hidden, dom.controls['cert.domain'].required], [false, true, true]);
    dom.controls['cert.domain'].value = 'a.example.com';
    dom.controls.port.value = '';
    await dom.byId['script-install-form'].events.submit({preventDefault() {}});
    assert.deepEqual(JSON.parse(JSON.stringify(posts.at(-1)[1].answers)), {'cert.mode': 'acme', 'cert.domain': 'a.example.com'});
    console.log('PASS script install: schema cards, unsupported servers, conditional fields, port generator and submitted answers');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
