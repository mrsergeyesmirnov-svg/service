import { api } from 'sdk';

// Invitations are redeemed by the existing FastAPI /api/login endpoint after
// validating Telegram initData. Serverless never accesses PostgreSQL directly.
export default async function (message) {
  if (message?.chat?.type !== 'private' || message.from?.id !== message.chat.id) return;
  const match = /^\/(start|help)(?:@skill_mojo_bot)?(?:\s+(.*))?\s*$/i.exec(message.text || '');
  if (!match) return;
  const invite = match[1].toLowerCase()==='start' && /^[A-Za-z0-9_-]{32}$/.test(match[2]?.trim()||'') ? match[2].trim() : null;
  const academyUrl = 'https://service.139.100.239.232.sslip.io/pilot/' + (invite ? '?invite='+encodeURIComponent(invite) : '');
  const sent = await api.sendMessage({
    chat_id: message.chat.id,
    text: invite
      ? 'Академия сервиса MOJO\n\nОткрой Академию по кнопке ниже, чтобы отправить заявку на доступ. Руководитель подтвердит её после проверки Telegram-аккаунта.'
      : 'Академия сервиса MOJO\n\nМеню, напитки и стандарты сервиса. Открой Академию, чтобы продолжить обучение. Для первого доступа нужно приглашение и подтверждение менеджера.',
    reply_markup: {remove_keyboard: true}
  });
  await api.editMessageReplyMarkup({
    chat_id: message.chat.id, message_id: sent.message_id,
    reply_markup: {inline_keyboard: [[{
      text: 'Открыть Академию',
      web_app: {url: academyUrl}
    }]]}
  });
}

