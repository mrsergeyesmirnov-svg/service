/* Optional iPhone/Android voice input in Telegram. Text can always be edited. */
function voiceInputMarkup(){
 return '<div class="voice-input"><button type="button" class="voice-record" data-voice-record aria-pressed="false">'+
 '<span aria-hidden="true">🎙</span> Записать ответ голосом · до 30 сек</button>'+
 '<p class="muted" data-voice-status role="status">Запись будет распознана Yandex SpeechKit. Аудио не сохраняется. Проверь текст перед отправкой.</p>'+
 '</div>';
}
function bindVoiceInput(form){
 const button=form.querySelector('[data-voice-record]');
 const state=form.querySelector('[data-voice-status]');
 const target=form.querySelector('textarea[name="answer"]');
 if(!button||!target||!state)return;
 if(!window.MediaRecorder||!navigator.mediaDevices?.getUserMedia){
  button.hidden=true;
  state.textContent='На этом устройстве запись недоступна. Можно продиктовать текст с клавиатуры или написать вручную.';
  return;
 }
 let recorder=null,stream=null,clock=null;
 const stopTracks=()=>{if(stream){stream.getTracks().forEach(t=>t.stop());stream=null}};
 button.onclick=async()=>{
  if(recorder && recorder.state==='recording'){
   recorder.stop();
   return;
  }
  button.disabled=true;
  try{
   const mime=['audio/mp4','audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus']
      .find(x=>MediaRecorder.isTypeSupported(x));
   stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true}});
   recorder=new MediaRecorder(stream,mime?{mimeType:mime}:undefined);
   const chunks=[];
   recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
   recorder.onstop=async()=>{
    clearTimeout(clock);
    stopTracks();
    button.textContent='🎙 Записать ещё раз';
    button.setAttribute('aria-pressed','false');
    button.disabled=true;
    try{
     const type=(recorder.mimeType||mime||'').split(';')[0];
     const blob=new Blob(chunks,{type});
     if(blob.size>2_500_000)throw Error('Запись слишком большая. Попробуй говорить короче.');
     state.textContent='Распознаём голос, текст появится ниже…';
     const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),35000);
     try{
      const r=await fetch('/api/voice/transcribe',{method:'POST',signal:controller.signal,
        headers:{'Authorization':'Bearer '+token,'Content-Type':type},body:blob});
      const response=await r.json().catch(()=>({}));
      if(!r.ok)throw Error(response.detail||('SpeechKit: '+r.status));
      target.value=target.value.trim()?target.value.trim()+' '+response.text:response.text;
      target.dispatchEvent(new Event('input',{bubbles:true}));
      state.textContent='Голос распознан. Проверь и исправь текст, затем отправь на разбор ИИ.';
      target.focus();
     }finally{clearTimeout(timer)}
    }catch(err){
     state.textContent=err.name==='AbortError'?'Распознавание затянулось. Можно напечатать ответ.':
       (err.message||'Голос не распознан, введи текст вручную.');
    }finally{button.disabled=false;recorder=null}
   };
   recorder.onerror=()=>{
    clearTimeout(clock);stopTracks();
    button.textContent='🎙 Повторить запись';button.disabled=false;
    state.textContent='Микрофон недоступен, используй текстовый ввод.';
    recorder=null;
   };
   recorder.start(500);
   button.textContent='■ Завершить запись';
   button.setAttribute('aria-pressed','true');
   state.textContent='Идёт запись… максимум 30 секунд. Не называй личные данные гостей.';
   clock=setTimeout(()=>{if(recorder?.state==='recording')recorder.stop()},30000);
  }catch(err){
   stopTracks();
   state.textContent='Не удалось включить микрофон. Разреши доступ или напиши ответ текстом.';
  }finally{button.disabled=false}
 };
}
