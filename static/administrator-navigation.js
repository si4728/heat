(() => {
  const settings=document.getElementById('administrator-settings');
  if(!settings)return;
  document.addEventListener('click',event=>{
    if(settings.open && !settings.contains(event.target))settings.open=false;
  });
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape' && settings.open){settings.open=false;settings.querySelector('summary').focus();}
  });
})();
