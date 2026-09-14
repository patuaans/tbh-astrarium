// Execute the shipping agent against a minimal Frida/game model. No game attach.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function fixture(autoStash=true, omitMode=false) {
  const mem = new Map(); let address = 0x10000000, now = 10000, update;
  class Pointer {
    constructor(n) { this.n = Number(n); }
    add(n) { return new Pointer(this.n + n); }
    isNull() { return this.n === 0; }
    toString() { return String(this.n); }
    readPointer() { return new Pointer(mem.get(this.n) || 0); }
    readS32() { return Number(mem.get(this.n) || 0); }
    readU8() { return this.readS32(); }
    readU64() { const n = this.readS32(); return {toNumber:()=>n,toString:()=>String(n)}; }
    readUtf8String() { return mem.get(this.n); }
    readUtf16String() { return mem.get(this.n); }
  }
  const ptr = n => new Pointer(n);
  const alloc = () => { address += 0x1000; return ptr(address); };
  const put = (p, off, value) => mem.set(p.n + off, value instanceof Pointer ? value.n : value);
  const obj = name => { const p=alloc(), c=alloc(), s=alloc(); put(p,0,c);put(c,0x10,s);put(s,0,name);return p; };
  const manager=obj('SlotInteractionManager'),service=obj('ru'),ui=obj('UI_RemakeStash'),uiManager=alloc(),uiObject=alloc();
  let stashOpen=false;
  put(manager,0x68,service);put(uiManager,0xe8,ui);put(ui,0xc8,2);
  const inv=alloc(),stash=alloc(),owned=alloc();
  for(const [rva,offset,d] of [[0x5F4BBB0,0,inv],[0x5F4B5E8,0x18,stash],[0x5FA3650,0,owned]]) {
    const c=alloc(),sf=alloc();put(ptr(rva),0,c);put(c,0xb8,sf);put(sf,offset,d);
  }
  const inventory=[{slot:0,id:'100',unlocked:true,itemId:143001,type:1,grade:3,category:2}];
  const storage=Array.from({length:343},(_,slot)=>({slot,id:slot<48?String(1000+slot):'0',unlocked:true}));
  const items=[{id:'100',itemId:1}],calls=[],events=[];
  function dictionary(d, values, convert) {
    const a=alloc();put(d,0x18,a);put(d,0x20,values.length);put(a,0x18,values.length);
    values.forEach((v,i)=>put(a,0x20+i*24+16,convert(v)));
  }
  function cache(x) { const c=alloc(),s=alloc();put(c,0x18,s);put(s,0x10,x.slot);put(s,0x18,Number(x.id));put(s,0x20,!!x.unlocked);return c; }
  function sync() {
    inventory.forEach(x=>{
      if(!x.itemPtr){x.itemPtr=alloc();x.infoPtr=alloc();x.enchantPtr=alloc();}
      put(x.itemPtr,0x10,x.infoPtr);put(x.itemPtr,0x58,x.enchantPtr);put(x.enchantPtr,0x18,0);
      put(x.infoPtr,0x30,x.itemId);put(x.infoPtr,0x34,x.type);put(x.infoPtr,0x38,x.grade);put(x.infoPtr,0x4c,x.category);
    });
    dictionary(inv,inventory,cache);dictionary(stash,storage,cache);
    dictionary(owned,items,x=>{const d=alloc(),s=alloc();put(d,0x28,s);put(d,0x30,x.itemId);put(s,0x10,x.id.length);put(s,0x14,x.id);return d;});
  }
  const rpc={exports:{}};
  function NativeFunction(p) {
    if(p.n===0x2A6CF10)return ()=>uiManager;
    if(p.n===0x472DB80)return component=>component.n===ui.n?uiObject:ptr(0);
    if(p.n===0x4733120)return gameObject=>gameObject.n===uiObject.n&&stashOpen;
    if(p.n===0x8AD400)return (manager,target)=>{
      assert.equal(manager.n,uiManager.n);assert.equal(target.n,ui.n);
      calls.push(['open']);stashOpen=true;
    };
    if(p.n===0xAEA300)return (u,page)=>{calls.push(['page',page]);put(u,0xc8,page);};
    if(p.n===0x8E39D0)return (s,source,slot,callback,target)=>{
      assert.equal(source,1);assert.equal(target,2);const page=ui.add(0xc8).readS32();
      const dest=storage.find(x=>x.slot/49>=page&&x.slot/49<page+1&&x.id==='0'&&x.unlocked);
      assert.ok(dest,'Move must never target a full page');const item=inventory.find(x=>x.slot===slot);
      calls.push(['move',page,item.id]);dest.id=item.id;item.id='0';
    };
    if(p.n===0x911260)return (source,slot)=>{
      const item=inventory.find(x=>x.slot===slot&&x.id!=='0');return item?item.itemPtr:ptr(0);
    };
    if(p.n===0x96AD90||p.n===0x96AD60)return ()=>false;
    throw Error('Unexpected native method');
  }
  vm.runInNewContext(fs.readFileSync(require.resolve('../src/tbhastrarium/agents/autostash.js'),'utf8'),{
    Process:{id:1,getModuleByName:()=>({base:ptr(0)})},NativeFunction,ptr,rpc,
    Date:{now:()=>now},send:e=>events.push(e),Interceptor:{attach:(p,cb)=>{update=cb.onEnter;}}
  });
  if(omitMode)rpc.exports.configure([143001]);else rpc.exports.configure([143001,190004,304171],autoStash);
  const tick=()=>{now+=300;rpc.exports.heartbeat();sync();update([manager]);};
  const arrive=(id,detail={})=>{const item={id,slot:inventory.length,unlocked:true,itemId:143001,type:1,grade:3,category:2,...detail};items.push({id,itemId:item.itemId});inventory.push(item);};
  const occupyCube=()=>{
    const c=alloc(),sf=alloc(),list=alloc(),array=alloc(),item=alloc();
    put(ptr(0x5f4b220),0,c);put(c,0xb8,sf);put(sf,0x118,list);
    put(list,0x18,1);put(list,0x10,array);put(array,0x20,item);put(item,0x18,1);
  };
  tick();return {tick,arrive,storage,inventory,calls,events,rpc,occupyCube,setStashOpen:value=>{stashOpen=!!value;}};
}
let f=fixture();f.arrive('101');f.tick();assert.deepEqual(f.calls,[['page',5]]);
f.tick();f.tick();assert.equal(f.events.at(-1).stashSlot,245);
f.arrive('102');f.tick();f.tick();assert.equal(f.events.at(-1).stashSlot,246);
assert.equal(f.inventory[0].id,'100');
console.log('PASS shipping agent routes Crafting only into Page 6');
f=fixture(true,true);f.arrive('101');f.tick();assert.equal(f.rpc.exports.heartbeat().active,true);
console.log('PASS omitted legacy RPC mode still enables Auto Stash');
f=fixture();for(const s of f.storage.filter(x=>x.slot>=245&&x.slot<294))s.id=String(1000+s.slot);
// The assigned page is full, so another category page must not be used.
f.arrive('101');f.tick();assert.equal(f.rpc.exports.heartbeat().state,'full');assert.equal(f.calls.length,0);
f.storage[260].id='0';f.tick();f.tick();f.tick();assert.equal(f.events.at(-1).stashSlot,260);
console.log('PASS shipping agent retains an item when its assigned page is full and resumes there only');
f=fixture(false);f.rpc.exports.openpage(6);f.tick();assert.deepEqual(f.calls,[['open'],['page',6]]);assert.equal(f.events.at(-1).page,7);assert.equal(f.events.at(-1).openedWindow,true);
f=fixture(false);f.setStashOpen(true);f.rpc.exports.openpage(3);f.tick();assert.deepEqual(f.calls,[['page',3]]);assert.equal(f.events.at(-1).openedWindow,false);
assert.throws(()=>f.rpc.exports.openpage(7),/Unsupported stash page/);
console.log('PASS page-only agent opens a closed Stash and switches an already-open Stash without toggling it closed');
f=fixture();f.arrive('101');f.occupyCube();f.tick();assert.equal(f.calls.length,0);
console.log('PASS Auto Stash yields while Cube holds selected items');
f=fixture();f.arrive('101',{itemId:190004,grade:7});f.tick();assert.equal(f.calls.length,0);assert.equal(f.inventory.at(-1).id,'101');
console.log('PASS Soulstones remain in Inventory');
f=fixture();f.arrive('101',{itemId:304171,type:2,grade:4,category:0});f.tick();assert.equal(f.calls.length,0);assert.equal(f.inventory.at(-1).id,'101');
console.log('PASS unprotected Gear remains in Inventory');
