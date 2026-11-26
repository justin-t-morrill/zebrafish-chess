/* A separate prospective log: earlier pilots never fill its 48 slots. */
(()=>{
'use strict';
const api=globalThis.ChessHumanLog,plan=api.activeConfirmationPlan;
if(!plan)return;
const root=document.getElementById('cf-sessions');
function el(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function summary(){const state=api.getState(),all=Object.values(state.confirmation_v2.games),done=all.filter(r=>r.result).length;document.getElementById('cf-summary').textContent=done+' / 48 fresh confirmation results logged. The 12 corrected pilot games remain separate; none fills this block.';}
function render(){
 root.replaceChildren();const state=api.getState();
 for(let n=1;n<=8;n++){const items=plan.items.filter(i=>i.session===n),details=el('details'),title=el('summary','Session '+n+' · new games '+items[0].game+'–'+items.at(-1).game),box=el('div');details.className='fold';box.className='hc-session';
  box.append(api.metadata(state.confirmation_v2.sessions[n],false),api.gameTable(items,state.confirmation_v2.games));details.append(title,box);root.append(details);
 }
 summary();
}
addEventListener('chess-log-rendered',render);addEventListener('chess-log-updated',summary);render();
})();
