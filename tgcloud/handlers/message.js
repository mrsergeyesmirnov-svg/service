import { api } from 'sdk';

// This handler only opens the existing Academy. Authorization and all course
// data remain on its backend. It does not create or approve employee accounts.
export default async function (message) {
  if (message?.chat?.type !== 'private' || message.from?.id !== message.chat.id) return;
  const match = /^\/(start|help)(?:@skill_mojo_bot)?(?:\s+(.*))?\s*$/i.exec(message.text || '');
  if (!match) return;
  const invitation = Boolean(match[2]?.trim());
  const sent = await api.sendMessage({
    chat_id: message.chat.id,
    text: invitation
      ? 'Академия сервиса MOJO\n\nВход для действующих сотрудников — по кнопке ниже. Регистрация по приглашению через этого обработчика пока недоступна: для первого доступа обратитесь к менеджеру.'
      : 'Академия сервиса MOJO\n\nМеню, напитки и стандарты сервиса. Открой Академию, чтобы продолжить обучение. Для первого доступа нужно приглашение и подтверждение менеджера.',
    reply_markup: {remove_keyboard: true}
  });
  await api.editMessageReplyMarkup({
    chat_id: message.chat.id, message_id: sent.message_id,
    reply_markup: {inline_keyboard: [[{
      text: 'Открыть Академию',
      web_app: {url: 'https://service.139.100.239.232.sslip.io/pilot/'}
    }]]}
  });
}

