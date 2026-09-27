'use strict';
let csrf = '', offset = 0, config = {};
const $ = s => document.querySelector(s);
const modes = {audio:'Áudio', video:'Vídeo', av:'Áudio + vídeo'};
const states = {stopped:'Parada', paused:'Pausada', starting:'Iniciando', recording:'Gravando', waiting:'Aguardando recuperação'};
const cloud = {not_selected:'Sem cópia selecionada', pending:'Cópia pendente', copied:'Copiado para a pasta do OneDrive · upload não confirmado', deleted:'Cópia removida pela retenção da nuvem'};
const bytes = n => {if(n==null)return 'Indisponível';const unit=n>=1024**3?['GiB',1024**3]:n>=1024**2?['MiB',1024**2]:['KiB',1024];return (n/unit[1]).toLocaleString('pt-BR',{maximumFractionDigits:2})+' '+unit[0];};
function message(s=''){ $('#message').textContent=s; }
async function api(path, data){
 const r=await fetch(path,{method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:data===undefined?undefined:JSON.stringify(data)});
 let result; try{result=await r.json();}catch{result={};}
 if(r.status===401){showLogin();throw Error('Entre novamente para continuar.');}
 if(!r.ok) throw Error(result.error||`Operação recusada (${r.status}).`);
 return result;
}
function showLogin(){csrf='';$('#dashboard').hidden=true;$('#logout').hidden=true;$('#login').hidden=false;$('#player').pause();$('#player').removeAttribute('src');}
function act(fn){return async e=>{e?.preventDefault();try{await fn(e);}catch(err){message(err.message);}};}
$('#login').onsubmit=act(async()=>{const r=await api('/api/login',{password:$('#password').value});$('#password').value='';csrf=r.csrf;await enter();});
$('#logout').onclick=act(async()=>{await api('/api/logout',{});showLogin();});
async function enter(){ $('#login').hidden=true;$('#dashboard').hidden=false;$('#logout').hidden=false;message();await loadConfig();await refresh(); }
for(const b of document.querySelectorAll('[data-command]'))b.onclick=act(async()=>{await api('/api/control',{command:b.dataset.command});message('Comando enviado.');await refresh();});
async function loadConfig(){
 config=await api('/api/config');const ds=(await api('/api/devices')).devices;
 for(const [field,kind] of [['camera','video'],['microphone','audio']]){
  const select=$(`[name=${field}]`);select.replaceChildren();select.add(new Option('Selecione um dispositivo',''));
  for(const d of ds.filter(d=>d.kind===kind))select.add(new Option(d.name,d.name));
  if(config[field]&&!ds.some(d=>d.kind===kind&&d.name===config[field]))select.add(new Option(config[field]+' (indisponível)',config[field]));
 }
 for(const [k,v] of Object.entries(config)){const el=$(`[name=${k}]`);if(!el)continue;if(el.type==='checkbox')el.checked=v;else el.value=Array.isArray(v)?v.join(','):v;}
 $('#remote-link').textContent=config.remote_enabled?'Endereço privado: https://'+config.remote_host:'Acesso remoto desativado.';
}
function values(){const data={};for(const [k,v] of Object.entries(config)){const el=$(`[name=${k}]`);if(!el)continue;data[k]=el.type==='checkbox'?el.checked:el.type==='number'?Number(el.value):Array.isArray(v)?el.value.split(',').map(s=>s.trim()).filter(Boolean).map(s=>k==='cloud_hours'?Number(s):s):el.value;}return data;}
$('#config').onsubmit=act(async()=>{await api('/api/config',values());message('Configurações salvas.');await loadConfig();await refresh();});
$('#import').onchange=act(async e=>{const f=e.target.files[0];if(!f)return;if(f.size>65536)throw Error('Arquivo muito grande.');await api('/api/config',JSON.parse(await f.text()));await loadConfig();message('Configurações importadas sem credenciais.');e.target.value='';});
for(const b of document.querySelectorAll('[data-folder]'))b.onclick=act(async()=>{const r=await api('/api/folder',{});if(r.path)$(`[name=${b.dataset.folder}]`).value=r.path;});
$('#serve').onclick=act(async()=>{const r=await api('/api/remote/serve',{});message(r.detail||(r.ok?'Serve configurado.':'Não foi possível configurar Serve.'));});
$('#retry').onclick=act(async()=>{await api('/api/cloud/retry',{});message('Fila liberada para nova tentativa.');});
$('#options').onclick=act(async()=>{let text='';for(const [field,kind] of [['camera','video'],['microphone','audio']]){const name=$(`[name=${field}]`).value;if(name){const r=await api('/api/device-options?'+new URLSearchParams({name,kind}));text+=r.options+'\n';}}$('#device-options').textContent=text;});
$('#change-password').onsubmit=act(async()=>{await api('/api/password',{password:$('#new-password').value});$('#new-password').value='';showLogin();message('Senha alterada. Todas as sessões foram revogadas.');});
$('#filter').onclick=act(async()=>{offset=0;await recordings();});
$('#next').onclick=act(async()=>{offset+=100;await recordings();});
$('#previous').onclick=act(async()=>{offset=Math.max(0,offset-100);await recordings();});
async function recordings(){
 const q=new URLSearchParams({offset,mode:$('#filter-mode').value});for(const k of ['from','to'])if($('#'+k).value)q.set(k,new Date($('#'+k).value).toISOString());
 const result=await api('/api/recordings?'+q);const box=$('#recordings');box.replaceChildren();
 if(!result.items.length)box.textContent='Nenhuma gravação neste período.';
 for(const r of result.items){
  const row=document.createElement('article');row.className='recording';const info=document.createElement('div');const title=document.createElement('b');title.textContent=new Date(r.created*1000).toLocaleString('pt-BR')+' · '+modes[r.mode];info.append(title);
  const detail=document.createElement('p');detail.textContent=`${Math.round(r.duration)} s · ${bytes(r.size)} · ${r.local_state==='local'?'Gravado localmente':'Local removido'} · ${cloud[r.cloud_state]}`;info.append(detail);
  if(r.cloud_error){const err=document.createElement('p');err.textContent=r.cloud_error;info.append(err);}const actions=document.createElement('div');actions.className='actions';
  if(r.local_state==='local'){const play=document.createElement('button');play.textContent='Reproduzir';play.onclick=()=>{const p=$('#player');p.hidden=false;p.src='/api/recordings/'+r.id+'/media';p.play().catch(()=>message('Toque em reproduzir no player.'));p.scrollIntoView({block:'center'});};actions.append(play);const download=document.createElement('a');download.className='button';download.textContent='Baixar';download.href='/api/recordings/'+r.id+'/media?download=1';actions.append(download);}
  const keep=document.createElement('button');keep.textContent=r.preserved?'Preservado ✓':'Preservar';keep.onclick=act(async()=>{await api('/api/recordings/'+r.id+'/preserve',{preserved:!r.preserved});await recordings();});actions.append(keep);row.append(info,actions);box.append(row);
 }
 $('#previous').disabled=offset===0;$('#next').disabled=result.items.length<100;$('#page').textContent='Página '+(offset/100+1);
}
async function refresh(){
 const s=await api('/api/status');$('#state').textContent=states[s.capture.state]||s.capture.state;$('#capture-detail').textContent=`Selecionado: ${modes[config.mode]}. ${s.capture.actual_mode?'Captura: '+modes[s.capture.actual_mode]+'. ':''}${s.capture.error||''}`;
 $('#free').textContent=bytes(s.space.free);$('#daily').textContent=bytes(s.space.estimated_daily);$('#monthly').textContent=bytes(s.space.estimated_monthly);$('#pending').textContent=bytes(s.space.pending_bytes);
 $('#cloud-space').textContent='Disco da pasta OneDrive: '+bytes(s.space.cloud_disk_free)+'. '+s.space.cloud_quota+'.'+(s.space.cloud_capacity_insufficient?' Espaço insuficiente para a fila!':'');
 const events=$('#events');events.replaceChildren();for(const e of s.events){const p=document.createElement('div');p.className='event';p.textContent=new Date(e.at*1000).toLocaleString('pt-BR')+' · '+e.level+' · '+e.message;events.append(p);}
 await recordings();
}
setInterval(()=>{if(csrf)refresh().catch(e=>message(e.message));},6000);
(async()=>{try{csrf=(await api('/api/session')).csrf;await enter();}catch{showLogin();message();}})();
