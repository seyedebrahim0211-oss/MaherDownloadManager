const $=id=>document.getElementById(id);
const setStatus=(s,error=false)=>{$('status').textContent=s;$('status').style.color=error?'#f37983':'#62d9a9';};
async function submit(url,kind='auto'){
  if(!url)return setStatus('پیوند را وارد کنید.',true);
  setStatus('در حال ارسال…');
  try{const res=await chrome.runtime.sendMessage({action:'download',url,kind});
    if(!res?.ok)throw Error(res?.error||'خطای اتصال');
    setStatus('✓ به صف دانلود اضافه شد: '+res.filename);
  }catch(e){setStatus(e.message,true)}
}
(async()=>{
  const {pairingToken,autoCapture}=await chrome.storage.local.get(['pairingToken','autoCapture']);
  $('token').value=pairingToken||'';$('auto').checked=!!autoCapture;
  const res=await chrome.runtime.sendMessage({action:'health'});
  setStatus(res?.ok?'✓ برنامه متصل است':(res?.error||'برنامه را اجرا کنید.'),!res?.ok);
})();
$('pair').onclick=async()=>{
  await chrome.storage.local.set({pairingToken:$('token').value.trim()});
  const res=await chrome.runtime.sendMessage({action:'health'});
  setStatus(res?.ok?'✓ اتصال برقرار شد':(res?.error||'اتصال ناموفق'),!res?.ok);
};
$('auto').onchange=async()=>{await chrome.storage.local.set({autoCapture:$('auto').checked});setStatus($('auto').checked?'دریافت خودکار فعال شد.':'دریافت خودکار غیرفعال شد.');};
$('send').onclick=()=>submit($('url').value.trim());
$('sendMedia').onclick=()=>submit($('media').value,'media');
chrome.tabs.query({active:true,currentWindow:true},async tabs=>{
  const tab=tabs[0]; if(!tab?.id)return;
  $('sendPage').onclick=()=>submit(tab.url,'media');
  try {
    const [result]=await chrome.scripting.executeScript({target:{tabId:tab.id},func:()=>{
      const nodes=[...document.querySelectorAll('video,audio,source')];
      const urls=nodes.flatMap(n=>[n.currentSrc,n.src,...[...n.querySelectorAll?.('source')||[]].map(s=>s.src)]);
      return [...new Set(urls.filter(x=>typeof x==='string'&&/^https?:\/\//i.test(x)))].slice(0,50);
    }});
    const select=$('media');select.replaceChildren();
    if(!result?.result?.length){select.add(new Option('رسانه مستقیمی یافت نشد',''));return;}
    for(const url of result.result){select.add(new Option(url.length>55?url.slice(0,55)+'…':url,url));}
  }catch(e){$('media').replaceChildren(new Option('برای این صفحه دسترسی وجود ندارد',''));}
});
