const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const chunk = source.slice(source.indexOf('function installPortCandidate('), source.indexOf('function editUser('));
const elements = {};
for (const id of ['ss-method', 'reality-private', 'reality-short-id', 'generate-short-id', 'credential', 'generate-credential', 'certificate-mode', 'acme-email', 'snell-mode', 'dns', 'dns-preference', 'tfo', 'install-options-status', 'certificate-help', 'protocol', 'port', 'sni', 'generate-sni', 'snell-name-field', 'install-name',
    'sni-field', 'sni-label', 'protocol-guidance', 'generated-credentials', 'generation-feedback', 'generate-port', 'generate-name', 'install-form', 'submit']) {
    elements[id] = {value: '', events: {}, addEventListener(event, handler) { this.events[event] = handler; }, reportValidity() { return true; }};
}
elements.protocol.value = 'xray:vless';
elements.port.value = '24443';
elements.sni.value = 'www.cloudflare.com';
elements['install-name'].value = 'u24443';
const calls = [];
let markup = '';
const context = vm.createContext({
    Uint32Array, Uint8Array, Set, Number, Error, btoa: text=>Buffer.from(text, "binary").toString("base64"),
    crypto: {getRandomValues(array) { array[0] = 0; return array; }},
    selected: {snapshot: {task_api_version: 2,
        write_capabilities: [{core: 'xray', protocol: 'vless'}, {core: 'xray', protocol: 'snell-v6'}],
        instances: [{port: 20000, protocol: 'snell-v6', users: [{name: 'u20001'}, {name: 'u20001_1'}]}]}},
    names: {vless: 'VLESS Reality', 'snell-v6': 'Snell v6'},
    esc: value => value,
    modal: (_, html) => { markup = html; },
    $: selector => elements[selector === '[type=submit]' ? 'submit' : selector.slice(1)],
    submitTask: async (...args) => calls.push(args),
    formError: error => { throw error; }
});
vm.runInContext(chunk, context);
async function main() {
    context.install();
    for (const id of ['generate-port', 'generate-name', 'generate-sni']) {
        assert(markup.includes(`type="button" id="${id}"`));
    }
    assert.equal(elements.port.value, '24443'); // opening does not overwrite defaults
    assert.equal(elements['snell-name-field'].hidden, false);
    assert.equal(elements['install-name'].disabled, true);
    assert.match(elements['generated-credentials'].textContent, /UUID/);
    elements['generate-port'].onclick();
    assert.equal(elements.port.value, 20001);
    assert.equal(calls.length, 0); // generation never installs
    elements.protocol.value = 'xray:snell-v6';
    elements.protocol.events.change();
    assert.equal(elements['snell-name-field'].hidden, false);
    assert.equal(elements.sni.disabled, true);
    assert.equal(elements['generate-sni'].disabled, true);
    assert.match(elements['generated-credentials'].textContent, /PSK/);
    elements['generate-name'].onclick();
    assert.equal(elements['install-name'].value, 'u20001_2');
    await elements['install-form'].events.submit({preventDefault() {}, target: elements['install-form']});
    assert.equal(calls[0][2].name, 'u20001_2');
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
        assert.equal(elements['sni-field'].hidden, false);
        assert.equal(elements.sni.required, !snell);
        assert.equal(elements['install-name'].required, snell);
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
    elements['install-name'].value = 'alice';
    elements.protocol.events.change();
    assert.equal(elements['acme-email'].disabled, false);
    assert.equal(elements['acme-email'].required, true);
    assert.equal(elements['generate-sni'].disabled, true);
    assert.equal(elements['snell-mode'].disabled, true);
    await elements['install-form'].events.submit({preventDefault() {}, target: elements['install-form']});
    assert.equal(calls.at(-1)[2].certificate_mode, 'acme');
    assert.equal(calls.at(-1)[2].name, 'alice');
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
    assert.equal(elements['ss-method', 'reality-private'].disabled, false);
    elements['reality-short-id'].value = 'aabbccdd';
    await elements['install-form'].events.submit({preventDefault() {}, target: elements['install-form']});
    assert.equal(calls.at(-1)[2].short_id, 'aabbccdd');
    assert.equal(calls.at(-1)[2].certificate_mode, undefined);
    elements.protocol.value = 'singbox:anytls';
    elements.protocol.events.change();
    assert.equal(elements['ss-method', 'reality-private'].disabled, true);
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
        elements['generate-credential'].onclick();
        if (protocol==='ss2022') assert.equal(Buffer.from(elements.credential.value,'base64').length,16);
        await elements['install-form'].events.submit({preventDefault(){},target:elements['install-form']});
        const params=calls.at(-1)[2];
        assert.equal(params.sni,undefined);
        assert.equal(params.certificate_mode,undefined);
        assert.equal(params.method,elements['ss-method'].value);
    }
    console.log('PASS installation generators, defaults, protocol fields, collisions, no implicit submission');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
