/* Conditional personal offset estimate; finite-sample bounded-score CI. */
(()=>{
"use strict";
function expectedHumanScore(record,delta){
 const exponent=(record.target+delta-record.rating)/400;
 return 1/(1+Math.pow(10,exponent));
}
function meanAt(records,delta){return records.reduce((sum,r)=>sum+expectedHumanScore(r,delta),0)/records.length;}
function offsetAtMean(records,p){
 if(p<=0)return Infinity;if(p>=1)return -Infinity;
 let low=-20000,high=20000;
 for(let i=0;i<90;i++){const mid=(low+high)/2;if(meanAt(records,mid)>p)low=mid;else high=mid;}
 return(low+high)/2;
}
function kl(q,p){
 if(p<=0)return q===0?0:Infinity;
 if(p>=1)return q===1?0:Infinity;
 return(q===0?0:q*Math.log(q/p))+(q===1?0:(1-q)*Math.log((1-q)/(1-p)));
}
function boundedScoreInterval(q,n,alpha=.05){
 const threshold=Math.log(2/alpha)/n;
 if(q===0)return[0,1-Math.exp(-threshold)];
 if(q===1)return[Math.exp(-threshold),1];
 let outside=0,inside=q;
 for(let i=0;i<90;i++){const p=(outside+inside)/2;if(kl(q,p)>threshold)outside=p;else inside=p;}
 const lower=(outside+inside)/2;inside=q;outside=1;
 for(let i=0;i<90;i++){const p=(outside+inside)/2;if(kl(q,p)>threshold)outside=p;else inside=p;}
 return[lower,(outside+inside)/2];
}
function estimate(input,alpha=.05){
 const records=input.filter(r=>Number.isFinite(r.target)&&r.target>=600&&r.target<=2600&&Number.isFinite(r.rating)&&r.rating>=100&&r.rating<=4000&&[0,.5,1].includes(r.score));
 if(!records.length)return{n:0,point:null,lower:null,upper:null,score:0,alpha};
 const score=records.reduce((s,r)=>s+r.score,0),q=score/records.length;
 const[meanLower,meanUpper]=boundedScoreInterval(q,records.length,alpha);
 return{n:records.length,score,meanScore:q,point:offsetAtMean(records,q),lower:offsetAtMean(records,meanUpper),upper:offsetAtMean(records,meanLower),meanLower,meanUpper,alpha};
}
function header(pgn,name){const m=(pgn||"").match(new RegExp("\\["+name+'\\s+"([^"\\r\\n]*)"\\s*\\]',"i"));return m?m[1]:null;}
function isEngine(name){return /^(?:Engine\b|Zebrafish(?:\s|\())/i.test(name||'');}
function engineTarget(name){return (name||'').match(/\((\d+)\s+(?:strength|target)\)/i)?.[1]||null;}
function engineBuild(pgn){
 if(inferVersion(pgn)==='web')return ['ZebrafishBuild','StrengthSystem','EngineSHA256','StrengthAdapterSHA256','RatingConversionSHA256','OpeningBookSHA256','EngineThreads','EngineHashMB','OwnBook','UseNNUE','SearchDepth','TargetScale'].map(k=>header(pgn,k)||'unknown').join('/');
 return header(pgn,'GUIBuild')||'';
}
function equivalentWeb(pgn){
 const data=globalThis.ChessReportData,manifests=data?.equivalentWebManifests||[data?.equivalentWebManifest];
 return manifests.some(m=>!!m&&header(pgn,'ZebrafishBuild')==='local-web-calibrated-native-v1'&&header(pgn,'StrengthSystem')===m.strength_system&&header(pgn,'GUIBuild')===m.gui_build&&header(pgn,'EngineSHA256')===m.engine_sha256&&header(pgn,'StrengthAdapterSHA256')===m.transport_sha256&&header(pgn,'CalibrationMappingSHA256')===m.mapping_sha256&&header(pgn,'GUISourceSHA256')===m.gui_source_sha256&&header(pgn,'NNUESHA256')===m.nnue_sha256&&header(pgn,'OpeningBookSHA256')===m.book_sha256&&header(pgn,'EngineThreads')==='1'&&header(pgn,'EngineHashMB')==='64'&&header(pgn,'OwnBook')==='true'&&header(pgn,'UseNNUE')==='true'&&header(pgn,'SearchDepth')==='0'&&header(pgn,'RatingConversionSHA256')==='none');
}
function protocolDeviation(pgn){return header(pgn,'SetUp')==='1'||/takeback|engine-assisted|pause/i.test(header(pgn,'ProtocolChanges')||'');}
function inferVersion(pgn){
 if(equivalentWeb(pgn))return 'corrected';
 if(header(pgn,'ZebrafishBuild')||[header(pgn,'White'),header(pgn,'Black')].some(n=>/^Zebrafish(?:\s|\()/i.test(n||'')))return 'web';
 const build=header(pgn,"GUIBuild");
 if(build==="relative-20261013-gui-worker-seed-v1")return"corrected";
 if(build)return"other";
 if(/Engine 8\.3 \(\d+ strength\)/.test(pgn||"")&&header(pgn,"Event")==="C Engine Game")return"affected";
 return"";
}
function fingerprint(pgn){return(pgn||"").replace(/\r/g,"").replace(/\s+/g,"");}
globalThis.ChessCalibrationOffset={estimate,expectedHumanScore,meanAt,offsetAtMean,boundedScoreInterval,kl,header,isEngine,engineTarget,engineBuild,equivalentWeb,protocolDeviation,inferVersion,fingerprint};
})();
