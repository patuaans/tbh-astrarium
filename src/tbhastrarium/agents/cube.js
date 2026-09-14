'use strict';

function validateSettings(s) {
  if (!s || !Array.isArray(s.combineCategories) || !Array.isArray(s.protectedIds)||!Array.isArray(s.combineExcludedIds)) throw Error('Invalid Cube settings');
  const seen=new Set();
  for (const x of s.combineCategories) {
    if(!x||![0,1,2].includes(x.category)||seen.has(x.category)||typeof x.enabled!=='boolean'||!Array.isArray(x.grades))throw Error('Invalid category settings');
    seen.add(x.category);
    for(const grade of x.grades)if(!Number.isInteger(grade)||grade<0||grade>8)throw Error('Cosmic cannot be combined');
    if(x.enabled&&(!x.grades.length||!Number.isInteger(x.tier)||x.tier<1))throw Error('Choose rarity and synthesis level for every enabled category');
  }
  if(seen.size!==3)throw Error('All three category settings are required');
  for (const x of [s.gearMax,s.materialMax]) if (!Number.isInteger(x)||x < -1||x>9) throw Error('Invalid Alchemy grade');
  for(const x of s.combineExcludedIds)if(!Number.isInteger(x)||x<=0)throw Error('Invalid excluded item');
  if(s.combine&&!s.combineCategories.some(x=>x.enabled))throw Error('Enable at least one Auto Combine category');
  return JSON.parse(JSON.stringify(s));
}
function eligible(x, s) {
  return [1,2].includes(x.source) && (x.source!==2 || x.slot<343) &&
    !x.blocked && !x.chaotic && !x.enchanted && !s.protectedIds.includes(x.itemId) &&
    [1,2].includes(x.type) && Number.isInteger(x.grade) && x.grade>=0 && x.grade<=9;
}
function combineEligible(x,s) {
  return eligible(x,s)&&!s.combineExcludedIds.includes(x.itemId);
}
function categorySetting(s,category) {
  return s.combineCategories.find(x=>x.category===category&&x.enabled)||null;
}
function matchingRules(s,rules,category,grade) {
  const setting=categorySetting(s,category);
  return setting?rules.filter(r=>r.tier===setting.tier&&r.category===category&&r.grade===grade&&r.count===9):[];
}
function batchRule(items,s,rules) {
  if(items.length!==9)return null;
  const first=items[0],setting=categorySetting(s,first.category);
  if(!s.combine||!setting||!setting.grades.includes(first.grade)||
      !items.every(x=>combineEligible(x,s)&&x.category===first.category&&x.grade===first.grade))return null;
  const tier=Math.min(...items.map(x=>x.tier)),average=items.reduce((v,x)=>v+x.level,0)/9;
  return matchingRules(s,rules,first.category,first.grade)
    .filter(r=>tier>=r.minTier&&average>=r.avg).sort((a,b)=>b.avg-a.avg)[0]||null;
}
function combineProgress(items,s,rules=[]) {
  if(!s.combine)return [];
  const groups=new Map();
  for(const x of items.filter(x=>combineEligible(x,s))) {const setting=categorySetting(s,x.category);if(setting&&setting.grades.includes(x.grade)&&x.grade<9) {
    if(!matchingRules(s,rules,x.category,x.grade).some(r=>x.tier>=r.minTier))continue;
    const k=x.category+':'+x.grade;
    if(!groups.has(k))groups.set(k,{category:x.category,grade:x.grade,tier:setting.tier,count:0});
    groups.get(k).count++;
  }}
  return [...groups.values()].sort((a,b)=>b.count-a.count||a.category-b.category||a.grade-b.grade);
}
function planBatch(items,s,rules=[]) {
  const available=items.filter(x=>eligible(x,s));
  if(s.combine) {
    const groups=new Map();
    for(const x of available) {const setting=categorySetting(s,x.category);if(combineEligible(x,s)&&setting&&setting.grades.includes(x.grade)&&x.grade<9) {
      const k=x.category+':'+x.grade;
      if(!groups.has(k))groups.set(k,[]); groups.get(k).push(x);
    }}
    for(const group of groups.values()) if(group.length>=9) {
      group.sort((a,b)=>b.level-a.level||a.source-b.source||a.slot-b.slot);
      // Some rules require a higher minimum material tier as well as an
      // average level. Try every rule of ONLY the user's selected tier.
      for(const r of matchingRules(s,rules,group[0].category,group[0].grade)) {
        const selected=group.filter(x=>x.tier>=r.minTier).slice(0,9);
        const rule=batchRule(selected,s,rules);
        if(rule)return {mode:'combine',recipe:1,tier:categorySetting(s,group[0].category).tier,category:group[0].category,rule,items:selected};
      }
    }
  }
  if(s.alchemy) {
    const candidates=available.filter(x=>x.grade <= (x.type===2?s.gearMax:s.materialMax));
    if(candidates.length)return {mode:'alchemy',recipe:0,items:candidates.slice(0,9)};
  }
  return null;
}
function cubeUiPolicy(active,transaction) {
  if(!active)return 'run';
  return transaction&&transaction.submitted?'finish_submitted':'yield';
}

function startCubeAgent() {
  const base=Process.getModuleByName('GameAssembly.dll').base,nil=ptr(0);
  const fn=(r,ret,args)=>new NativeFunction(base.add(r),ret,[...args,'pointer']);
  const getItem=fn(0x911260,'pointer',['int','int']);
  const getId=fn(0x96ad30,'uint64',['pointer']);
  const cubeId=fn(0x9a9aa0,'uint64',['pointer']);
  const blocked=fn(0x96ad90,'bool',['pointer']);
  const chaotic=fn(0x96ad60,'bool',['pointer']);
  const itemTier=fn(0x96af00,'int',['pointer']);
  const recipeTier=fn(0x9b6a90,'int',['pointer']);
  const recipeUnlocked=fn(0x9b6ad0,'bool',['pointer']);
  const selectSubRecipe=fn(0x9094e0,'bool',['pointer']);
  const selectRecipe=fn(0x9091a0,'void',['int']);
  const selectCategory=fn(0x907fb0,'void',['int']);
  const canAdd=fn(0x910440,'bool',['int','int','bool']);
  const add=fn(0x910c60,'int',['int','int','int','bool']);
  const remove=fn(0x90deb0,'void',['int']);
  const trigger=fn(0x90c390,'void',[]);
  // UI_Cube.hsy() uses this official game method when the window closes.  It
  // clears the selected recipe and lets the next hsw() rebuild every slot,
  // raycast target and tooltip from a clean state.
  const closeCubeSession=fn(0x90c990,'void',[]);
  const getUiManager=new NativeFunction(base.add(0x2a6cf10),'pointer',['pointer']);
  const getGameObject=fn(0x472db80,'pointer',['pointer']);
  const activeInHierarchy=fn(0x4733060,'bool',['pointer']);
  let settings=null, beat=Date.now(), next=0, transaction=null, status='starting', stopped=false;
  let total={combine:0,alchemy:0}, preview=false, stageOnly=false, lastReport=0, stopDone=null;
  let rules=null,revision=0,uiWasActive=false;
  function emit(event,extra={}){send({event,total,...extra});}
  function fields(r){const c=base.add(r).readPointer();if(c.isNull())throw Error('Game data unavailable');const f=c.add(0xb8).readPointer();if(f.isNull())throw Error('Game data unavailable');return f;}
  function entries(d){
    if(d.isNull())throw Error('Missing inventory');
    const a=d.add(0x18).readPointer(),n=d.add(0x20).readS32(),out=[];
    if(n<0||n>10000)throw Error('Invalid inventory size');
    if(n && (a.isNull()||n>a.add(0x18).readU64().toNumber()))throw Error('Invalid inventory array');
    for(let i=0;i<n;i++){const e=a.add(0x20+i*24);if(e.readS32()>=0&&!e.add(16).readPointer().isNull())out.push(e);}
    return out;
  }
  function listValues(p){
    if(p.isNull())throw Error('Cube recipe catalog is not loaded');
    const n=p.add(0x18).readS32(),a=p.add(0x10).readPointer();
    if(n<0||n>10000||a.isNull()||n>a.add(0x18).readU64().toNumber())throw Error('Invalid Cube recipe catalog');
    return Array.from({length:n},(_,i)=>a.add(0x20+i*8).readPointer());
  }
  function readRule(p){
    if(p.isNull())return null;
    const out={};
    for(const [key,offset] of [['key',0x30],['tier',0x34],['minTier',0x38],['min',0x3c],['max',0x40],['category',0x44],['grade',0x48],['count',0x4c],['avg',0x50]])out[key]=p.add(offset).readS32();
    return out;
  }
  function synthesisRules(){
    if(!rules){const db=fields(0x5fc0780).readPointer();if(db.isNull())throw Error('Recipe database is unavailable');
      rules=listValues(db.add(0x150).readPointer()).map(readRule).filter(Boolean);
      if(!rules.length)throw Error('No synthesis rules available');}
    return rules;
  }
  function targetRecipe(tier){
    for(const e of entries(fields(0x5f4b220).add(0xf8).readPointer()))if(e.add(8).readS32()===1)
      for(const p of listValues(e.add(16).readPointer()))if(!p.isNull()&&recipeTier(p,nil)===tier) {
        // The public selector can PURCHASE a locked recipe. Never call it
        // unless the game confirms that this exact recipe is already unlocked.
        if(!recipeUnlocked(p,nil))throw Error('Selected synthesis tier is locked');
        return p;
      }
    throw Error('Selected synthesis tier is unavailable');
  }
  function chooseRecipe(batch){
    if(batch.mode==='combine')selectSubRecipe(targetRecipe(batch.tier),nil);
    else selectRecipe(batch.recipe,nil);
  }
  function cubeState(){
    const f=fields(0x5f4b220),l=f.add(0x118).readPointer();
    if(l.isNull())throw Error('Cube is not loaded');
    const n=l.add(0x18).readS32(),a=l.add(0x10).readPointer(),slots=[];
    if(n!==9)throw Error('Unsupported Cube capacity');
    for(let i=0;i<n;i++) {const p=a.add(0x20+i*8).readPointer();slots.push({index:i,id:cubeId(p,nil).toString(),source:p.add(0x18).readS32()});}
    const r=f.add(0x158).readPointer(),syn=f.add(0x260).readPointer();
    return {busy:!!f.add(0x160).readU8(),ready:!!f.add(0x249).readU8(),
      recipe:r.isNull()?null:r.add(0x18).readPointer().add(0x34).readS32(),
      tier:r.isNull()?null:recipeTier(r,nil),rule:readRule(syn),
      required:syn.isNull()?null:syn.add(0x4c).readS32(),slots,filled:slots.filter(x=>x.source!==0)};
  }
  function cubeUiActive(){
    const singleton=base.add(0x5f55050).readPointer();
    if(singleton.isNull())return false;
    const manager=getUiManager(singleton);
    if(manager.isNull())return false;
    const cube=manager.add(0xd8).readPointer();
    if(cube.isNull())return false;
    const gameObject=getGameObject(cube,nil);
    return !gameObject.isNull()&&!!activeInHierarchy(gameObject,nil);
  }
  function restoreHiddenCube(){
    const c=cubeState();
    if(!c.busy&&!cubeUiActive()&&c.recipe!==null)closeCubeSession(nil);
  }
  function readItem(source,slot){
    const p=getItem(source,slot,nil);if(p.isNull())return null;
    const info=p.add(0x10).readPointer();if(info.isNull())return null;
    const enchant=p.add(0x58).readPointer();let enchanted=false;
    if(!enchant.isNull()) {
      const n=enchant.add(0x18).readU64().toNumber();if(n>32)throw Error('Invalid enchant data');
      // The game stores a base value of 1 for normal Rare-and-higher gear.
      // Values above 1 represent a user-applied upgrade and remain protected.
      for(let i=0;i<n;i++) if(enchant.add(0x20+i*4).readS32()>1)enchanted=true;
    }
    return {source,slot,id:getId(p,nil).toString(),itemId:info.add(0x30).readS32(),type:info.add(0x34).readS32(),
      grade:info.add(0x38).readS32(),category:info.add(0x4c).readS32(),level:info.add(0x6c).readS32(),tier:itemTier(p,nil),
      blocked:!!blocked(p,nil),chaotic:!!chaotic(p,nil),enchanted};
  }
  function inventory(){
    const out=[];
    for(const [source,d] of [[1,fields(0x5f4bbb0).readPointer()],[2,fields(0x5f4b5e8).add(0x18).readPointer()]]) {
      for(const e of entries(d)) {
        const save=e.add(16).readPointer().add(0x18).readPointer(),slot=save.add(0x10).readS32();
        if(!save.add(0x20).readU8()||save.add(0x18).readU64().toString()==='0'||source===2&&slot>=343)continue;
        const x=readItem(source,slot);if(x)out.push(x);
      }
    }
    return out;
  }
  function cleanup(){
    if(!transaction)return;
    const c=cubeState();if(c.busy)return;
    const own=new Set(transaction.items.map(x=>x.id));
    for(const x of c.filled)if(own.has(x.id))remove(x.index,nil);
  }
  function pause(reason){
    stopped=true;status='paused';
    try{if(transaction&&!transaction.submitted)cleanup();restoreHiddenCube();}catch(e){reason+='; cleanup: '+e;}
    emit('paused',{reason});
  }
  rpc.exports={
    configure(s,readOnly=false,rehearse=false){settings=validateSettings(s);revision++;preview=!!readOnly;stageOnly=!!rehearse;beat=Date.now();status='on';emit('ready',{preview});},
    heartbeat(){beat=Date.now();return {state:status,total};},
    stop(){stopped=true;return new Promise(resolve=>{stopDone=resolve;setTimeout(()=>resolve({state:status}),1500);});}
  };
  Interceptor.attach(base.add(0x8edf00),{onEnter(args){
    const now=Date.now();if(!settings||now<next)return;next=now+500;
    try {
      const c=cubeState();
      const uiActive=cubeUiActive(),policy=cubeUiPolicy(uiActive,transaction);
      if(uiActive!==uiWasActive) {
        emit(uiActive?'user_cube_opened':'user_cube_closed');
        uiWasActive=uiActive;
      }
      if(stopped||now-beat>8000){
        if(transaction&&transaction.submitted&&c.busy)return;
        if(transaction&&!transaction.submitted)cleanup();
        transaction=null;
        if(!uiActive&&!c.busy&&c.recipe!==null)closeCubeSession(nil);
        status='off';if(stopDone){stopDone({state:status});stopDone=null;}return;
      }
      if(transaction) {
        if(transaction.submitted) {
          if(c.busy){if(now-transaction.at>60000)pause('Cube server response timed out; no retry');return;}
          const ids=new Set(inventory().map(x=>x.id));
          const consumed=transaction.items.filter(x=>!ids.has(x.id)).length;
          if(consumed===transaction.items.length){
            const completed=transaction;
            // Match UI_Cube.hsy(): while the Cube is hidden, end the temporary
            // automation session instead of changing recipe back and forth.
            // The next manual open then performs the game's normal full setup.
            if(!uiActive)closeCubeSession(nil);
            total[completed.mode]+=consumed;emit('processed',{mode:completed.mode,count:consumed});
            transaction=null;status=uiActive?'waiting_user_cube':'on';next=now+500;return;
          }
          if(now-transaction.at>15000)pause('Cube result was not confirmed; no automatic retry');
          return;
        }
        if(policy==='yield') {
          cleanup();transaction=null;status='waiting_user_cube';
          emit('yielded_to_user',{reason:'Cube window is open'});return;
        }
        if(c.busy){pause('Cube started outside automation');return;}
        if(transaction.revision!==revision){cleanup();transaction=null;restoreHiddenCube();status='on';emit('cancelled',{reason:'Settings changed; selecting a new batch'});return;}
        if(transaction.mode==='combine'&&c.tier!==transaction.tier){pause('Cube tier changed; batch cancelled without synthesis');return;}
        const liveItems=transaction.items.map(x=>readItem(x.source,x.slot));
        if(!liveItems.every((x,i)=>x&&x.id===transaction.items[i].id&&eligible(x,settings))||
            transaction.mode==='combine'&&!batchRule(liveItems,settings,synthesisRules())){
          // Auto Stash can move an item after planning but before Cube owns
          // it. Re-scan instead of disabling Auto Combine for that safe race.
          if(!transaction.staged){transaction=null;status='on';emit('cancelled',{reason:'Item moved; selecting a fresh batch'});return;}
          pause('Items no longer meet the selected synthesis tier');return;
        }
        if(!transaction.staged) {
          if(c.filled.length){pause('Cube selection changed; batch cancelled');return;}
          if(c.recipe!==transaction.recipe){pause('Requested recipe is not unlocked');return;}
          if(!transaction.items.every(x=>{const live=readItem(x.source,x.slot);return live&&live.id===x.id&&eligible(live,settings);})){pause('Item state changed; batch cancelled');return;}
          // Recipe and synthesis-category changes rebuild the Cube on the next
          // Unity update.  Adding in the same update is rejected even though
          // the selected recipe field has already changed.
          for(let i=0;i<transaction.items.length;i++) {
            const x=transaction.items[i];
            if(!canAdd(x.source,x.slot,0,nil)) {pause('Game rejected an item; batch cancelled');return;}
            const code=add(x.source,x.slot,i,1,nil);
            if(code!==0){pause('Game rejected Cube input (code '+code+')');return;}
          }
          transaction.staged=true;status='staged';next=now+500;return;
        }
        const expected=transaction.items.map(x=>x.id).sort().join(',');
        if(c.recipe!==transaction.recipe||c.filled.map(x=>x.id).sort().join(',')!==expected){pause('Cube selection changed; batch cancelled');return;}
        if(!transaction.items.every(x=>{const live=readItem(x.source,x.slot);return live&&live.id===x.id&&eligible(live,settings);})){pause('Item state changed; batch cancelled');return;}
        if(transaction.mode==='combine'&&c.required!==9){pause('This recipe does not require 9 items');return;}
        if(transaction.mode==='combine') {
          const rule=batchRule(liveItems,settings,synthesisRules());
          if(!c.rule||c.rule.tier!==transaction.tier||c.rule.key!==rule.key){pause('Game result rule changed; batch cancelled without synthesis');return;}
          targetRecipe(transaction.tier);
        }
        if(!c.ready){pause('Game rejected this batch or recipe tier');return;}
        if(stageOnly){emit('rehearsed',{mode:transaction.mode,tier:c.tier,rule:c.rule,ready:c.ready,required:c.required,items:transaction.items});cleanup();transaction=null;restoreHiddenCube();stopped=true;status='off';return;}
        transaction.submitted=true;transaction.at=now;status='processing';
        emit('submitted',{mode:transaction.mode,tier:c.tier,rule:c.rule,items:transaction.items});trigger(nil);return;
      }
      if(policy==='yield'){status='waiting_user_cube';return;}
      if(c.busy||c.filled.length){status='waiting_cube';return;}
      const m=args[0],service=m.add(0x68).readPointer();
      if(service.isNull()||service.add(0x20).readU8()||!m.add(0x60).readPointer().isNull()||!m.add(0x88).readPointer().isNull()||m.add(0x58).readU8()||m.add(0x59).readU8()||m.add(0x5c).readU8())return;
      const catalog=synthesisRules();
      if(settings.combine)for(const tier of new Set(settings.combineCategories.filter(x=>x.enabled).map(x=>x.tier)))targetRecipe(tier);
      const owned=inventory(),batch=planBatch(owned,settings,catalog),progress=combineProgress(owned,settings,catalog);
      status=batch?'on':'waiting_items';
      if(preview){if(now-lastReport>3000){emit('preview',{batch,progress});lastReport=now;}return;}
      if(!batch){if(now-lastReport>3000){emit('scan',{progress});lastReport=now;}return;}
      chooseRecipe(batch);
      if(batch.mode==='combine')selectCategory(batch.category,nil);
      transaction={...batch,revision,at:now,submitted:false,staged:false};
      status='preparing';next=now+500;
    }catch(e){pause(String(e));}
  }});
}
if(typeof Process!=='undefined')startCubeAgent();else module.exports={validateSettings,eligible,combineEligible,combineProgress,planBatch,batchRule,categorySetting,cubeUiPolicy};
