// Stop first: this invalidates queued speech and any answer already in flight.
// A fresh server session prevents old turns reaching the model without DELETE.
export async function resetConversationContext(api, channels, {stopped, fresh, reconnect}) {
  await api.json('/audio/stop',{});
  stopped();
  const session=await api.json('/sessions',{});
  if(typeof session.id!=='string'||!session.id)throw new Error('Не удалось создать чистый разговор.');
  fresh(session.id);
  // Reopen SSE before listening again: its old queue must not refill the UI.
  await reconnect();
  const audio={loopback:false,microphone:false};
  const warnings=[];
  for(const {source,device_index} of channels){
    try{
      if(device_index===null||device_index===undefined)throw new Error('Устройство не выбрано.');
      const result=await api.json('/audio/start',{source,device_index});
      audio[source]=result.started===true;
      if(!audio[source])throw new Error('Прослушивание не запустилось.');
    }catch(error){warnings.push(`${source==='loopback'?'Звук системы':'Микрофон'}: ${error instanceof Error?error.message:String(error)}`);}
  }
  return {session_id:session.id,audio,warnings};
}
