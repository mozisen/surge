const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const chunk = source.slice(source.indexOf('function installPortCandidate('), source.indexOf('function editUser('));
const elements = {};
for (const id of ['protocol', 'port', 'sni', 'reset-sni', 'snell-name-field', 'install-name',
    'generated-credentials', 'generation-feedback', 'generate-port', 'generate-name', 'install-form', 'submit']) {
    elements[id] = {value: '', events: {}, addEventListener(event, handler) { this.events[event] = handler; }, reportValidity() { return true; }};
}
elements.protocol.value = 'xray:vless';
elements.port.value = '24443';
elements.sni.value = 'www.cloudflare.com';
elements['install-name'].value = 'u24443';
const calls = [];
let markup = '';
const context = vm.createContext({
    Uint32Array, Set, Number, Error,
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
    for (const id of ['generate-port', 'generate-name', 'reset-sni']) {
        assert(markup.includes(`type="button" id="${id}"`));
    }
    assert.equal(elements.port.value, '24443'); // opening does not overwrite defaults
    assert.equal(elements['snell-name-field'].hidden, true);
    assert.equal(elements['install-name'].disabled, true);
    assert.match(elements['generated-credentials'].textContent, /UUID/);
    elements['generate-port'].onclick();
    assert.equal(elements.port.value, 20001);
    assert.equal(calls.length, 0); // generation never installs
    elements.protocol.value = 'xray:snell-v6';
    elements.protocol.events.change();
    assert.equal(elements['snell-name-field'].hidden, false);
    assert.equal(elements.sni.disabled, true);
    assert.equal(elements['reset-sni'].disabled, true);
    assert.match(elements['generated-credentials'].textContent, /PSK/);
    elements['generate-name'].onclick();
    assert.equal(elements['install-name'].value, 'u20001_2');
    await elements['install-form'].events.submit({preventDefault() {}, target: elements['install-form']});
    assert.equal(calls[0][2].name, 'u20001_2');
    assert.equal(calls[0][2].sni, undefined);
    elements.protocol.value = 'xray:vless';
    elements.protocol.events.change();
    elements.sni.value = 'custom.example.com';
    elements['reset-sni'].onclick();
    assert.equal(elements.sni.value, 'www.cloudflare.com');
    await elements['install-form'].events.submit({preventDefault() {}, target: elements['install-form']});
    assert.equal(calls[1][2].name, undefined);
    assert.equal(calls[1][2].sni, 'www.cloudflare.com');
    const allUsed = Array.from({length: 45536}, (_, i) => ({port: i + 20000}));
    assert.throws(() => context.installPortCandidate(allUsed, 24443), /没有可推荐/);
    assert.equal(context.installNameCandidate([{protocol: 'snell', users: [{name: 'u12345'}]}], 'snell-v6', 12345), 'u12345');
    console.log('PASS installation generators, defaults, protocol fields, collisions, no implicit submission');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
