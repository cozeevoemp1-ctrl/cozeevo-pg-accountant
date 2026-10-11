// Send messages to the local sandbox bot and print replies: node probe.mjs "msg1" "msg2" ...
const base = 'http://localhost:8100', phone = process.env.PHONE || '917680814628';
await fetch(base + '/api/test/clear-pending', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ phone }) }).catch(() => {});
for (const [i, m] of process.argv.slice(2).entries()) {
  const r = await fetch(base + '/api/whatsapp/process', { method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ phone, message: m, message_id: `demo-${Date.now()}-${i}` }) });
  const d = await r.json();
  console.log(`>>> ${m}   [${d.intent}]\n${d.reply}\n`);
}
