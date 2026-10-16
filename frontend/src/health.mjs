export function describeHealth(health) {
  if (!health.ready) return {ready:false,status:'Ожидание локального сервиса'};
  const errors=health.warmup_errors;
  if (errors && (Array.isArray(errors)?errors.length:Object.keys(errors).length)) return {ready:false,status:'Ошибка подготовки моделей — подробности в настройках'};
  if (health.warming_up || !health.asr?.loaded || !health.ollama?.installed) return {ready:false,status:'Модели загружаются…'};
  if (!health.ollama?.available) return {ready:false,status:'Ollama недоступна — проверьте настройки'};
  return {ready:true,status:'Локальные модели готовы'};
}
