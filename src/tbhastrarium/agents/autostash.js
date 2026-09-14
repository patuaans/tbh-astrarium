'use strict';

// This account owns the Stash DLC. It exposes seven 49-slot pages; the game's
// own tab UI may fail to render the last three, so page selection is exposed
// through TBH Astrarium as well.
const ACCESSIBLE_STASH_PAGE_COUNT = 7;

// Pure queue policy is also exercised under Node without attaching to a game.
class StashQueue {
  constructor(eligible) { this.eligible = new Set(eligible); this.known = new Set(); this.pending = new Map(); this.seeded = false; }
  observe(items, inventory, stash) {
    if (!this.seeded) {
      const inventoryIds = new Set(inventory.filter(x => x.unlocked && x.id !== '0').map(x => x.id));
      for (const x of items) {
        this.known.add(x.id);
        // Reconcile eligible items already waiting in Inventory. This preserves
        // work across viewer restarts and lets a newly freed assigned page drain.
        if (inventoryIds.has(x.id) && this.eligible.has(x.itemId)) this.pending.set(x.id, x);
      }
      for (const x of [...inventory, ...stash]) this.known.add(x.id);
      this.seeded = true;
      return;
    }
    for (const x of items) {
      if (!this.known.has(x.id)) {
        this.known.add(x.id);
        if (this.eligible.has(x.itemId)) this.pending.set(x.id, x);
      }
    }
    const owned = new Set(items.map(x => x.id));
    const stashed = new Set(stash.map(x => x.id));
    for (const id of this.pending.keys()) if (stashed.has(id) || !owned.has(id)) this.pending.delete(id);
  }
  candidate(inventory) {
    return this.candidates(inventory)[0] || null;
  }
  candidates(inventory) {
    return inventory.filter(x => x.unlocked && x.id !== '0' && this.pending.has(x.id))
      .map(x => ({...x, ...this.pending.get(x.id)}));
  }
}

function chooseStashPage(stash, pageCount = ACCESSIBLE_STASH_PAGE_COUNT) {
  // StashSaveData.Index is global across pages; each normal page has 49 slots.
  // Include every owned page, including the DLC pages selected by the viewer.
  const maxSlot = pageCount * 49;
  const empty = stash.filter(x => x.unlocked && x.id === '0' && x.slot >= 0 && x.slot < maxSlot)
    .sort((a, b) => a.slot - b.slot)[0];
  return empty ? Math.floor(empty.slot / 49) : null;
}

// The stash is deliberately partitioned by item family. Pages are zero-based
// here, matching the game's internal page selection API:
//   1 Keepers, 2 Engraving, 3 Arcana+ Decoration, 4 Immortal Decoration,
//   5 Legendary-and-lower Decoration, 6 Crafting, 7 Accessories.
// Soulstones and unprotected Gear remain in Inventory.
function routeStashPage(item, protectedIds = new Set()) {
  if (!item || !Number.isInteger(item.itemId)) return null;
  // Page 1 is reserved for items the user explicitly protects.  Enhancement
  // and chaotic state describe an item, but do not mean that it belongs in
  // the keeper page by themselves.
  const protectedItem = !!item.blocked || protectedIds.has(item.itemId);
  if (item.type === 2) {
    if (protectedItem) return 0;
    return item.category === 1 ? 6 : null;
  }
  if (item.type !== 1) return null;
  if (item.itemId >= 190000 && item.itemId < 200000) return null;
  if (item.itemId >= 120000 && item.itemId < 140000) return 1;
  if (item.itemId >= 110000 && item.itemId < 120000) {
    if (item.grade >= 5) return 2;
    if (item.grade === 4) return 3;
    if (item.grade >= 0 && item.grade <= 3) return 4;
    return null;
  }
  if (item.itemId >= 140000 && item.itemId < 150000) return 5;
  return null;
}

function pageHasSpace(stash, page) {
  if (!Number.isInteger(page) || page < 0 || page >= ACCESSIBLE_STASH_PAGE_COUNT) return false;
  const first = page * 49, last = first + 49;
  return stash.some(x => x.unlocked && x.id === '0' && x.slot >= first && x.slot < last);
}

function selectRoutableCandidate(queue, inventory, stash, readDetail, protectedIds = new Set()) {
  let waiting = null;
  const held = [];
  for (const queued of queue.candidates(inventory)) {
    const detail = readDetail(queued.slot);
    if (!detail || detail.itemId !== queued.itemId) {
      held.push({...queued, itemId: queued.itemId, reason: 'Item changed before routing'});
      queue.pending.delete(queued.id);
      continue;
    }
    const targetPage = routeStashPage(detail, protectedIds);
    if (targetPage === null) {
      held.push({...queued, ...detail, reason: 'Inventory route'});
      queue.pending.delete(queued.id);
      continue;
    }
    const candidate = {...queued, ...detail};
    if (!pageHasSpace(stash, targetPage)) {
      // Keep this item pending, but continue scanning. A full Crafting page
      // must not block items assigned to another page that still has room.
      if (!waiting) waiting = {candidate, targetPage};
      continue;
    }
    return {candidate, targetPage, waiting, held};
  }
  return {candidate: null, targetPage: null, waiting, held};
}

function startAgent() {
  const module = Process.getModuleByName('GameAssembly.dll');
  const base = module.base;
  const nil = ptr(0);
  // Only used with the exact SHA-256 verified by tbh_autostash.py.
  const move = new NativeFunction(base.add(0x8E39D0), 'void', ['pointer', 'int', 'int', 'pointer', 'int', 'pointer']);
  const getItem = new NativeFunction(base.add(0x911260), 'pointer', ['int', 'int', 'pointer']);
  const isBlocked = new NativeFunction(base.add(0x96AD90), 'bool', ['pointer', 'pointer']);
  const isChaotic = new NativeFunction(base.add(0x96AD60), 'bool', ['pointer', 'pointer']);
  const getUiManager = new NativeFunction(base.add(0x2A6CF10), 'pointer', ['pointer']);
  const getGameObject = new NativeFunction(base.add(0x472DB80), 'pointer', ['pointer', 'pointer']);
  const isActiveSelf = new NativeFunction(base.add(0x4733120), 'bool', ['pointer', 'pointer']);
  // UIManager.hno is the same public open/toggle path used by the game's UI.
  // Call it only for an inactive target because an active target is toggled closed.
  const openUi = new NativeFunction(base.add(0x8AD400), 'void', ['pointer', 'pointer', 'pointer']);
  const selectStashPage = new NativeFunction(base.add(0xAEA300), 'void', ['pointer', 'int', 'pointer']);
  let queue = null, active = false, inFlight = null, next = 0, heartbeat = Date.now(), requestedPage = null;
  let protectedIds = new Set();
  let identity = null, total = 0, state = 'starting', lastStatus = 0;

  function emit(event, extra = {}) { send({event, total, ...extra}); }
  function pause(reason) { active = false; state = 'paused'; emit('paused', {reason}); }
  function className(p) { return p.readPointer().add(0x10).readPointer().readUtf8String(); }
  function fields(rva) {
    const c = base.add(rva).readPointer();
    if (c.isNull()) throw Error('Game data is not ready');
    const p = c.add(0xb8).readPointer();
    if (p.isNull()) throw Error('Game data is not ready');
    return p;
  }
  function entries(p, limit) {
    if (p.isNull()) throw Error('Missing game inventory');
    const array = p.add(0x18).readPointer(), count = p.add(0x20).readS32();
    if (count < 0 || count > limit) throw Error('Unsupported inventory layout');
    if (count === 0) return [];
    if (array.isNull() || count > array.add(0x18).readU64().toNumber()) throw Error('Invalid inventory capacity');
    const result = [];
    for (let i = 0; i < count; i++) {
      const e = array.add(0x20 + i * 24);
      if (e.readS32() >= 0 && !e.add(16).readPointer().isNull()) result.push(e);
    }
    return result;
  }
  function slots(dictionary) {
    return entries(dictionary, 10000).map(e => {
      const save = e.add(16).readPointer().add(0x18).readPointer();
      return {slot: save.add(0x10).readS32(), id: save.add(0x18).readU64().toString(), unlocked: !!save.add(0x20).readU8()};
    });
  }
  function items(dictionary) {
    return entries(dictionary, 100000).map(e => {
      const data = e.add(16).readPointer(), key = data.add(0x28).readPointer();
      const length = key.add(0x10).readS32();
      if (length < 1 || length > 24) throw Error('Invalid item key');
      const id = key.add(0x14).readUtf16String(length);
      if (!/^\d+$/.test(id)) throw Error('Invalid item identity');
      return {id, itemId: data.add(0x30).readS32()};
    });
  }
  function inventoryItem(slot) {
    const item = getItem(1, slot, nil);
    if (item.isNull()) return null;
    const info = item.add(0x10).readPointer();
    if (info.isNull()) return null;
    const enchant = item.add(0x58).readPointer();
    let enhanced = false;
    if (!enchant.isNull()) {
      const count = enchant.add(0x18).readU64().toNumber();
      if (count < 0 || count > 32) throw Error('Invalid enchant data');
      for (let i = 0; i < count; i++) if (enchant.add(0x20 + i * 4).readS32() > 1) enhanced = true;
    }
    return {
      itemId: info.add(0x30).readS32(), type: info.add(0x34).readS32(),
      grade: info.add(0x38).readS32(), category: info.add(0x4c).readS32(),
      blocked: !!isBlocked(item, nil), chaotic: !!isChaotic(item, nil), enhanced,
    };
  }
  rpc.exports = {
    configure(eligible, autoStash, protectedItemIds) {
      if (queue) throw Error('Agent is already configured');
      // Older packaged viewers send null for omitted optional RPC parameters.
      // Treat both null and undefined as the established Auto Stash default.
      const enabled = autoStash === null || autoStash === undefined ? true : !!autoStash;
      protectedIds = new Set(Array.isArray(protectedItemIds) ? protectedItemIds : []);
      queue = new StashQueue(eligible); active = enabled; state = active ? 'starting' : 'page'; heartbeat = Date.now();
    },
    setprotected(protectedItemIds) {
      protectedIds = new Set(Array.isArray(protectedItemIds) ? protectedItemIds : []);
      return {count: protectedIds.size};
    },
    openpage(page) {
      if (!Number.isInteger(page) || page < 0 || page >= ACCESSIBLE_STASH_PAGE_COUNT) throw Error('Unsupported stash page');
      requestedPage = page; heartbeat = Date.now(); return {page: page + 1};
    },
    heartbeat() { heartbeat = Date.now(); return {active, state, total}; },
    stop() { active = false; state = 'off'; return {total}; }
  };

  // The receiver is supplied by the game's own Update, never from an old cached
  // pointer. All game calls and snapshots run on this same Unity main thread.
  Interceptor.attach(base.add(0x8EDF00), {
    onEnter(args) {
      if ((!active && requestedPage === null) || !queue || Date.now() < next) return;
      const now = Date.now(); next = now + 250;
      if (active && now - heartbeat > 8000) { pause('Controller disconnected'); return; }
      try {
        const manager = args[0];
        if (className(manager) !== 'SlotInteractionManager') throw Error('Unsupported game update');
        if (requestedPage !== null) {
          const targetPage = requestedPage;
          const uiManager = getUiManager(base.add(0x5F55050).readPointer());
          if (uiManager.isNull()) throw Error('Stash interface is not loaded');
          const stashUi = uiManager.add(0xe8).readPointer();
          if (stashUi.isNull() || className(stashUi) !== 'UI_RemakeStash') throw Error('Unsupported stash interface');
          const stashObject = getGameObject(stashUi, nil);
          if (stashObject.isNull()) throw Error('Stash window is not loaded');
          const wasOpen = !!isActiveSelf(stashObject, nil);
          if (!wasOpen) {
            openUi(uiManager, stashUi, nil);
            if (!isActiveSelf(stashObject, nil)) throw Error('Game did not open the stash window');
          }
          const previousPage = stashUi.add(0xc8).readS32();
          if (previousPage !== targetPage) selectStashPage(stashUi, targetPage, nil);
          if (stashUi.add(0xc8).readS32() !== targetPage) throw Error('Game did not switch stash page');
          requestedPage = null;
          emit('page_opened', {from: previousPage + 1, page: targetPage + 1, openedWindow: !wasOpen});
          return;
        }
        const invDict = fields(0x5F4BBB0).readPointer();
        const stashDict = fields(0x5F4B5E8).add(0x18).readPointer();
        const itemDict = fields(0x5FA3650).readPointer();
        const currentIdentity = [invDict, stashDict, itemDict].map(String).join(':');
        if (identity && identity !== currentIdentity) { pause('Inventory session changed; enable Auto Stash again'); return; }
        identity = currentIdentity;
        const inventory = slots(invDict), stash = slots(stashDict), owned = items(itemDict);
        if (!inventory.length || !stash.length) throw Error('Inventory is not loaded');
        const wasSeeded = queue.seeded;
        queue.observe(owned, inventory, stash);
        if (!wasSeeded) {
          state = 'on';
          emit('ready', {
            inventoryCount: inventory.filter(x => x.id !== '0').length,
            stashFree: stash.filter(x => x.unlocked && x.id === '0' && x.slot < ACCESSIBLE_STASH_PAGE_COUNT * 49).length,
            accessiblePages: ACCESSIBLE_STASH_PAGE_COUNT,
            pending: queue.pending.size,
          });
          return;
        }
        if (inFlight) {
          const destination = stash.find(x => x.id === inFlight.id);
          const source = inventory.find(x => x.id === inFlight.id);
          if (destination && !source) {
            total++; emit('stashed', {...inFlight, stashSlot: destination.slot});
            queue.pending.delete(inFlight.id); inFlight = null; state = 'on';
          } else if (now - inFlight.at > 5000) {
            pause('Move was not confirmed; item was not retried');
            emit('unconfirmed', inFlight); inFlight = null;
          }
          return;
        }
        const selection = selectRoutableCandidate(queue, inventory, stash, inventoryItem, protectedIds);
        for (const held of selection.held) emit('held', held);
        const candidate = selection.candidate, targetPage = selection.targetPage;
        if (!candidate) {
          if (selection.waiting) {
            state = 'full';
            if (now - lastStatus > 5000) {
              emit('full', {pending: queue.pending.size,
                targetPage: selection.waiting.targetPage + 1,
                itemId: selection.waiting.candidate.itemId,
                accessiblePages: ACCESSIBLE_STASH_PAGE_COUNT});
              lastStatus = now;
            }
          } else state = 'on';
          return;
        }
        state = 'on';
        // Cube owns selected items until its batch finishes. Yield to manual
        // and automatic Cube work, including references to stash items.
        const cubeClass = base.add(0x5f4b220).readPointer();
        if (!cubeClass.isNull()) {
          const cubeFields = cubeClass.add(0xb8).readPointer();
          if (!cubeFields.isNull()) {
            if (cubeFields.add(0x160).readU8()) return;
            const cubeList = cubeFields.add(0x118).readPointer();
            if (!cubeList.isNull()) {
              const n = cubeList.add(0x18).readS32();
              if (n < 0 || n > 9) throw Error('Unsupported Cube layout');
              const array = cubeList.add(0x10).readPointer();
              for (let i = 0; i < n; i++) {
                if (array.add(0x20 + i * 8).readPointer().add(0x18).readS32() !== 0) return;
              }
            }
          }
        }
        const service = manager.add(0x68).readPointer();
        // Yield to an in-progress move or any user drag/selection/modifier.
        if (service.isNull() || className(service) !== 'ru' || service.add(0x20).readU8() ||
            !manager.add(0x60).readPointer().isNull() || !manager.add(0x88).readPointer().isNull() ||
            manager.add(0x58).readU8() || manager.add(0x59).readU8() || manager.add(0x5c).readU8()) return;
        const uiManager = getUiManager(base.add(0x5F55050).readPointer());
        if (uiManager.isNull()) throw Error('Stash interface is not loaded');
        const stashUi = uiManager.add(0xe8).readPointer();
        if (stashUi.isNull() || className(stashUi) !== 'UI_RemakeStash') throw Error('Unsupported stash interface');
        const previousPage = stashUi.add(0xc8).readS32();
        if (previousPage !== targetPage) {
          selectStashPage(stashUi, targetPage, nil);
          if (stashUi.add(0xc8).readS32() !== targetPage) throw Error('Game did not switch stash page');
          emit('page_changed', {from: previousPage + 1, to: targetPage + 1});
          // Let page bindings refresh and re-read source/target before moving.
          return;
        }
        inFlight = {...candidate, at: now, stashPage: targetPage + 1}; state = 'moving';
        emit('moving', inFlight);
        move(service, 1, candidate.slot, nil, 2, nil);
      } catch (error) { pause(String(error)); }
    }
  });
  emit('attached', {pid: Process.id});
}

if (typeof Process !== 'undefined') startAgent();
else module.exports = {ACCESSIBLE_STASH_PAGE_COUNT, StashQueue, chooseStashPage, routeStashPage,
  pageHasSpace, selectRoutableCandidate};
