const SERVICE = 'http://127.0.0.1:17691';
const allowed = url => /^https?:\/\//i.test(url || '') || /^ftp:\/\//i.test(url || '');
const media = url => /(?:youtube\.com|youtu\.be|\.m3u8(?:\?|$)|\.mpd(?:\?|$))/i.test(url || '');
const credentials = async () => (await chrome.storage.local.get(['pairingToken','autoCapture']));
async function health() {
  const {pairingToken} = await credentials();
  if (!pairingToken) return {ok:false,error:'کد اتصال را از برنامه ویندوز کپی کنید.'};
  try {
    const r = await fetch(`${SERVICE}/health`,{headers:{'X-Maher-Token':pairingToken}});
    return r.ok ? await r.json() : {ok:false,error:'کد اتصال نامعتبر است.'};
  } catch (_) { return {ok:false,error:'برنامه ویندوز اجرا نشده است.'}; }
}
async function sendToApp(url,kind='auto') {
  if (!allowed(url)) throw Error('این نشانی قابل دانلود نیست.');
  const {pairingToken} = await credentials();
  if (!pairingToken) throw Error('ابتدا در افزونه، کد اتصال برنامه را وارد کنید.');
  let r;
  try {
    r = await fetch(`${SERVICE}/add`,{
      method:'POST',headers:{'Content-Type':'application/json','X-Maher-Token':pairingToken},
      body:JSON.stringify({url,kind})
    });
  } catch (_) { throw Error('برنامه ماهر دانلود را اجرا کنید.'); }
  const data = await r.json();
  if (!r.ok || !data.ok) throw Error(data.error || 'خطا در ارسال دانلود');
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
