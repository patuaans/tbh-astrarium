const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(extra={}) {
  const mem=new Map(),records=new Map(),events=[],calls=[];let addr=0x10000000,now=10000,update,uiActive=!!extra.uiActive;
  class P {
    constructor(n){this.n=Number(n);} add(n){return new P(this.n+n);}isNull(){return !this.n;}
    readPointer(){return new P(mem.get(this.n)||0);}readS32(){return Number(mem.get(this.n)||0);}
    readU8(){return this.readS32();}readU64(){const n=this.readS32();return {toNumber:()=>n,toString:()=>String(n)};}
  }
  const ptr=n=>new P(n),alloc=()=>new P(addr+=0x1000),put=(p,o,v)=>mem.set(p.n+o,v instanceof P?v.n:v);
  const cube=alloc(),list=alloc(),array=alloc(),recipe=alloc(),recipeInfo=alloc(),syn=alloc(),manager=alloc(),service=alloc();
  const uiManager=alloc(),cubeUi=alloc(),cubeGameObject=alloc(),uiMethodInfo=alloc();
  put(ptr(0x5f55050),0,uiMethodInfo);put(uiManager,0xd8,cubeUi);
  function fields(r,f){const c=alloc();put(ptr(r),0,c);put(c,0xb8,f);}
  fields(0x5f4b220,cube);put(cube,0x118,list);put(list,0x10,array);put(list,0x18,9);
  put(cube,0x260,syn);put(syn,0x4c,9);put(recipe,0x18,recipeInfo);put(manager,0x68,service);
  const slots=Array.from({length:9},(_,i)=>{const p=alloc();put(array,0x20+i*8,p);return p;});
  const inventory=Array.from({length:9},(_,i)=>({source:1,slot:i,id:String(i+100),itemId:300000+i,grade:0,category:0,type:2,level:90,tier:9}));
  const rules=require('./fixtures/synthesis-rules.json'),options=new Map();
  function makeList(values){const l=alloc(),a=alloc();put(l,0x10,a);put(l,0x18,values.length);put(a,0x18,values.length);values.forEach((v,i)=>put(a,0x20+i*8,v));return l;}
  const rulePtrs=rules.map(r=>{const p=alloc();for(const [k,o] of [['key',0x30],['tier',0x34],['minTier',0x38],['min',0x3c],['max',0x40],['category',0x44],['grade',0x48],['count',0x4c],['avg',0x50]])put(p,o,r[k]);return p;});
  const dbFields=alloc(),db=alloc();fields(0x5fc0780,dbFields);put(dbFields,0,db);put(db,0x150,makeList(rulePtrs));
  const d=alloc(),a=alloc();put(cube,0xf8,d);put(d,0x18,a);put(d,0x20,1);put(a,0x18,1);put(a,0x28,1);
  const opts=Array.from({length:9},(_,i)=>{const p=alloc();options.set(p.n,i+1);put(p,0x18,recipeInfo);return p;});
  put(a,0x30,makeList(opts));
  function setRule(tier){const index=rules.findIndex(r=>r.tier===tier&&r.category===0&&r.grade===0&&r.avg===90);put(cube,0x260,index<0?syn:rulePtrs[index]);}
  const live=new Map();
  function sync(){
    for(const [r,off,source] of [[0x5f4bbb0,0,1],[0x5f4b5e8,0x18,2]]) {
      const f=alloc(),d=alloc(),a=alloc();fields(r,f);put(f,off,d);put(d,0x18,a);
      const rows=inventory.filter(x=>x.source===source);put(d,0x20,rows.length);put(a,0x18,rows.length);
      rows.forEach((x,i)=>{const rec=alloc(),save=alloc();put(a,0x20+i*24+16,rec);put(rec,0x18,save);
        put(save,0x10,x.slot);put(save,0x18,Number(x.id));put(save,0x20,1);
        if(!live.has(x.id)){const p=alloc(),info=alloc();put(p,0x10,info);records.set(p.n,x);live.set(x.id,p);
          for(const [o,k] of [[0x30,'itemId'],[0x34,'type'],[0x38,'grade'],[0x4c,'category'],[0x6c,'level']])put(info,o,x[k]);}
      });
    }
  }
  const rpc={exports:{}};
  function NativeFunction(p){
    switch(p.n){
      case 0x911260:return (source,slot)=>{const x=inventory.find(x=>x.source===source&&x.slot===slot);return x?live.get(x.id):ptr(0);};
      case 0x96ad30:return p=>({toString:()=>records.get(p.n).id});
      case 0x9a9aa0:return p=>({toString:()=>String(mem.get(p.n+0x30)||0)});
      case 0x96ad90:return p=>!!records.get(p.n).blocked;
      case 0x96ad60:return p=>!!records.get(p.n).chaotic;
      case 0x96af00:return p=>records.get(p.n).tier;
      case 0x9b6a90:return p=>options.get(p.n)||0;
      case 0x9b6ad0:return p=>!extra.locked;
      case 0x9094e0:return p=>{calls.push('tier:'+options.get(p.n));put(cube,0x158,p);put(recipeInfo,0x34,1);setRule(options.get(p.n));};
      case 0x9091a0:return r=>{calls.push('recipe');
        // The live game clears the completed result display when changing
        // recipes. Model that refresh so the next batch can be scheduled.
        if(put(recipeInfo,0x34,r), inventory.length===0) for(const s of slots){put(s,0x18,0);put(s,0x30,0);}
        put(cube,0x158,recipe);};
      case 0x907fb0:return category=>calls.push('category:'+category);
      case 0x910440:return (source,slot)=>!extra.reject||slot!==4;
      case 0x910c60:return (source,slot,index)=>{const x=inventory.find(x=>x.source===source&&x.slot===slot);put(slots[index],0x18,source);put(slots[index],0x30,Number(x.id));put(cube,0x249,1);return 0;};
      case 0x90deb0:return index=>{put(slots[index],0x18,0);put(slots[index],0x30,0);};
      case 0x90c390:return ()=>{calls.push('trigger');if(!extra.timeout)inventory.splice(0,9);};
      case 0x90c990:return ()=>{calls.push('close');put(cube,0x158,0);put(cube,0x249,0);for(const s of slots){put(s,0x18,0);put(s,0x30,0);}};
      case 0x2a6cf10:return ()=>uiManager;
      case 0x472db80:return ()=>cubeGameObject;
      case 0x4733060:return ()=>uiActive;
      default:throw Error('Unknown method '+p.n.toString(16));
    }
  }
  vm.runInNewContext(fs.readFileSync(require.resolve('../src/tbhastrarium/agents/cube.js'),'utf8'),{
    Process:{getModuleByName:()=>({base:ptr(0)})},NativeFunction,ptr,rpc,Date:{now:()=>now},send:e=>events.push(e),setTimeout:()=>{},
    Interceptor:{attach:(p,cb)=>update=cb.onEnter}
  });
  const config={combine:true,combineCategories:[
    {category:0,enabled:true,grades:[0],tier:9},
    {category:1,enabled:false,grades:[0],tier:8},
    {category:2,enabled:false,grades:[0],tier:7},
  ],combineExcludedIds:[],alchemy:false,gearMax:-1,materialMax:-1,protectedIds:[]};
  rpc.exports.configure(config,!!extra.preview,!!extra.rehearse);
  const tick=()=>{now+=600;rpc.exports.heartbeat();sync();update([manager]);};
  const filled=()=>slots.filter(p=>p.add(0x18).readS32()).length;
  return {tick,calls,events,filled,rpc,change:()=>put(slots[0],0x30,999),lock:()=>inventory[0].blocked=true,
    config,changeTier:()=>put(cube,0x158,opts[7]),changeRule:()=>put(cube,0x260,syn),
    busy:()=>put(cube,0x160,1),occupied:()=>put(slots[0],0x18,1),openUi:()=>uiActive=true,closeUi:()=>uiActive=false};
}
let f=fixture();f.tick();assert.equal(f.filled(),0);f.tick();assert.equal(f.filled(),9);assert.equal(f.calls.includes('trigger'),false);
f.tick();f.tick();assert.equal(f.calls.filter(x=>x==='trigger').length,1);assert.equal(f.events.at(-1).event,'processed');assert.equal(f.filled(),0);
assert.deepEqual(f.calls,['tier:9','category:0','trigger','close']);
f.tick();f.tick();assert.deepEqual(f.calls,['tier:9','category:0','trigger','close']);
f=fixture({preview:true});f.tick();assert.equal(f.calls.length,0);assert.equal(f.events.at(-1).event,'preview');
f=fixture({rehearse:true});f.tick();f.tick();f.tick();assert.equal(f.calls.includes('trigger'),false);assert.equal(f.filled(),0);
f=fixture({reject:true});f.tick();f.tick();assert.equal(f.filled(),0);assert.equal(f.events.at(-1).event,'paused');
f=fixture();f.tick();f.tick();f.change();f.tick();assert.equal(f.calls.includes('trigger'),false);assert.equal(f.filled(),0);assert.equal(f.calls.includes('close'),true);
f=fixture();f.tick();f.lock();f.tick();assert.equal(f.calls.includes('trigger'),false);assert.equal(f.filled(),0);assert.equal(f.events.at(-1).event,'cancelled');
f=fixture();f.occupied();f.tick();assert.equal(f.calls.length,0);
f=fixture();f.tick();f.rpc.exports.stop();f.tick();assert.equal(f.filled(),0);assert.equal(f.calls.includes('trigger'),false);
f=fixture({timeout:true});for(let i=0;i<32;i++)f.tick();assert.equal(f.calls.filter(x=>x==='trigger').length,1);assert.equal(f.events.at(-1).event,'paused');
console.log('PASS shipping Cube agent: stage/submit/confirm, preview, rehearsal, rejected input, user edits, lock changes, busy Cube, stop cleanup and no retry after timeout');
f=fixture({locked:true});f.tick();assert.equal(f.calls.length,0);assert.equal(f.events.at(-1).event,'paused','locked tier never calls a purchase-capable selector');
for(const ticks of [1,2]) {
  f=fixture();for(let i=0;i<ticks;i++)f.tick();f.changeTier();f.tick();
  assert.equal(f.calls.includes('trigger'),false);assert.equal(f.filled(),0);assert.equal(f.events.at(-1).event,'paused');
  f=fixture();for(let i=0;i<ticks;i++)f.tick();f.rpc.exports.configure({...f.config,combineCategories:f.config.combineCategories.map(x=>x.category===0?{...x,tier:8}:x)});f.tick();
  assert.equal(f.calls.includes('trigger'),false);assert.equal(f.filled(),0);assert.equal(f.events.at(-1).event,'cancelled');
  f.tick();assert.ok(f.calls.includes('tier:8'));
}
f=fixture();f.tick();f.tick();f.changeRule();f.tick();assert.equal(f.calls.includes('trigger'),false);assert.equal(f.filled(),0);
f=fixture();f.tick();f.tick();f.rpc.exports.configure({...f.config,combineCategories:f.config.combineCategories.map(x=>x.category===0?{...x,grades:[2]}:x)});f.tick();assert.equal(f.filled(),0);assert.equal(f.calls.includes('trigger'),false);
console.log('PASS exact tier selection/restoration, locked tiers, downgrade before staging/submission, effective result rule mismatch and filter/tier changes during a batch');
f=fixture({uiActive:true});f.tick();assert.equal(f.calls.length,0);assert.equal(f.events.at(-1).event,'user_cube_opened');
f=fixture();f.tick();f.tick();f.openUi();f.tick();assert.equal(f.calls.includes('trigger'),false);assert.equal(f.filled(),0);assert.equal(f.events.at(-1).event,'yielded_to_user');
f=fixture();f.tick();f.tick();f.tick();f.openUi();f.tick();assert.equal(f.events.at(-1).event,'processed');assert.equal(f.calls.includes('close'),false);
console.log('PASS Cube UI coexistence: yield before submit, finish submitted transaction, and leave visible UI state to the game');
