const http  = require('http');
const https = require('https');

const PORT = 8766;

const server = http.createServer((req, res) => {
  // CORS headers so the browser accepts the response
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.method !== 'POST' || req.url !== '/birth-compatibility') {
    res.writeHead(404);
    res.end('Not found');
    return;
  }

  let body = '';
  req.on('data', chunk => { body += chunk; });
  req.on('end', () => {
    const options = {
      hostname: 'pink-api.ru',
      path:     '/birth-compatibility',
      method:   'POST',
      headers: {
        'Content-Type':   'application/json',
        'Content-Length': Buffer.byteLength(body),
        'Origin':         'https://in-contri.ru',
        'Referer':        'https://in-contri.ru/',
        'User-Agent':     'Mozilla/5.0',
      }
    };

    const proxyReq = https.request(options, proxyRes => {
      res.writeHead(proxyRes.statusCode, { 'Content-Type': 'application/json' });
      proxyRes.pipe(res);
    });

    proxyReq.on('error', err => {
      console.error('Proxy error:', err.message);
      res.writeHead(502);
      res.end(JSON.stringify({ error: err.message }));
    });

    proxyReq.write(body);
    proxyReq.end();
  });
});

server.listen(PORT, () => {
  console.log(`Proxy running at http://localhost:${PORT}`);
  console.log('Forwarding /birth-compatibility → https://pink-api.ru/birth-compatibility');
});
