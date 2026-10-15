(() => {
  const dialog=document.getElementById('image-viewer');
  const image=document.getElementById('viewer-image');
  document.querySelectorAll('.image-open').forEach(button=>button.addEventListener('click',()=>{
    image.src=button.dataset.image||'';
    image.alt=button.dataset.title||'原始素材';
    document.getElementById('viewer-title').textContent=button.dataset.title||'';
    document.getElementById('viewer-caption').textContent=button.dataset.caption||'';
    document.getElementById('viewer-original').href=image.src;
    document.getElementById('viewer-source').href=button.dataset.source||'#';
    dialog.showModal();
  }));
  document.getElementById('viewer-close')?.addEventListener('click',()=>dialog.close());
  dialog?.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
  const video=document.getElementById('own-video');
  const poster=document.querySelector('.film-start');
  const play=async (seconds=0)=>{
    if(!video)return;
    poster.hidden=true;video.hidden=false;
    try{
      if(video.readyState===0){video.preload='auto';await new Promise((resolve,reject)=>{video.addEventListener('loadedmetadata',resolve,{once:true});video.addEventListener('error',()=>reject(new Error('Video unavailable')),{once:true});video.load();});}
      video.currentTime=seconds;
      await video.play();
    }catch(_error){video.hidden=true;poster.hidden=false;poster.setAttribute('aria-label','点击重新播放本期早报视频');}
  };
  poster?.addEventListener('click',()=>play());
  document.querySelectorAll('[data-seek]').forEach(button=>button.addEventListener('click',event=>{
    event.preventDefault();
    document.querySelector('.chapter-picker')?.removeAttribute('open');
    play(Number(button.dataset.seek)||0);
    document.querySelector('.film')?.scrollIntoView({behavior:'smooth',block:'center'});
  }));
  document.addEventListener('click',event=>{
    const picker=document.querySelector('.chapter-picker');
    if(picker?.open&&!picker.contains(event.target))picker.removeAttribute('open');
  });
})();
