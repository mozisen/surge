const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const chunk = source.slice(source.indexOf('function installPortCandidate('), source.indexOf('function editUser('));
const elements = {};
for (const id of ['protocol-choice-form', 'install-back', 'install-advanced', 'install-core-field', 'ss-method-field', 'credential-fields', 'certificate-fields', 'reality-fields', 'snell-fields', 'credential-label', 'acme-email-field', 'ss-method', 'reality-private', 'reality-short-id', 'generate-short-id', 'credential', 'generate-credential', 'certificate-mode', 'acme-email', 'snell-mode', 'dns', 'dns-preference', 'tfo', 'install-options-status', 'certificate-help', 'protocol', 'port', 'sni', 'generate-sni',
    'sni-field', 'sni-label', 'protocol-guidance', 'generated-credentials', 'generation-feedback', 'generate-port', 'install-form', 'submit', 'install-server']) {
    elements[id] = {value: '', events: {}, focus() {}, addEventListener(event, handler) { this.events[event] = handler; }, reportValidity() { return true; }};
}
elements.protocol.value = 'xray:vless';
elements.port.value = '24443';
elements.sni.value = 'www.cloudflare.com';
const calls = [];
let markup = '';
const context = vm.createContext({
    Uint32Array, Uint8Array, Set, Number, Error, btoa: text=>Buffer.from(text, "binary").toString("base64"),
    crypto: {getRandomValues(array) { array[0] = 0; return array; }},
    selected: {id: 'a', name: '香港', adopted: true, status: 'online', maintenance: false, deleted: null, snapshot: {task_api_version: 2,
        write_capabilities: [{core: 'xray', protocol: 'vless'}, {core: 'xray', protocol: 'snell-v6'}],
        instances: [{port: 20000, protocol: 'snell-v6', users: [{name: 'u20001'}, {name: 'u20001_1'}]}]}},
    names: {vless: 'VLESS Reality', 'snell-v6': 'Snell v6'},
    esc: value => value,
    modal: (_, html, wide, kind, back) => { markup = html; context.back = back; },
    $: selector => elements[selector === '[type=submit]' ? 'submit' : selector.slice(1)],
    submitTask: async (...args) => calls.push(args),
    formError: error => { throw error; }
});
const server = (id, extra = {}) => ({id, name: 'node-' + id, adopted: true, status: 'online', maintenance: false, deleted: null,
    snapshot: {task_api_version: 2, write_capabilities: [{core: 'singbox', protocol: 'vless'}], instances: [{port: 30000, protocol: 'vless', users: []}]}, ...extra});
context.nodes = [context.selected, server('b', {name: '<b>东京</b>'}), server('c', {status: 'offline'}), server('d', {deleted: 1}),
    server('e', {maintenance: true}), server('f', {adopted: false}), server('g', {snapshot: {task_api_version: 2, write_capabilities: [], instances: []}})];
vm.runInContext(chunk, context);
async function main() {
    context.install();
    assert(markup.includes('protocol-choice-form'));
    assert(!markup.includes('install-form'));
    assert.equal(calls.length, 0);
    assert(markup.includes('<button type="submit" class="protocol-card" value="vless">'));
    assert(markup.includes('<button type="submit" class="protocol-card" value="snell-v6">'));
    assert(markup.includes('Reality · TCP'));
    assert(markup.includes('已安装 1 个')); // snell-v6 has one instance; vless has none
    assert.equal((markup.match(/已安装/g) || []).length, 1);
    assert.equal((markup.match(/<select/g) || []).length, 1); // only the server picker
    assert(markup.includes('<option value="a" selected>香港</option>') && markup.includes('<option value="b"><b>东京</b></option>'));
    for (const id of ['c', 'd', 'e', 'f']) assert(!markup.includes(`<option value="${id}"`)); // offline, deleted, maintenance, unadopted
    elements['protocol-choice-form'].events.submit({preventDefault(){}, submitter: {value: 'unknown'}});
    elements['protocol-choice-form'].events.submit({preventDefault(){}});
    assert(!markup.includes('install-form')); // unknown or missing card value does not open the form
    elements['protocol-choice-form'].events.submit({preventDefault(){}, submitter: {value: 'vless'}});
    assert(markup.includes('install-form'));
    // One page: no collapsed group, no section headings, no in-form back button; the header arrow returns.
    for (const gone of ['<details', '基础设置', '高级设置', '证书设置', 'install-back', '返回选择协议', 'generated-credentials']) assert(!markup.includes(gone), gone);
    assert.equal(typeof context.back, 'function');
    assert(markup.includes('class="install-top"') && markup.includes('class="install-grid"'));
    assert(!markup.includes('value="xray:snell-v6"'));
    for (const id of ['generate-port', 'generate-sni']) {
        assert(markup.includes(`type="button" id="${id}"`));
    }
    // No account name is typed: the field and its generator are gone, and the port starts random.
    for (const id of ['install-name', 'generate-name', 'snell-name-field']) assert(!markup.includes(`id="${id}"`));
    assert(!markup.includes('24443'));
    assert.equal(elements.port.value, 20001); // opening picks a free random high port
    assert.equal(elements['credential-label'].textContent, 'UUID');
    assert.equal(elements['credential-fields'].hidden, true); // install_options_version 0: no credential field
    elements['generate-port'].onclick();
    assert.equal(elements.port.value, 20002);
    assert.equal(calls.length, 0); // generation never installs
    elements.protocol.value = 'xray:snell-v6';
    elements.protocol.events.change();
    assert.equal(elements.sni.disabled, true);
    assert.equal(elements['generate-sni'].disabled, true);
    assert.equal(elements['credential-label'].textContent, 'PSK');
    elements.port.value = '20001';
    await elements['install-form'].events.submit({preventDefault() {}, target: elements['install-form']});
    assert.equal(calls[0][2].name, 'u20001_2'); // generated, unused by this protocol
    assert.equal(calls[0][2].sni, undefined);
    elements.protocol.value = 'xray:vless';
    elements.protocol.events.change();
    elements.sni.value = 'custom.example.com';
    elements['generate-sni'].onclick();
    assert.equal(elements.sni.value, 'ads.apple.com');
    await elements['install-form'].events.submit({preventDefault() {}, target: elements['install-form']});
    assert.equal(calls[1][2].name, undefined);
    assert.equal(calls[1][2].sni, 'ads.apple.com');
    for (const combo of ['xray:vless', 'singbox:vless', 'singbox:hy2', 'xray:trojan', 'singbox:trojan', 'singbox:anytls', 'xray:snell', 'xray:snell-v5', 'xray:snell-v6']) {
        elements.protocol.value = combo;
        elements.protocol.events.change();
        const snell = combo.includes('snell');
        assert.equal(elements['sni-field'].hidden, snell);
        assert.equal(elements.sni.required, !snell);
        assert(elements['protocol-guidance'].textContent.length > 10);
        await elements['install-form'].events.submit({preventDefault() {}, target: elements['install-form']});
        assert.deepEqual(Object.keys(calls.at(-1)[2]), [snell ? 'name' : 'sni']);
    }
    const script = fs.readFileSync(path.join(__dirname, '../vendor/vless-server.sh'), 'utf8');
    const pool = [...script.match(/readonly COMMON_SNI_LIST=\(([\s\S]*?)\n\)/)[1].matchAll(/"([^"]+)"/g)].map(m => m[1]);
    const generated = [];
    for (let i = 0; i < pool.length; i++) {
        context.crypto.getRandomValues = array => {array[0] = i; return array;};
        generated.push(context.installSniCandidate('custom.example'));
    }
    assert.deepEqual(generated, pool);
    assert.notEqual(context.installSniCandidate('ads.apple.com'), 'ads.apple.com');
    context.selected.snapshot.install_options_version = 1;
    elements.protocol.value = 'singbox:anytls';
    elements['certificate-mode'].value = 'acme';
    elements['acme-email'].value = 'admin@example.com';
    elements.protocol.events.change();
    assert.equal(elements['credential-fields'].hidden, false);
    assert.equal(elements['certificate-help'].hidden, false); // ACME explains its requirements
    assert.equal(elements['acme-email'].disabled, false);
    assert.equal(elements['acme-email'].required, true);
    assert.equal(elements['generate-sni'].disabled, true);
    assert.equal(elements['snell-mode'].disabled, true);
    await elements['install-form'].events.submit({preventDefault() {}, target: elements['install-form']});
    assert.equal(calls.at(-1)[2].certificate_mode, 'acme');
    assert.match(calls.at(-1)[2].name, /^u\d+/);
    elements.protocol.value = 'xray:snell-v6';
    elements['snell-mode'].value = 'unshaped';
    elements['dns-preference'].value = 'prefer-ipv4';
    elements.dns.value = '1.1.1.1';
    elements.tfo.value = 'false';
    elements.protocol.events.change();
    assert.equal(elements['certificate-mode'].disabled, true);
    assert.equal(elements['snell-mode'].disabled, false);
    await elements['install-form'].events.submit({preventDefault() {}, target: elements['install-form']});
    assert.equal(calls.at(-1)[2].mode, 'unshaped');
    assert.equal(calls.at(-1)[2].tfo, false);
    assert.equal(calls.at(-1)[2].acme_email, undefined);
    assert.equal(calls.at(-1)[2].sni, undefined);
    context.selected.snapshot.install_options_version = 2;
    elements.protocol.value = 'singbox:vless';
    elements.protocol.events.change();
    assert.equal(elements['reality-private'].disabled, false);
    elements['reality-short-id'].value = 'aabbccdd';
    await elements['install-form'].events.submit({preventDefault() {}, target: elements['install-form']});
    assert.equal(calls.at(-1)[2].short_id, 'aabbccdd');
    assert.equal(calls.at(-1)[2].certificate_mode, undefined);
    elements.protocol.value = 'singbox:anytls';
    elements.protocol.events.change();
    assert.equal(elements['reality-private'].disabled, true);
    await elements['install-form'].events.submit({preventDefault() {}, target: elements['install-form']});
    assert.equal(calls.at(-1)[2].short_id, undefined);
    context.selected.snapshot.install_options_version = 1;
    elements.protocol.value = 'xray:vless';
    elements.protocol.events.change();
    assert.equal(elements['reality-short-id'].disabled, true);
    const allUsed = Array.from({length: 45536}, (_, i) => ({port: i + 20000}));
    assert.throws(() => context.installPortCandidate(allUsed, 24443), /没有可推荐/);
    assert.equal(context.installNameCandidate([{protocol: 'snell', users: [{name: 'u12345'}]}], 'snell-v6', 12345), 'u12345');
    for (const protocol of ['ss-legacy', 'ss2022']) {
        elements.protocol.value='singbox:'+protocol;
        elements.protocol.events.change();
        assert.equal(elements.sni.disabled,true);
        assert.equal(elements['certificate-mode'].disabled,true);
        assert.equal(elements['ss-method'].disabled,false);
        assert.equal(elements['sni-field'].hidden,true);
        assert.equal(elements['certificate-fields'].hidden,true);
        assert.equal(elements['reality-fields'].hidden,true);
        assert.equal(elements['snell-fields'].hidden,true);
        assert.equal(elements['ss-method-field'].hidden,false);
        elements['generate-credential'].onclick();
        if (protocol==='ss2022') assert.equal(Buffer.from(elements.credential.value,'base64').length,16);
        await elements['install-form'].events.submit({preventDefault(){},target:elements['install-form']});
        const params=calls.at(-1)[2];
        assert.equal(params.sni,undefined);
        assert.equal(params.certificate_mode,undefined);
        assert.equal(params.method,elements['ss-method'].value);
    }
    context.back();
    assert(markup.includes('protocol-choice-form'));

    // Server selection: defaults, switching, submission target, nothing installable.
    context.esc = value => String(value).replace(/</g, '&lt;');
    context.startInstall('b');
    assert(markup.includes('<option value="b" selected>&lt;b>东京&lt;/b></option>'));
    assert(markup.includes('value="vless"') && !markup.includes('value="snell-v6"') && markup.includes('已安装 1 个')); // node b: one vless instance
    context.startInstall('c'); // offline: falls back to the first installable server
    assert(markup.includes('<option value="a" selected>'));
    elements['install-server'].events.change({target: {value: 'g'}});
    assert(markup.includes('<option value="g" selected>') && markup.includes('未声明可用写入能力') && !markup.includes('protocol-card'));
    elements['install-server'].events.change({target: {value: 'a'}});
    elements['protocol-choice-form'].events.submit({preventDefault(){}, submitter: {value: 'snell-v6'}});
    assert(markup.includes('<option value="b" disabled>&lt;b>东京&lt;/b>（不支持此协议）</option>') && markup.includes('<option value="g" disabled>'));
    elements['protocol-choice-form'].events.submit({preventDefault(){}, submitter: {value: 'vless'}});
    elements['install-server'].events.change({target: {value: 'b'}});
    assert(markup.includes('<option value="b" selected>') && markup.includes('value="singbox:vless"') && !markup.includes('value="xray:vless"'));
    context.selected = context.nodes[0]; // a periodic re-render of the detail page resets `selected`
    elements.protocol.value = 'singbox:vless';
    elements.protocol.events.change();
    await elements['install-form'].events.submit({preventDefault() {}, target: elements['install-form']});
    assert.equal(calls.at(-1)[3].id, 'b'); // submitted to the chosen server
    context.nodes = [server('c', {status: 'offline'})];
    context.startInstall('c');
    assert(markup.includes('需要已接管、在线') && !markup.includes('protocol-choice-form'));
    console.log('PASS install server picker: eligible servers, defaults, switching, submission target, none available');
    console.log('PASS installation generators, defaults, protocol fields, collisions, no implicit submission');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
