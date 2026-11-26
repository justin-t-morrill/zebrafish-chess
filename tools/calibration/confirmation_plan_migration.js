/* Preserve records when the user changes a prepared confirmation bracket. */
(()=>{
'use strict';
function migrate(value,active){
 const prior=value?.confirmation_v2;
 if(!active||!prior?.plan_id||prior.plan_id===active.plan_id)return value;
 const old=(globalThis.ChessReportData?.previousConfirmationPlans||[]).find(p=>p.plan_id===prior.plan_id);
 if(!old)throw Error('Unrecognized earlier confirmation plan. Keep this backup intact for review.');
 const copy=JSON.parse(JSON.stringify(value));copy.extras=copy.extras||[];
 const history=copy.confirmation_history||[];
 if(!history.some(h=>h.plan_id===prior.plan_id))history.push({plan_id:prior.plan_id,plan:old,original_record:JSON.parse(JSON.stringify(prior))});
 let moved=0;
 for(const item of old.items){
  const r=prior.games?.[item.game];if(!r||!Object.values(r).some(v=>v!==''&&v!==null&&v!==false))continue;
  const meta=prior.sessions?.[item.session]||{},id='retired-'+prior.plan_id+'-'+item.game;
  if(copy.extras.some(e=>e.id===id))continue;
  copy.extras.push({...r,id,player:'thecarrotgod',player_id:'main',relative_setting:Number(r.actual_target)||item.relative_setting,human_color:item.human_color,
   human_rating:r.human_rating||meta.rating||'',time_control:r.time_control||meta.time_control||item.time_control,date:r.date||meta.date||'',
   notes:[r.notes,meta.notes,'Preserved from earlier confirmation bracket '+old.settings.join('/')+', session '+item.session+', game '+item.game+'. Earlier exploratory record; does not fill the revised block.'].filter(Boolean).join('\n')});moved++;
 }
 copy.confirmation_history=history;copy.confirmation_v2={plan_id:active.plan_id,sessions:{},games:{}};
 copy.updated_utc=new Date().toISOString();globalThis.ChessConfirmationMigration.lastMigration={from:prior.plan_id,to:active.plan_id,moved};
 return copy;
}
globalThis.ChessConfirmationMigration={migrate,lastMigration:null};
})();
