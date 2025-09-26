#!/usr/bin/env node
import http from 'node:http';
import https from 'node:https';
import { URL } from 'node:url';
import zlib from 'node:zlib';
import { pipeline } from 'node:stream';

const UPSTREAM = 'https://floodmap.drose.io';
const PORT = Number(process.env.PORT || 8900);

function isTile(pathname){
  return pathname.startsWith('/api/v1/tiles/');
}
function isCompressible(pathname, contentType){
  if (/\.u16(\?|$)/.test(pathname)) return true; // elevation raw
  if (/\.pbf(\?|$)/.test(pathname)) return true; // vector MVT
  if (contentType && /(json|javascript|text|css|xml|wasm)/i.test(contentType)) return true;
  return false;
}

function proxy(req, res){
  try {
    const reqUrl = new URL(req.url, `http://localhost:${PORT}`);
    const upstreamUrl = new URL(reqUrl.pathname + reqUrl.search, UPSTREAM);
    const isTileReq = isTile(reqUrl.pathname);
    const opts = {
      method: req.method,
      headers: { ...req.headers }
    };
    // Normalize headers to avoid hop-by-hop
    delete opts.headers['host'];
    delete opts.headers['content-length'];
    // Fetch uncompressed from upstream so we can apply our own encoding
    if (isTileReq) {
      opts.headers['accept-encoding'] = 'identity';
    }
    const client = upstreamUrl.protocol === 'https:' ? https : http;
    const upstreamReq = client.request(upstreamUrl, opts, (upstreamRes) => {
      const { statusCode, headers } = upstreamRes;
      // Copy headers
      const outHeaders = { ...headers };
      delete outHeaders['content-length'];
      // Apply compression for compressible resources if client accepts br
      const wantsBr = /\bbr\b/.test(String(req.headers['accept-encoding']||''));
      const ctype = String(headers['content-type']||'');
      const compress = isTileReq && isCompressible(reqUrl.pathname, ctype) && wantsBr;
      if (compress) {
        outHeaders['content-encoding'] = 'br';
        outHeaders['vary'] = 'Accept-Encoding';
      }
      res.writeHead(statusCode || 502, outHeaders);
      if (compress) {
        const bro = zlib.createBrotliCompress({
          params: {
            [zlib.constants.BROTLI_PARAM_QUALITY]: 11,
            [zlib.constants.BROTLI_PARAM_MODE]: zlib.constants.BROTLI_MODE_GENERIC
          }
        });
        pipeline(upstreamRes, bro, res, (err)=>{ if(err){ console.error('pipeline error', err); res.end(); } });
      } else {
        pipeline(upstreamRes, res, (err)=>{ if(err){ console.error('pipeline error', err); res.end(); } });
      }
    });
    upstreamReq.on('error', (e)=>{
      console.error('Upstream error', e.message);
      res.writeHead(502, { 'content-type': 'text/plain' });
      res.end('Bad gateway');
    });
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      pipeline(req, upstreamReq, (err)=>{ if(err) console.error('req pipe error', err); });
    } else {
      upstreamReq.end();
    }
  } catch (e) {
    console.error('Proxy error', e);
    res.writeHead(500, { 'content-type': 'text/plain' });
    res.end('Internal error');
  }
}

http.createServer(proxy).listen(PORT, () => {
  console.log(`Proxy listening on http://localhost:${PORT} -> ${UPSTREAM}`);
});
