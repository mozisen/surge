"""Opt-in real core TCP test: requires sing-box with V2Ray API, grpcurl and curl.
Uses only temporary loopback listeners and random credentials; never production config.
"""
import base64, contextlib, http.server, json, os, socket, subprocess, tempfile, threading, time
@contextlib.contextmanager
def reserve():
    s=socket.socket();s.bind(('127.0.0.1',0));p=s.getsockname()[1];s.close();yield p
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.end_headers();self.wfile.write(b'x'*262144)
    def log_message(self,*args):pass
server=http.server.HTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
methods=['aes-128-gcm','aes-256-gcm','chacha20-ietf-poly1305','2022-blake3-aes-128-gcm','2022-blake3-aes-256-gcm']
proto='syntax="proto3"; package v2ray.core.app.stats.command; message QueryStatsRequest {string pattern=1; bool reset=2;} message Stat {string name=1; int64 value=2;} message QueryStatsResponse {repeated Stat stat=1;} service StatsService {rpc QueryStats(QueryStatsRequest) returns(QueryStatsResponse);}'
with tempfile.TemporaryDirectory(prefix='vaio-ss-proof-') as d:
    os.chmod(d,0o700)
    open(d+'/stats.proto','w').write(proto)
    for method in methods:
        with reserve() as ss, reserve() as api, reserve() as socks:
            key=base64.b64encode(os.urandom(16 if '128' in method else 32)).decode()
            configs=[{'inbounds':[{'type':'shadowsocks','tag':'proof','listen':'127.0.0.1','listen_port':ss,'method':method,'password':key}], 'outbounds':[{'type':'direct'}],'experimental':{'v2ray_api':{'listen':'127.0.0.1:'+str(api),'stats':{'enabled':True,'inbounds':['proof']}}}}, {'inbounds':[{'type':'socks','listen':'127.0.0.1','listen_port':socks}], 'outbounds':[{'type':'shadowsocks','server':'127.0.0.1','server_port':ss,'method':method,'password':key}]}]
            procs=[]
            try:
                for i,c in enumerate(configs):
                    path=d+'/'+str(i)+'.json';open(path,'w').write(json.dumps(c))
                    subprocess.run(['sing-box','check','-c',path],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    procs.append(subprocess.Popen(['sing-box','run','-c',path],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
                time.sleep(1)
                subprocess.run(['curl','--fail','--silent','--max-time','8','--noproxy','','--socks5-hostname','127.0.0.1:'+str(socks),'http://127.0.0.1:'+str(server.server_port)],check=True,stdout=subprocess.DEVNULL)
                time.sleep(.2)
                def counters():
                    r=subprocess.check_output(['grpcurl','-plaintext','-max-time','5','-import-path',d,'-proto','stats.proto','-d','{"pattern":"inbound>>>","reset":false}','127.0.0.1:'+str(api),'v2ray.core.app.stats.command.StatsService/QueryStats'])
                    return {s['name']:int(s.get('value',0)) for s in json.loads(r).get('stat',[])}
                c=counters();assert c['inbound>>>proof>>>traffic>>>downlink']>=262144 and c['inbound>>>proof>>>traffic>>>uplink']>0,c
                assert counters()==c
                print(method+': PASS payload, inbound counters, non-reset reads',flush=True)
            finally:
                for p in procs:p.terminate()
                for p in procs:p.wait(timeout=5)
server.shutdown()
