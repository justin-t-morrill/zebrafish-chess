/* Offline page navigation and transfer from the old file's browser storage. */
(()=>{
'use strict';
const key='chess2-human-confirmation-20261013-v1',ratingKey='chess2-discrepancy-reference-rating-v1';
function read(k){try{return localStorage.getItem(k);}catch(e){return null;}}
function valid(v){return v?.schema==='chess2-human-log-v1'&&v.schedule_id==='confirmation-20261013-1700';}
let state=null,reference=read(ratingKey),problem='';
try{const stored=JSON.parse(read(key)||'null');if(valid(stored))state=stored;}catch(e){problem='Stored log could not be read; use your JSON backup.';}
const params=new URLSearchParams(location.hash.slice(1));
if(params.has('log')){
 try{
  const payload=JSON.parse(params.get('log'));
  if(payload.schema!=='chess2-report-transfer-v1'||!valid(payload.log))throw Error('Unrecognized transferred log.');
  if(!state||!state.updated_utc||!payload.log.updated_utc||payload.log.updated_utc>=state.updated_utc){state=payload.log;reference=payload.reference??reference;}
  try{localStorage.setItem(key,JSON.stringify(state));if(reference!==null)localStorage.setItem(ratingKey,reference);}catch(e){problem='Browser storage is unavailable. Download a backup before closing the page.';}
  const section=params.get('section')||'';history.replaceState(null,'',location.pathname+(section?'#'+encodeURIComponent(section):''));
 }catch(e){problem='Log transfer failed: '+e.message+' Your existing saved log was left intact.';}
}
globalThis.ChessReportBridge={state,get reference(){return reference;},read};
document.addEventListener('click',e=>{
 const link=e.target.closest('a[data-portal-link]');if(!link)return;
 let latest=globalThis.ChessHumanLog?.getState()||globalThis.ChessReportBridge.state;
 try{const stored=JSON.parse(read(key)||'null');if(valid(stored)&&(!latest||stored.updated_utc>latest.updated_utc))latest=stored;}catch(e){}
 if(!latest)return;
 if(!link.dataset.originalHref)link.dataset.originalHref=link.getAttribute('href');
 const dest=new URL(link.dataset.originalHref,location.href),snapshot=JSON.stringify({schema:'chess2-report-transfer-v1',log:latest,reference:read(ratingKey)??reference});
 if(snapshot.length>1500000){e.preventDefault();alert('This log is too large to transfer in a local link. Download its JSON backup, then open the destination and import the backup on Game log.');return;}
 const hash=new URLSearchParams({log:snapshot});if(dest.hash)hash.set('section',decodeURIComponent(dest.hash.slice(1)));dest.hash=hash.toString();link.href=dest.href;
});
document.addEventListener('DOMContentLoaded',()=>{
 const n=document.getElementById('portal-storage-note');if(n)n.textContent=problem||'Local pages carry your saved log when you follow their navigation links. Download a JSON backup regularly.';
 const count=document.getElementById('portal-saved-count');if(count&&state){const all=[...Object.values(state.games||{}),...(state.friends||[]).flatMap(f=>Object.values(f.games||{})),...(state.extras||[])];count.textContent=all.filter(r=>r.result||r.pgn).length+' browser log entries found. Open Game log from here to carry them across.';}
 const backup=document.getElementById('portal-backup');if(backup)backup.addEventListener('click',()=>{const current=globalThis.ChessHumanLog?.getState()||globalThis.ChessReportBridge.state;if(!current){alert('No browser log was found at this address. You can import an existing JSON backup on Game log.');return;}const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(current,null,2)],{type:'application/json'}));a.href=url;a.download='human-calibration-migration-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
 if(location.hash&&!location.hash.startsWith('#log=')){try{document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView();}catch(e){}}
});
})();
