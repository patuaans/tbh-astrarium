const assert=require('node:assert/strict');
const policy=require('../src/tbhastrarium/agents/cube.js');
const rules=require('./fixtures/synthesis-rules.json');
const planBatch=(items,s)=>policy.planBatch(items,s,rules);
const combineProgress=(items,s)=>policy.combineProgress(items,s,rules);
const {validateSettings}=policy;
const categories=(enabled=[0,2],grades=[0,1,2],tier=9)=>[0,1,2].map(category=>({category,enabled:enabled.includes(category),grades:[...grades],tier}));
const config={combine:true,combineCategories:categories(),combineExcludedIds:[],alchemy:false,gearMax:-1,materialMax:-1,protectedIds:[]};
const configFor=(category,grades=[0,1,2],tier=9)=>({...config,combineCategories:categories([category],grades,tier)});
const items=Array.from({length:9},(_,i)=>({id:String(i+1),itemId:300000+i,source:2,slot:200+i,type:2,grade:1,category:0,level:90,tier:9,blocked:false,chaotic:false,enchanted:false}));
assert.equal(planBatch(items,config).items.length,9);
assert.equal(planBatch(items.slice(0,8),config),null);
assert.deepEqual(combineProgress(items.slice(0,8),config),[{category:0,grade:1,tier:9,count:8}]);
for(const field of ['blocked','chaotic','enchanted'])assert.equal(planBatch(items.map((x,i)=>({...x,[field]:i===0})),config),null);
assert.equal(planBatch(items,{...config,protectedIds:[items[0].itemId]}),null);
assert.equal(planBatch(items,{...config,combineExcludedIds:[items[0].itemId]}),null);
assert.equal(planBatch(items.map(x=>({...x,itemId:777777})),{...config,combineExcludedIds:[777777]}),null,'All copies of an excluded item definition stay out of Combine');
assert.equal(planBatch(items.map((x,i)=>({...x,grade:i%2})),config),null);
assert.equal(planBatch(items.map(x=>({...x,category:1})),config),null);
assert.equal(planBatch(items.map(x=>({...x,source:5})),config),null);
assert.equal(planBatch(items.map(x=>({...x,slot:350})),config),null);
assert.equal(planBatch(items.map(x=>({...x,grade:9})),configFor(0,[8])),null);
assert.throws(()=>validateSettings(configFor(0,[9])));
assert.equal(planBatch(items,{...config,combine:false,alchemy:true}),null);
assert.equal(planBatch(items,{...config,alchemy:true,gearMax:1}).mode,'combine');
assert.equal(planBatch(items.slice(0,2),{...config,alchemy:true,gearMax:1}).mode,'alchemy');
assert.equal(planBatch(items.slice(0,2),{...config,combine:false,alchemy:true,gearMax:1,combineExcludedIds:[items[0].itemId]}).mode,'alchemy','Combine exclusions do not alter Auto Alchemy');
assert.equal(planBatch(items,{...config,combine:false,alchemy:true,gearMax:0}),null);
for(const category of [0,1,2])for(let grade=0;grade<=8;grade++){
  const matrix=items.map((x,i)=>({...x,id:`${category}:${grade}:${i}`,category,grade,source:i%2?1:2,slot:200+i}));
  const settings=configFor(category,[grade]);
  const batch=planBatch(matrix,settings);
  assert.equal(batch.items.length,9,`category ${category}, grade ${grade}`);
  assert.equal(batch.category,category);
  assert.ok(batch.items.every(x=>x.grade===grade));
}
console.log('PASS Cube grouping, nine-item threshold, grade/category filters, protected items, owned pages, Alchemy thresholds and ordering');
assert.throws(()=>validateSettings({...configFor(0,[0]),combineCategories:configFor(0,[0]).combineCategories.map(x=>x.category===0?{...x,tier:undefined}:x)}));
assert.throws(()=>validateSettings(configFor(0,[0],0)));
assert.throws(()=>validateSettings({...config,combineCategories:config.combineCategories.slice(0,2)}));
assert.throws(()=>validateSettings({...config,combineCategories:[...config.combineCategories,{...config.combineCategories[0]}]}));
assert.throws(()=>validateSettings({...config,combineExcludedIds:['777777']}));
assert.throws(()=>validateSettings({...config,combineExcludedIds:[0]}));
assert.equal(planBatch(items,configFor(0,[0,1,2],99)),null,'unknown tier never falls back');
const tooLow=items.map((x,i)=>({...x,tier:i===0?7:9}));
assert.equal(planBatch(tooLow,config),null,'8 eligible plus 1 low tier must wait');
assert.equal(planBatch(tooLow,configFor(0,[0,1,2],8)).tier,8,'lower tier must be explicitly selected');
assert.equal(planBatch(items.map(x=>({...x,tier:8,level:79})),config),null,'average below 80 must wait');
assert.equal(planBatch(items.map(x=>({...x,tier:8,level:80})),config).rule.tier,9);
assert.equal(planBatch([...tooLow,{...items[0],id:'extra',slot:210}],config).items.some(x=>x.tier<8),false);
for(const r of rules.filter(x=>x.count===9&&x.grade<9)) {
  const s=configFor(r.category,[r.grade],r.tier);
  const candidates=items.map(x=>({...x,type:r.category===2?1:2,category:r.category,grade:r.grade,tier:r.minTier,level:r.avg}));
  const batch=planBatch(candidates,s);
  assert.equal(batch?.tier,r.tier,`rule ${r.key}`);
  assert.ok(batch.rule.avg<=r.avg);
  assert.equal(planBatch(candidates.map(x=>({...x,tier:0})),s),null);
}
console.log('PASS every current synthesis rule, exact selected tier, mixed levels, average thresholds, missing/invalid tier and no downgrade fallback');
const gear=items.map((x,i)=>({...x,id:`g${i}`,category:0,grade:2}));
const accessories=items.map((x,i)=>({...x,id:`a${i}`,slot:20+i,category:1,grade:1,tier:8,level:80}));
const materials=items.map((x,i)=>({...x,id:`m${i}`,slot:40+i,type:1,category:2,grade:0,tier:1,level:0}));
const independent={...config,combineCategories:[
  {category:0,enabled:true,grades:[0,1,2],tier:9},
  {category:1,enabled:true,grades:[0,1],tier:8},
  {category:2,enabled:true,grades:[0,1],tier:7},
]};
assert.equal(planBatch([...gear,...accessories,...materials],independent).category,0);
assert.equal(planBatch(accessories,independent).tier,8);
assert.equal(planBatch(materials,independent).tier,7);
assert.equal(planBatch(gear.map(x=>({...x,grade:3})),independent),null,'Gear rarity is independent');
assert.equal(planBatch(materials.map(x=>({...x,grade:2})),independent),null,'Material rarity is independent');
assert.equal(planBatch(accessories.map(x=>({...x,grade:2})),independent),null,'Accessory rarity is independent');
console.log('PASS independent rarity and synthesis level for Gear, Accessories and Materials');
