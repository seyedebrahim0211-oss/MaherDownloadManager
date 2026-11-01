(() => {
  // Overlay for direct HTML5 URLs and public YouTube pages. DRM/blob are not decrypted.
  const control = document.createElement('button');
  control.textContent = '↓ دانلود این ویدیو با ماهر';
  control.type = 'button';
  control.style.cssText = [
    'position:fixed','z-index:2147483646','display:none','background:#15aaa7',
    'color:#061724','font:bold 12px sans-serif','padding:10px 14px',
    'border:0','border-radius:9px','cursor:pointer','box-shadow:0 5px 20px #0008'
  ].join(';');
  document.documentElement.append(control);
  let current = null, hideHandle;
  function source(video) {
    const candidates = [video.currentSrc, video.src,
      ...Array.from(video.querySelectorAll('source')).map(s => s.src)];
    return candidates.find(s => /^https?:\/\//i.test(s||'')) || ((/^(?:www\.|m\.)?youtube\.com$/.test(location.hostname)) ? location.href : null);
  }
  function hide() {control.style.display='none';current=null;}
  function locate(el) {
    const rect = el.getBoundingClientRect();
    control.style.top = `${Math.max(12,rect.top+10)}px`;
    control.style.left = `${Math.max(12,rect.right-195)}px`;
  }
  document.addEventListener('mouseover',event => {
    const node = event.target;
    if (!(node instanceof HTMLVideoElement)) return;
    const url=source(node);
    if (!url) return;
    clearTimeout(hideHandle);current=url;locate(node);control.style.display='block';
  },true);
  document.addEventListener('mouseout',event => {
    if (event.target instanceof HTMLVideoElement) hideHandle=setTimeout(hide,1000);
  },true);
  control.addEventListener('mouseenter',()=>clearTimeout(hideHandle));
  control.addEventListener('mouseleave',hide);
  control.addEventListener('click',() => {
    if (!current)return;
    control.textContent='در حال ارسال…';
    chrome.runtime.sendMessage({action:'download',url:current},result=>{
      control.textContent=(result && result.ok)?'✓ به صف اضافه شد':'خطا: '+(result?.error||'اتصال برقرار نشد');
      setTimeout(()=>{control.textContent='↓ دانلود این ویدیو با ماهر';hide();},2000);
    });
  });
})();
