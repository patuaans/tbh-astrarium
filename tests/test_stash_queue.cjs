const assert = require('node:assert/strict');
const {ACCESSIBLE_STASH_PAGE_COUNT,StashQueue,chooseStashPage,routeStashPage,pageHasSpace} = require('../src/tbhastrarium/agents/autostash.js');
const item=(id,itemId=1)=>({id:String(id),itemId});
const slot=(id,index=0,unlocked=true)=>({id:String(id),slot:index,unlocked});
let passed=0;
function test(name,fn){fn();console.log('PASS '+name);passed++;}
test('Existing eligible inventory is reconciled but existing stash is not queued',()=>{
 const q=new StashQueue([1]);q.observe([item(1),item(2)],[slot(1)],[slot(2)]);
 assert.equal(q.candidate([slot(1)]).id,'1');
 q.observe([item(1),item(2)],[],[slot(1),slot(2,1)]);assert.equal(q.pending.size,0);
 q.observe([item(1),item(2)],[slot(2,1)],[]);assert.equal(q.candidate([slot(2,1)]),null);
});
test('All simultaneous arrivals are retained and moved by current slot',()=>{
 const q=new StashQueue([1]);q.observe([],[],[]);q.observe([item(2),item(3)],[slot(2,4),slot(3,5)],[]);
 assert.equal(q.pending.size,2);assert.equal(q.candidate([slot(3,9),slot(2,8)]).slot,9);
 q.observe([item(2),item(3)],[slot(2,8)],[slot(3,15)]);assert.equal(q.candidate([slot(2,8)]).id,'2');
});
test('Inventory arriving after registry is still queued',()=>{
 const q=new StashQueue([1]);q.observe([],[],[]);q.observe([item(2)],[],[]);
 assert.equal(q.candidate([]),null);q.observe([item(2)],[slot(2,6)],[]);assert.equal(q.candidate([slot(2,6)]).id,'2');
});
test('Chest and unknown catalog types are excluded',()=>{
 const q=new StashQueue([1]);q.observe([],[],[]);q.observe([item(2,900),item(3,999)],[slot(2),slot(3)],[]);
 assert.equal(q.pending.size,0);
});
test('A stashed item withdrawn later is not moved back',()=>{
 const q=new StashQueue([1]);q.observe([],[],[]);q.observe([item(2)],[slot(2)],[]);
 q.observe([item(2)],[],[slot(2)]);q.observe([item(2)],[slot(2)],[]);assert.equal(q.candidate([slot(2)]),null);
});
test('Consumed or removed items are dropped from pending',()=>{
 const q=new StashQueue([1]);q.observe([],[],[]);q.observe([item(2)],[slot(2)],[]);q.observe([],[],[]);assert.equal(q.pending.size,0);
});
test('Locked slots never become move candidates',()=>{
 const q=new StashQueue([1]);q.observe([],[],[]);q.observe([item(2)],[slot(2,4,false)],[]);assert.equal(q.candidate([slot(2,4,false)]),null);
});
test('Full stash does not discard the queue',()=>{
 const q=new StashQueue([1]);q.observe([],[],[slot(10)]);q.observe([item(2)],[slot(2)],[slot(10)]);
 for(let i=0;i<50;i++)q.observe([item(2)],[slot(2)],[slot(10)]);
 assert.equal(q.candidate([slot(2)]).id,'2');
});
test('Re-enabling resumes eligible inventory work',()=>{
 const q=new StashQueue([1]);q.observe([item(2)],[slot(2)],[]);q.observe([item(2)],[slot(2)],[]);assert.equal(q.pending.size,1);
});
test('Full first page advances to second page',()=>{
 const stash=Array.from({length:98},(_,i)=>slot(i<49?i+1:0,i));assert.equal(chooseStashPage(stash),1);
});
test('Owned DLC pages are selected after normal pages are full',()=>{
 const stash=Array.from({length:343},(_,i)=>slot(i<294?i+1:0,i));
 assert.equal(chooseStashPage(stash),6);
});
test('All owned pages return waiting; freeing any page resumes',()=>{
 const stash=Array.from({length:343},(_,i)=>slot(i+1,i));assert.equal(chooseStashPage(stash),null);
 stash[174]=slot(0,174);assert.equal(chooseStashPage(stash),3);
});
test('Locked pages and unsorted dictionary order are handled',()=>{
 assert.equal(chooseStashPage([slot(0,147),slot(0,49,false),slot(0,98)]),2);
 assert.equal(chooseStashPage([slot(0,49,false)]),null);
});
test('The final owned page is usable',()=>{
 assert.equal(chooseStashPage([slot(0,342)]),6);
});
test('Page boundary changes after last free slot is consumed',()=>{
 const stash=[slot(0,48),slot(0,49)];assert.equal(chooseStashPage(stash),0);
 stash[0]=slot(12,48);assert.equal(chooseStashPage(stash),1);
});
test('Configured item families route only to their assigned pages',()=>{
 const mat=(itemId,grade)=>({itemId,type:1,grade,category:2});
 assert.equal(routeStashPage(mat(123003,3)),1); // Engraving → Page 2
 assert.equal(routeStashPage(mat(115001,5)),2); // Arcana+ Decoration → Page 3
 assert.equal(routeStashPage(mat(114001,4)),3); // Immortal Decoration → Page 4
 assert.equal(routeStashPage(mat(113003,3)),4); // Lower Decoration → Page 5
 assert.equal(routeStashPage(mat(143001,3)),5); // Crafting → Page 6
 assert.equal(routeStashPage(mat(190004,7)),null); // Soulstone stays in Inventory
});
test('Equipment routing distinguishes protection and category',()=>{
 const gear={itemId:304171,type:2,grade:4,category:0};
 const accessory={itemId:615091,type:2,grade:5,category:1};
 assert.equal(routeStashPage(gear),null);
 assert.equal(routeStashPage({...gear,enhanced:true}),null);
 assert.equal(routeStashPage({...gear,chaotic:true}),null);
 assert.equal(routeStashPage(accessory),6);
 assert.equal(routeStashPage({...accessory,enhanced:true}),6);
 assert.equal(routeStashPage({...accessory,chaotic:true}),6);
 assert.equal(routeStashPage(accessory,new Set([615091])),0);
 assert.equal(routeStashPage({...accessory,blocked:true}),0);
});
test('A full assigned page never spills into another category page',()=>{
 const stash=[slot(1,48),slot(0,49)];
 assert.equal(pageHasSpace(stash,0),false);
 assert.equal(pageHasSpace(stash,1),true);
});
console.log(`${passed} policy checks passed`);
