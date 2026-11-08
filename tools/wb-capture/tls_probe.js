// tls_probe.js - 用客户端自带的 Electron/Node 复现 CLI 的 TLS 路径：
// CONNECT 127.0.0.1:8888 -> TLS(www.workbuddy.cn) -> 发一个 GET
// 用于验证 NODE_TLS_REJECT_UNAUTHORIZED / NODE_EXTRA_CA_CERTS 是否真的生效。
const net = require('net');
const tls = require('tls');

const target = process.argv[2] || 'www.workbuddy.cn';
const sock = net.connect(8888, '127.0.0.1', () => {
  sock.write(`CONNECT ${target}:443 HTTP/1.1\r\nHost: ${target}:443\r\n\r\n`);
});

let buf = '';
sock.once('data', (d) => {
  buf += d.toString('latin1');
  if (!buf.startsWith('HTTP/1.1 200')) {
    console.log('CONNECT failed:', buf.split('\r\n')[0]);
    process.exit(2);
  }
  const s = tls.connect({
    socket: sock,
    servername: target,
    rejectUnauthorized: process.env.NODE_TLS_REJECT_UNAUTHORIZED === '0' ? false : true,
  }, () => {
    console.log('TLS OK, authorized =', s.authorized, 'alpn =', s.alpnProtocol);
    s.write(`GET /v3/config HTTP/1.1\r\nHost: ${target}\r\nAccept: application/json\r\nConnection: close\r\n\r\n`);
  });
  s.on('data', (d) => {
    const head = d.toString('latin1').split('\r\n')[0];
    console.log('HTTP:', head);
    process.exit(0);
  });
  s.on('error', (e) => {
    console.log('TLS ERROR:', e.code, e.message);
    process.exit(3);
  });
});
sock.on('error', (e) => { console.log('SOCKET ERROR:', e.code, e.message); process.exit(4); });
setTimeout(() => { console.log('timeout'); process.exit(5); }, 15000);
