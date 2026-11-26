const assert=require('assert/strict');
const fs=require('fs'),vm=require('vm');
require('./elo_discrepancy_estimator.js');
const m=globalThis.ChessCalibrationOffset;
const near=(a,b,tolerance=1e-7)=>assert(Math.abs(a-b)<tolerance,`${a} versus ${b}`);
const six=[0,1,0,1,.5,0].map((score,i)=>({target:i?1700:1699,rating:1398,score}));
const e=m.estimate(six);near(e.point,-243.3820526708);near(e.lower,-649.4233504149);near(e.upper,217.1635997382);
const seven=m.estimate([...six,{target:1550,rating:1398,score:1}]);near(seven.point,-281.21430912865);
assert.equal(m.estimate([]).point,null);
assert.equal(m.estimate([{target:1550,rating:1398,score:1}]).lower,-Infinity);
assert.equal(m.estimate([{target:1550,rating:1398,score:0}]).upper,Infinity);
near(m.estimate(six.map(r=>({...r,rating:r.rating+100}))).point,e.point+100);
near(m.meanAt(six,e.point),2.5/6);
assert(m.estimate([...six,...six]).upper-m.estimate([...six,...six]).lower<e.upper-e.lower);
// Exhaustive fixed-sample coverage checks, including draws and unequal means.
function coverage(probabilities){
 let failure=0;
 function walk(i,sum,prob){if(i===probabilities.length){const [lo,hi]=m.boundedScoreInterval(sum/probabilities.length,probabilities.length);const trueMean=probabilities.reduce((s,p)=>s+p[1]/2+p[2],0)/probabilities.length;if(trueMean<lo-1e-12||trueMean>hi+1e-12)failure+=prob;return;}for(let j=0;j<3;j++)walk(i+1,sum+j/2,prob*probabilities[i][j]);}
 walk(0,0,1);assert(failure<=.05+1e-12,`Coverage failure ${failure}`);
}
for(let n=1;n<=8;n++)for(const p of [.01,.05,.2,.5,.8,.95,.99])coverage(Array(n).fill([1-p,0,p]));
coverage([[.1,.8,.1],[.7,.2,.1],[.1,.1,.8],[.2,.4,.4],[.3,.6,.1],[.1,.6,.3]]);
// Data assembly consumes arbitrary browser log records, not a hardcoded game total.
const dummy={value:'1398',addEventListener(){},replaceChildren(){},append(){},textContent:''};
const context={ChessCalibrationOffset:m,document:{getElementById:()=>dummy,createElement:()=>({...dummy})},localStorage:{getItem:()=>null,setItem(){}},console};
vm.runInNewContext(fs.readFileSync('testing/results/strength_calibration/human-pilot-20261013-1700/elo_discrepancy_ui.js','utf8'),context);
const ui=context.ChessCalibrationDiscrepancyUI;
const schedule=[{game:1,session:1,relative_setting:1550,human_color:'White'},{game:2,session:1,relative_setting:1550,human_color:'Black'}];
let state={games:{1:{result:'win',version:'affected'},2:{result:'win',version:'affected'}},sessions:{1:{rating:'1398',time_control:'180+2'}},friends:[]};
let result=ui.assemble(state,schedule,{}, {},1398);
assert.equal(result.groups.find(g=>g.version==='affected').estimate.n,8); // six pilot + two logged; archived copy of row 2 omitted.
assert.equal(result.groups.find(g=>g.version==='corrected').estimate.n,0);
state.games[1].version='corrected';result=ui.assemble(state,schedule,{}, {},1398);
assert.equal(result.groups.find(g=>g.version==='corrected').estimate.n,1);
const archived=JSON.parse(fs.readFileSync('testing/results/strength_calibration/human-pilot-20261013-1700/discrepancy_archived_games.json','utf8'));
state={games:{1:{pgn:archived[0].pgn,result:'loss'}},sessions:{},friends:[]};
result=ui.assemble(state,schedule,{}, {},1398);assert.equal(result.records.length,7);assert(result.warnings.some(x=>x.includes('duplicate')));
state={games:{1:{result:'draw',version:'corrected'}},sessions:{1:{rating:'1398',time_control:'600+5'}},friends:[{id:1,name:'Rapid friend',preset:'generic',rating:'875',time_control:'900+10',games:{1:{result:'loss',version:'corrected'}}}]};
result=ui.assemble(state,schedule,{order:[{game:1,relative_setting:1000,human_color:'White'}]},{username:'pktaces67'},1398);
assert.equal(result.groups.find(g=>g.playerId==='main'&&g.tc==='600+5').estimate.n,1);
assert.equal(result.groups.find(g=>g.player==='Rapid friend').tc,'900+10');
assert.equal(result.groups.find(g=>g.playerId==='main'&&g.tc==='180+2'&&g.version==='corrected').estimate.n,0);
delete state.friends[0].rating;result=ui.assemble(state,schedule,{order:[{game:1,relative_setting:1000,human_color:'White'}]},{username:'pktaces67'},1398);assert(result.warnings.some(x=>x.includes('valid rating')));
console.log('Passed: mixed targets, draws, open bounds, translation, finite-sample coverage, live log results, version/control separation, per-player ratings and duplicate suppression.');
