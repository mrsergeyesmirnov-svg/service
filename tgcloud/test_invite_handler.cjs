const assert = require('node:assert/strict');
const fs = require('node:fs');

(async () => {
  const source = fs.readFileSync('tgcloud/handlers/message.js', 'utf8');
  const calls = [];
  globalThis.__testApi = {
    sendMessage: async x => { calls.push({ ...x }); return { message_id: calls.length }; },
    editMessageReplyMarkup: async x => { calls.at(-1).button = x.reply_markup; }
  };
  const mocked = source.replace("import { api } from 'sdk';", 'const api = globalThis.__testApi;');
  assert.notEqual(mocked, source, 'SDK import must be replaced for the test');
  const { default: handler } = await import('data:text/javascript;base64,' + Buffer.from(mocked).toString('base64'));
  const message = text => ({ text, chat: { id: 123, type: 'private' }, from: { id: 123 } });
  const base = 'https://service.139.100.239.232.sslip.io/pilot/';
  await handler(message('/start'));
  assert.equal(calls.at(-1).button.inline_keyboard[0][0].web_app.url, base);
  const invite = 'Abcdefghijklmnopqrstuvwxyz123456';
  assert.equal(invite.length, 32);
  await handler(message('/start ' + invite));
  assert.equal(calls.at(-1).button.inline_keyboard[0][0].web_app.url, base + '?invite=' + invite);
  assert.match(calls.at(-1).text, /заявку на доступ/);
  await handler(message('/help ' + invite));
  assert.equal(calls.at(-1).button.inline_keyboard[0][0].web_app.url, base);
  await handler(message('/start not-a-token'));
  assert.equal(calls.at(-1).button.inline_keyboard[0][0].web_app.url, base);
  const count = calls.length;
  await handler({ ...message('/start ' + invite), from: { id: 456 } });
  await handler({ ...message('/start ' + invite), chat: { id: 123, type: 'group' } });
  assert.equal(calls.length, count);
  delete globalThis.__testApi;
  console.log('Telegram Serverless invitation handler tests passed');
})().catch(err => { console.error(err); process.exitCode = 1; });
