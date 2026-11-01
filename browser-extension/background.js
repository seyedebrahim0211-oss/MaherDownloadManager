const SERVICE = 'http://127.0.0.1:17691';
const allowed = url => /^https?:\/\//i.test(url || '') || /^ftp:\/\//i.test(url || '');
const media = url => /(?:youtube\.com|youtu\.be|\.m3u8(?:\?|$)|\.mpd(?:\?|$))/i.test(url || '');
const credentials = async () => (await chrome.storage.local.get(['pairingToken','autoCapture']));
const normalizeToken = value => String(value || '').replace(/[\s\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]/g, '').toLowerCase();
const validToken = token => /^[0-9a-f]{48}$/.test(token);
const errorMessage = {
  missing_code:'کد اتصال را از خود برنامه ماهر کپی کنید.',
  invalid_format:'کد باید ۴۸ نویسه انگلیسی داشته باشد؛ از دکمه کپی برنامه استفاده کنید.',
  invalid_code:'کد با برنامه فعال مطابقت ندارد. همه نسخه‌های باز ماهر را ببندید، فقط یک نسخه اجرا و کد را دوباره کپی کنید.',
  invalid_origin:'مجوز افزونه معتبر نیست؛ افزونه جدید را مجدداً بارگذاری کنید.',
  not_found:'برنامه یا افزونه قدیمی است؛ هر دو را به‌روز کنید.',
  offline:'برنامه ماهر اجرا نیست یا درگاه ۱۷۶۹۱ در دسترس نیست.'
};
const fail = code => ({ok:false,error_code:code,error:errorMessage[code]||'ارتباط برقرار نشد.'});

async function health(candidate) {
  const token = normalizeToken(candidate === undefined ? (await credentials()).pairingToken : candidate);
  if (!token) return fail('missing_code');
  if (!validToken(token)) return fail('invalid_format');
  try {
    const r = await fetch(`${SERVICE}/health`, {headers:{'X-Maher-Token':token},cache:'no-store'});
    const body = await r.json().catch(() => ({}));
    if (!r.ok || !body.ok) return fail(body.error_code || (r.status === 401 ? 'invalid_code' : r.status === 404 ? 'not_found' : 'offline'));
    return {ok:true,protocol:body.protocol || 1};
  } catch (_) { return fail('offline'); }
}
async function pair(candidate) {
  const token = normalizeToken(candidate);
  const state = await health(token);
  if (state.ok) await chrome.storage.local.set({pairingToken:token});
  return state;
}
async function sendToApp(url,kind='auto') {
  if (!allowed(url)) throw Error('این نشانی قابل دانلود نیست.');
  const {pairingToken} = await credentials();
  const token=normalizeToken(pairingToken);
  if (!validToken(token)) throw Error(errorMessage[token?'invalid_format':'missing_code']);
  let r;
  try {
    r = await fetch(`${SERVICE}/add`,{
      method:'POST',headers:{'Content-Type':'application/json','X-Maher-Token':token},
      body:JSON.stringify({url,kind})
    });
  } catch (_) { throw Error('برنامه ماهر دانلود را اجرا کنید.'); }
  const data = await r.json();
  if (!r.ok || !data.ok) throw Error(errorMessage[data.error_code] || data.error || 'خطا در ارسال دانلود');
  return data;
}
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({id:'maher-link',title:'دانلود لینک با ماهر',contexts:['link']});
  chrome.contextMenus.create({id:'maher-media',title:'دانلود ویدیو با ماهر',contexts:['video','audio']});
  chrome.contextMenus.create({id:'maher-page',title:'دانلود ویدیوی این صفحه با ماهر',contexts:['page']});
});
chrome.contextMenus.onClicked.addListener(async (info,tab) => {
  const url=info.linkUrl||info.srcUrl||(info.menuItemId==='maher-page' ? tab?.url : null);
  if (!url) return;
  try {
    await sendToApp(url,info.menuItemId==='maher-page' ? 'media' : 'auto');
    await chrome.action.setBadgeBackgroundColor({color:'#1da98f'});
    await chrome.action.setBadgeText({text:'✓'});
  } catch (e) {
    await chrome.action.setBadgeBackgroundColor({color:'#d65a65'});
    await chrome.action.setBadgeText({text:'!'});
    console.warn('Maher Download Manager:',e.message);
  }
});
chrome.runtime.onMessage.addListener((message,sender,respond) => {
  if (message.action==='download') {
    sendToApp(message.url,message.kind||'auto').then(data=>respond({ok:true,...data}))
      .catch(e=>respond({ok:false,error:e.message}));
    return true;
  }
  if (message.action==='health') { health().then(respond);return true; }
  if (message.action==='pair' && sender?.url === chrome.runtime.getURL('popup.html')) {
    pair(message.token).then(respond).catch(() => respond(fail('offline')));
    return true;
  }
});
// Intercept only after successfully handing off to the desktop app.
// The user must opt in. This does NOT capture DRM, blob URLs, or browser-internal downloads.
const inFlight = new Set();
chrome.downloads.onCreated.addListener(async item => {
  const {autoCapture} = await credentials();
  if (!autoCapture || item.state !== 'in_progress' || !allowed(item.finalUrl||item.url)) return;
  if (inFlight.has(item.id)) return;
  inFlight.add(item.id);
  try {
    const url=item.finalUrl||item.url;
    const state=await health();
    if (!state.ok) return; // Browser must continue when desktop is unavailable.
    await sendToApp(url,media(url)?'media':'direct');
    // Browser download cancellation only AFTER app acknowledges the hand-off.
    await chrome.downloads.cancel(item.id);
    await chrome.downloads.erase({id:item.id});
  } catch(e) { console.warn('Maher auto capture skipped:',e.message); }
  finally { inFlight.delete(item.id); }
});
