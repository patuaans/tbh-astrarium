"""Read-only inspector for the current Task Bar Hero IL2CPP drop queues.

It never writes to, injects into, or calls code inside the game process.
"""

import ctypes
import json
import struct
from ctypes import wintypes
from pathlib import Path

from .builds import require_supported

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
        ("szModule", wintypes.WCHAR * 256), ("szExePath", wintypes.WCHAR * 260),
    ]


def find_pid(exe_name):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == exe_name.lower():
                return entry.th32ProcessID
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    raise RuntimeError(f"Process not found: {exe_name}")


def module_base(pid, module_name):
    flags = TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32
    snap = kernel32.CreateToolhelp32Snapshot(flags, pid)
    if snap == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Module32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szModule.lower() == module_name.lower():
                return ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value
            ok = kernel32.Module32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    raise RuntimeError(f"Module not found: {module_name}")


def module_path(pid, module_name):
    flags = TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32
    snap = kernel32.CreateToolhelp32Snapshot(flags, pid)
    if snap == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Module32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szModule.lower() == module_name.lower():
                return Path(entry.szExePath)
            ok = kernel32.Module32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    raise RuntimeError(f"Module not found: {module_name}")


class Reader:
    def __init__(self, pid):
        self.handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def read(self, address, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        ok = kernel32.ReadProcessMemory(
            self.handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got)
        )
        if not ok or got.value != size:
            raise ctypes.WinError(ctypes.get_last_error())
        return buf.raw

    def u64(self, address):
        return struct.unpack("<Q", self.read(address, 8))[0]

    def i32(self, address):
        return struct.unpack("<i", self.read(address, 4))[0]

    def string(self, address):
        if not address:
            return None
        length = self.i32(address + 0x10)
        if length < 0 or length > 4096:
            return f"<invalid-string length={length}>"
        return self.read(address + 0x14, length * 2).decode("utf-16-le", errors="replace")

    def char_array(self, address):
        if not address:
            return []
        length = self.u64(address + 0x18)
        if length > 4096:
            raise ValueError(f"implausible char[] length {length}")
        if not length:
            return []
        return list(struct.unpack(f"<{length}H", self.read(address + 0x20, length * 2)))


def read_obscured_int(reader, address):
    """Decode ACTk ObscuredInt from this build.

    The game's ObscuredInt implementation decrypts it as
    (hiddenValue - currentCryptoKey) XOR currentCryptoKey.
    """
    hash_value, hidden, key, fake = struct.unpack("<iiii", reader.read(address, 16))
    subtracted = ctypes.c_uint32(hidden - key).value
    decoded = ctypes.c_int32(subtracted ^ ctypes.c_uint32(key).value).value
    return {
        "value": decoded,
        "hash": hash_value,
        "hiddenValue": hidden,
        "cryptoKey": key,
        "fakeValue": fake,
    }


def read_obscured_string(reader, address):
    """Decode the current ACTk ObscuredString char-array representation."""
    if not address:
        return None
    key_chars = reader.char_array(reader.u64(address + 0x18))
    hidden_chars = reader.char_array(reader.u64(address + 0x20))
    if not key_chars:
        return "" if not hidden_chars else None
    decoded = [value ^ key_chars[index % len(key_chars)]
               for index, value in enumerate(hidden_chars)]
    return bytes(struct.pack(f"<{len(decoded)}H", *decoded)).decode(
        "utf-16-le", errors="replace"
    )


def read_list(reader, list_ptr):
    items = reader.u64(list_ptr + 0x10)
    size = reader.i32(list_ptr + 0x18)
    if size < 0 or size > 10000:
        raise ValueError(f"implausible List size {size}")
    result = []
    for index in range(size):
        box = reader.u64(items + 0x20 + index * 8)
        if not box:
            continue
        obscured_item_id = read_obscured_int(reader, box + 0x10)
        obscured_reward_id = read_obscured_int(reader, box + 0x30)
        result.append({
            "index": index,
            "box_address": f"0x{box:X}",
            "itemId": reader.i32(box + 0x54),
            "itemKey": reader.string(reader.u64(box + 0x58)),
            "claimableAt": reader.string(reader.u64(box + 0x60)),
            "rewardItemId": reader.i32(box + 0x68),
            "rewardItemKey": reader.string(reader.u64(box + 0x70)),
            "isGet": bool(reader.read(box + 0x78, 1)[0]),
            "obscuredItemId": obscured_item_id["value"],
            "obscuredItemKey": read_obscured_string(reader, reader.u64(box + 0x20)),
            "obscuredClaimableAt": read_obscured_string(reader, reader.u64(box + 0x28)),
            "obscuredRewardItemId": obscured_reward_id["value"],
            "obscuredRewardItemKey": read_obscured_string(reader, reader.u64(box + 0x40)),
        })
    return result


def read_dictionary(reader, dict_ptr):
    entries = reader.u64(dict_ptr + 0x18)
    count = reader.i32(dict_ptr + 0x20)
    free_count = reader.i32(dict_ptr + 0x28)
    capacity = reader.u64(entries + 0x18) if entries else 0
    groups = {}
    # Specialized Entry<EBoxType,List<BoxData>> is 24 bytes:
    # int hashCode, int next, EBoxType key, 4-byte padding, List<BoxData>* value.
    for index in range(min(max(count, 0), capacity, 64)):
        row = entries + 0x20 + index * 24
        hash_code, _next, key = struct.unpack("<iii", reader.read(row, 12))
        value = reader.u64(row + 0x10)
        if hash_code >= 0 and value:
            groups[str(key)] = read_list(reader, value)
    return {
        "address": f"0x{dict_ptr:X}",
        "count": count,
        "freeCount": free_count,
        "capacity": capacity,
        "groups": groups,
    }


def read_owned_chests(reader, base):
    """Read vm.ul.bfdz: the game's live unopened-chest inventory.

    bfdz is Dictionary<EBoxType, Dictionary<ulong, int>>.  Unlike the save
    file and the BoxBucket history, the game removes an entry here immediately
    when a chest is opened and adds it immediately when a chest is received.
    """
    # we.ux_TypeInfo in the current build.
    inventory_class = reader.u64(base + 0x5F4BBB0)
    static_fields = reader.u64(inventory_class + 0xB8)
    outer = reader.u64(static_fields + 0x10)  # vm.ul.bfdz
    entries = reader.u64(outer + 0x18)
    count = reader.i32(outer + 0x20)
    capacity = reader.u64(entries + 0x18) if entries else 0
    if count < 0 or count > 64 or capacity > 64:
        raise ValueError("implausible live chest inventory dictionary")
    result = []
    for index in range(min(count, capacity)):
        row = entries + 0x20 + index * 24
        hash_code, _next, box_type = struct.unpack("<iii", reader.read(row, 12))
        inner = reader.u64(row + 0x10)
        if hash_code < 0 or not inner:
            continue
        inner_entries = reader.u64(inner + 0x18)
        inner_count = reader.i32(inner + 0x20)
        inner_capacity = reader.u64(inner_entries + 0x18) if inner_entries else 0
        if inner_count < 0 or inner_count > 4096 or inner_capacity > 4096:
            raise ValueError("implausible live chest inventory entries")
        # Entry<ulong,ClientBoxData>: hash/next (8), ulong key (8), then
        # ClientBoxData { int Quantity; int BoxItemKey; } (8).
        for item_index in range(min(inner_count, inner_capacity)):
            item_row = inner_entries + 0x20 + item_index * 24
            item_hash, _item_next = struct.unpack("<ii", reader.read(item_row, 8))
            if item_hash < 0:
                continue
            unique_id = reader.u64(item_row + 0x08)
            quantity = reader.i32(item_row + 0x10)
            if unique_id and quantity > 0:
                result.append({"type": str(box_type), "unique_id": str(unique_id), "quantity": quantity})
    return result


def read_current_stage(reader, base):
    """Read the live StageCache identity for UI context (TBH 1.01.05)."""
    # we.vy.bgev is the currently entered StageCache.
    stage_class = reader.u64(base + 0x5F4C658)  # we.vy_TypeInfo
    static_fields = reader.u64(stage_class + 0xB8)
    cache = reader.u64(static_fields + 0xA8)
    if not cache:
        return None
    return {
        "difficulty": read_obscured_int(reader, cache + 0x58)["value"],
        "act": read_obscured_int(reader, cache + 0x68)["value"],
        "stage": read_obscured_int(reader, cache + 0x78)["value"],
        "stageKey": read_obscured_int(reader, cache + 0x18)["value"],
        "normalBoxId": read_obscured_int(reader, cache + 0xA8)["value"],
        "bossBoxId": read_obscured_int(reader, cache + 0x98)["value"],
    }


def read_current_item_catalog():
    """Read immutable item metadata already loaded by the current game.

    This lets the viewer recognize newly added gear and materials immediately,
    even when its bundled display-name catalog predates the game update.
    """
    pid = find_pid("TaskBarHero.exe")
    require_supported(module_path(pid, "GameAssembly.dll"), "drop-reader")
    reader = Reader(pid)
    try:
        base = module_base(pid, "GameAssembly.dll")
        # oa<bci> is the singleton backing the game's complete data tables.
        singleton_class = reader.u64(base + 0x5FC0780)
        static_fields = reader.u64(singleton_class + 0xB8)
        database = reader.u64(static_fields)
        item_list = reader.u64(database + 0x20)
        array = reader.u64(item_list + 0x10)
        count = reader.i32(item_list + 0x18)
        capacity = reader.u64(array + 0x18) if array else 0
        if count < 0 or count > 20000 or count > capacity:
            raise ValueError("implausible item catalog")
        result = {}
        for index in range(count):
            item = reader.u64(array + 0x20 + index * 8)
            if not item:
                continue
            item_id = reader.i32(item + 0x30)
            if item_id <= 0:
                continue
            result[str(item_id)] = {
                "nameKey": reader.string(reader.u64(item + 0x50)) or "",
                "typeValue": reader.i32(item + 0x34),
                "gradeValue": reader.i32(item + 0x38),
                "gearValue": reader.i32(item + 0x44),
                "level": reader.i32(item + 0x6C),
            }
        return result
    finally:
        reader.close()


def read_snapshot():
    pid = find_pid("TaskBarHero.exe")
    require_supported(module_path(pid, "GameAssembly.dll"), "drop-reader")
    reader = Reader(pid)
    try:
        base = module_base(pid, "GameAssembly.dll")
        # yb_TypeInfo owns the live drop-queue manager in the current build.
        xg_class = reader.u64(base + 0x5FA3650)
        static_fields = reader.u64(xg_class + 0xB8)
        wp_ptr = reader.u64(static_fields + 0x18)  # xg.bfrz
        queues = {}
        for label, offset in (("bfqn", 0x10), ("bfqo", 0x18), ("bfqp", 0x20)):
            dict_ptr = reader.u64(wp_ptr + offset)
            queues[label] = read_dictionary(reader, dict_ptr)
        return {
            "processId": pid,
            "gameAssemblyBase": f"0x{base:X}",
            "xgClass": f"0x{xg_class:X}",
            "xgStaticFields": f"0x{static_fields:X}",
            "wpQueueManager": f"0x{wp_ptr:X}",
            "boxType": {"0": "NORMAL", "1": "BOSS", "2": "ACTBOSS"},
            "queues": queues,
            "ownedChests": read_owned_chests(reader, base),
            "currentStage": read_current_stage(reader, base),
        }
    finally:
        reader.close()


def main():
    print(json.dumps(read_snapshot(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
