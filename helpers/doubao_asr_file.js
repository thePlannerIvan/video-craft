// 豆包流式语音识别2.0 (SeedASR SAUC) 整文件转写
// 用法: node doubao_asr_file.js <input.raw|wav> <out.json> <offsetSec>
// 输出 Scribe 兼容: {words:[{text,start,end,type:"word",speaker:"S0"}]}
const fs = require('fs');
const WebSocket = require('ws');

// Credentials are never hardcoded here — this file is published.
// Read them from the environment, falling back to <repo>/.env with the same
// keys the Python sibling documents: DOUBAO_APP_ID / DOUBAO_ACCESS_TOKEN.
function loadCredentials() {
  const envFile = require('path').resolve(__dirname, '..', '.env');
  if (!process.env.DOUBAO_APP_ID || !process.env.DOUBAO_ACCESS_TOKEN) {
    try {
      for (const line of fs.readFileSync(envFile, 'utf8').split('\n')) {
        const t = line.trim();
        if (!t || t.startsWith('#') || !t.includes('=')) continue;
        const i = t.indexOf('=');
        const k = t.slice(0, i).trim();
        if (k && process.env[k] === undefined) process.env[k] = t.slice(i + 1).trim();
      }
    } catch (e) { /* no .env file — the explicit error below reports it */ }
  }
  const appKey = process.env.DOUBAO_APP_ID;
  const accessKey = process.env.DOUBAO_ACCESS_TOKEN;
  if (!appKey || !accessKey) {
    console.error('DOUBAO_APP_ID / DOUBAO_ACCESS_TOKEN not found in the environment or <repo>/.env (see install.md)');
    process.exit(1);
  }
  return { appKey, accessKey };
}
const { appKey: APP_KEY, accessKey: ACCESS_KEY } = loadCredentials();
const RESOURCE_ID = 'volc.seedasr.sauc.duration';
const WS_URL = 'wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream';

const SEG_SEC = parseFloat(process.env.SEG_SEC || '120'); // 每段秒数

const inPath = process.argv[2];
const outPath = process.argv[3];
const baseOffset = parseFloat(process.argv[4] || '0');

function buildHeader(msgType, flags, serialization) {
  return Buffer.from([0x11, (msgType << 4) | flags, (serialization << 4) | 0, 0x00]);
}
function fullClientRequest() {
  const payload = Buffer.from(JSON.stringify({
    user: { uid: 'dsh-transcribe', platform: 'Linux' },
    audio: { format: 'pcm', codec: 'raw', rate: 16000, bits: 16, channel: 1, language: 'zh-CN' },
    request: { model_name: 'bigmodel', enable_punc: true, enable_itn: true, enable_ddc: false, show_utterances: true, result_type: 'full' },
  }));
  const h = buildHeader(1, 0, 1);
  const sz = Buffer.alloc(4); sz.writeUInt32BE(payload.length);
  return Buffer.concat([h, sz, payload]);
}
function audioChunk(pcm) {
  const h = buildHeader(2, 0, 0);
  const sz = Buffer.alloc(4); sz.writeUInt32BE(pcm.length);
  return Buffer.concat([h, sz, pcm]);
}
function finalPacket() {
  const h = buildHeader(2, 2, 0);
  const sz = Buffer.alloc(4); sz.writeUInt32BE(0);
  return Buffer.concat([h, sz]);
}

// read PCM 16k mono (from .raw directly, or .wav via simple 44-byte header skip)
function readPcm(path) {
  const b = fs.readFileSync(path);
  if (path.endsWith('.wav')) return b.subarray(44); // naive RIFF skip
  return b;
}

function transcribeSegment(pcm, segOffsetSec) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(WS_URL, { headers: {
      'X-Api-App-Key': APP_KEY, 'X-Api-Access-Key': ACCESS_KEY,
      'X-Api-Resource-Id': RESOURCE_ID, 'X-Api-Connect-Id': require('crypto').randomUUID(),
    }});
    let lastResult = null, sent = 0;
    const chunkBytes = 3200;
    ws.on('open', () => {
      ws.send(fullClientRequest());
      while (sent < pcm.length) {
        const end = Math.min(sent + chunkBytes, pcm.length);
        ws.send(audioChunk(pcm.subarray(sent, end)));
        sent = end;
      }
      ws.send(finalPacket());
    });
    ws.on('message', (data) => {
      const buf = Buffer.from(data);
      if (buf.length < 8) return;
      const msgType = (buf[1] >> 4) & 0xf;
      const flags = buf[1] & 0xf;
      let off = 4;
      if (flags & 1) off += 4;
      const sz = buf.readUInt32BE(off);
      const payload = buf.subarray(off + 4, off + 4 + sz);
      if (msgType === 9) { try { lastResult = JSON.parse(payload.toString()); } catch (e) {} }
      else if (msgType === 15) { reject(new Error('SERVER ERROR: ' + payload.toString())); ws.close(); }
    });
    ws.on('error', reject);
    ws.on('close', () => {
      const words = [];
      const utts = lastResult?.result?.utterances || [];
      for (const u of utts) {
        for (const w of (u.words || [])) {
          if (w.text === undefined || w.text === '') continue;
          words.push({
            text: w.text, type: 'word', speaker: 'S0',
            start: +(segOffsetSec + w.start_time / 1000).toFixed(3),
            end: +(segOffsetSec + w.end_time / 1000).toFixed(3),
          });
        }
      }
      resolve({ words, utterances: utts.length });
    });
    setTimeout(() => reject(new Error('segment timeout')), 120000);
  });
}

(async () => {
  const pcm = readPcm(inPath);
  const bytesPerSec = 16000 * 2;
  const segBytes = SEG_SEC * bytesPerSec;
  const nSeg = Math.ceil(pcm.length / segBytes);
  console.error(`total ${(pcm.length/bytesPerSec).toFixed(1)}s -> ${nSeg} segments`);
  const allWords = [];
  for (let i = 0; i < nSeg; i++) {
    const seg = pcm.subarray(i * segBytes, Math.min((i + 1) * segBytes, pcm.length));
    const offset = baseOffset + i * SEG_SEC;
    console.error(`segment ${i + 1}/${nSeg} (${(seg.length/bytesPerSec).toFixed(1)}s, offset ${offset}s)...`);
    const { words } = await transcribeSegment(seg, offset);
    allWords.push(...words);
    console.error(`  -> ${words.length} words`);
  }
  allWords.sort((a, b) => a.start - b.start);
  fs.writeFileSync(outPath, JSON.stringify({ text: allWords.map(w => w.text).join(''), language: 'zh', model: 'doubao-seedasr-sauc-2.0', words: allWords }, null, 0));
  console.error(`DONE: ${allWords.length} words -> ${outPath}`);
})();
