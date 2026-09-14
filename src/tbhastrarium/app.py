"""TBH Astrarium drop viewer with explicitly enabled Auto Unbox and Auto Stash.

Drop prediction remains read-only. Auto Unbox uses the BepInEx companion;
Auto Stash attaches its own runtime agent only while enabled.
"""

import json
import re
import sys
import time
import ctypes
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from ctypes import wintypes

from . import probe as tbh_drop_probe
from .autostash import AutoStashController
from .cube import CubeController, read_synthesis_options
from .storage import StorageError, TBHStorage, atomic_write_json, default_storage_path


ROOT = Path(__file__).resolve().parent


def bundled_path(name):
    """Locate read-only assets both from source and from a PyInstaller build."""
    if getattr(sys, "frozen", False):
        packaged = Path(sys._MEIPASS) / "tbhastrarium" / name
        return packaged if packaged.exists() else Path(sys._MEIPASS) / name
    return ROOT / name


def user_data_path(name):
    """Keep mutable state outside both the source tree and install folder."""
    return default_storage_path().parent / name


def legacy_user_data_path(name):
    """Locate JSON files written by older portable releases for migration."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / name
    return ROOT / name


CATALOG_PATHS = (user_data_path("catalog.local.json"), bundled_path("tbh_items_min.json"))
WIKI_CATALOG_PATHS = (user_data_path("wiki-items.local.json"), bundled_path("wiki-items.json"))
WATCH_LIST_PATH = user_data_path("tbh_watch_list.json")
CHEST_COOLDOWN_PATH = user_data_path("tbh_chest_cooldowns.json")
CUBE_SETTINGS_PATH = user_data_path("tbh_cube_settings.json")
UI_SETTINGS_PATH = user_data_path("tbh_ui_settings.json")
LEGACY_WATCH_LIST_PATH = legacy_user_data_path("tbh_watch_list.json")
LEGACY_CHEST_COOLDOWN_PATH = legacy_user_data_path("tbh_chest_cooldowns.json")
LEGACY_CUBE_SETTINGS_PATH = legacy_user_data_path("tbh_cube_settings.json")
DATABASE_PATH = default_storage_path()
PREDICTION_NAMES = {"0": "Normal Drops", "1": "Boss Drops", "2": "Act Boss Drops"}
CHEST_TYPE_NAMES = {"0": "Normal", "1": "Stage Boss", "2": "Act Boss"}
GRADE_COLORS_DARK = {
    "COMMON": "#b5becb", "UNCOMMON": "#57d083", "RARE": "#62a9ff", "LEGENDARY": "#ffb454",
    "IMMORTAL": "#ff7373", "ARCANA": "#c58cff", "BEYOND": "#dc75ff", "CELESTIAL": "#4bd5e7",
    "DIVINE": "#ff82c8", "COSMIC": "#a994ff",
}
GRADE_COLORS_LIGHT = {
    "COMMON": "#5f6b7a", "UNCOMMON": "#178653", "RARE": "#216fc3", "LEGENDARY": "#b96608",
    "IMMORTAL": "#c93f45", "ARCANA": "#873bc4", "BEYOND": "#a53cc6", "CELESTIAL": "#147a91",
    "DIVINE": "#b93682", "COSMIC": "#6650ba",
}
THEMES = {
    "dark": {
        "bg": "#0f141c", "surface": "#171e29", "surface_alt": "#1d2633", "raised": "#253142",
        "border": "#2d394b", "text": "#edf2f7", "muted": "#9ba8b8", "accent": "#f2c14e",
        "green": "#39c98a", "green_dark": "#173b32", "green_border": "#26775b",
        "green_hover": "#205040", "green_pressed": "#143229", "blue": "#4777c7", "red": "#b55454",
        "blue_panel": "#263b60", "blue_text": "#b9d4ff", "red_panel": "#4b2b31", "red_text": "#ffc1c1",
        "purple_panel": "#392c50", "purple_text": "#dec8ff", "next_bg": "#293445",
        "grades": GRADE_COLORS_DARK,
    },
    "light": {
        "bg": "#eef2f6", "surface": "#ffffff", "surface_alt": "#f3f6fa", "raised": "#e2e8f0",
        "border": "#c7d1dd", "text": "#172033", "muted": "#66758a", "accent": "#a86908",
        "green": "#16835b", "green_dark": "#ddf3e9", "green_border": "#58a98a",
        "green_hover": "#cceadd", "green_pressed": "#b9dece", "blue": "#4777c7", "red": "#b55454",
        "blue_panel": "#dce8fa", "blue_text": "#244f8e", "red_panel": "#f5dfe1", "red_text": "#8d363c",
        "purple_panel": "#eadff5", "purple_text": "#67408b", "next_bg": "#e7edf5",
        "grades": GRADE_COLORS_LIGHT,
    },
}
UI = THEMES["dark"]
GRADE_COLORS = dict(GRADE_COLORS_DARK)
CHEST_COOLDOWNS = {"0": 4 * 60, "1": 6 * 60}
CHEST_COOLDOWN_NAMES = {"0": "Common chest", "1": "Blue chest"}
# Keep the installed companion protocol stable across the product rename.
COMPANION_PIPE_NAME = r"\\.\pipe\TBHStargaze.Companion.v1"
DIFFICULTY_BY_NORMAL_BOX_ID = {
    910011: "Normal", 910051: "Normal", 910101: "Normal", 910151: "Normal",
    910201: "Normal", 910301: "Normal", 910401: "Nightmare", 910501: "Nightmare",
    910651: "Hell", 910801: "Torment",
}
DIFFICULTY_NAMES = {0: "Normal", 1: "Nightmare", 2: "Hell", 3: "Torment"}
GRADE_NAMES = tuple(GRADE_COLORS)
ITEM_TYPE_NAMES = {0: "STAGEBOX", 1: "MATERIAL", 2: "GEAR", 3: "NONE"}
GEAR_TYPE_NAMES = {
    1: "SWORD", 2: "BOW", 3: "STAFF", 4: "SCEPTER", 5: "CROSSBOW", 6: "AXE",
    7: "SHIELD", 8: "ARROW", 9: "ORB", 10: "TOME", 11: "BOLT", 12: "HATCHET",
    13: "HELMET", 14: "ARMOR", 15: "GLOVES", 16: "BOOTS", 17: "AMULET",
    18: "EARING", 19: "RING", 20: "BRACER",
}


def load_catalog():
    """Full static catalog: grade, gear type and level are immutable item data."""
    catalog = {}
    for path in WIKI_CATALOG_PATHS:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            catalog = {
                str(item["id"]): {"name": (item.get("name") or {}).get("en-US", str(item["id"])),
                                  "grade": item.get("grade", ""), "type": item.get("type", ""),
                                  "gear": item.get("gear"), "level": item.get("level"), "affix": item.get("affix")}
                for item in raw if isinstance(item, dict) and item.get("id") is not None
            }
            break
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    if not catalog:
        for path in CATALOG_PATHS:
            try:
                catalog = {key: {"name": value, "grade": "", "type": "", "gear": None, "level": None}
                           for key, value in json.loads(path.read_text(encoding="utf-8")).items()}
                break
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
    try:
        live = tbh_drop_probe.read_current_item_catalog()
    except (OSError, RuntimeError, ValueError):
        live = {}
    for item_id, item in live.items():
        if item_id in catalog:
            continue
        name_key = item.get("nameKey") or ""
        base_match = re.fullmatch(r"ItemName_(\d+)", name_key)
        base_name = catalog.get(base_match.group(1), {}).get("name") if base_match else None
        grade_value = item.get("gradeValue", -1)
        catalog[item_id] = {
            "name": base_name or (name_key if name_key and not name_key.startswith("ItemName_") else f"Item {item_id}"),
            "grade": GRADE_NAMES[grade_value] if 0 <= grade_value < len(GRADE_NAMES) else "",
            "type": ITEM_TYPE_NAMES.get(item.get("typeValue"), ""),
            "gear": GEAR_TYPE_NAMES.get(item.get("gearValue")),
            "level": item.get("level") or None,
            "affix": None,
        }
    return catalog


def load_watch_list(catalog, storage=None):
    if storage is not None:
        try:
            return {value for value in storage.get_watch_items() if value in catalog}
        except StorageError:
            pass
    try:
        values = json.loads(WATCH_LIST_PATH.read_text(encoding="utf-8"))
        return {str(value) for value in values if str(value) in catalog}
    except (OSError, json.JSONDecodeError):
        return set()


def load_chest_cooldowns(storage=None):
    """Persist only the locally observed chest state used by the Ready column."""
    empty = {"seen": {"0": [], "1": []}, "started_at": {}}
    try:
        value = (storage.get_json("chest_cooldowns") if storage is not None
                 else json.loads(CHEST_COOLDOWN_PATH.read_text(encoding="utf-8")))
        if not isinstance(value, dict):
            return empty
        seen = value.get("seen", {})
        started_at = value.get("started_at", {})
        return {
            "seen": {group: [str(item) for item in seen.get(group, [])][-300:] for group in CHEST_COOLDOWNS},
            "started_at": {group: float(started_at[group]) for group in CHEST_COOLDOWNS if group in started_at},
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError, StorageError):
        return empty


def load_cube_settings(storage=None):
    try:
        value = (storage.get_json("cube_settings") if storage is not None
                 else json.loads(CUBE_SETTINGS_PATH.read_text(encoding="utf-8")))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError, StorageError):
        return {}


def load_ui_settings(storage=None):
    try:
        value = (storage.get_json("ui_preferences") if storage is not None
                 else json.loads(UI_SETTINGS_PATH.read_text(encoding="utf-8")))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError, StorageError):
        return {}


def select_theme_palette(name):
    """Select the shared palette before creating or restyling Tk widgets."""
    global UI
    UI = THEMES[name if name in THEMES else "dark"]
    GRADE_COLORS.clear()
    GRADE_COLORS.update(UI["grades"])


def box_unique_id(box):
    """Return the decoded BoxData unique chest key, if this is a chest instance."""
    value = box.get("obscuredItemKey") or box.get("itemKey")
    try:
        return str(int(str(value)))
    except (TypeError, ValueError):
        return None


def live_reward_by_chest_id(queues):
    """Index loaded BoxData by its chest key across all runtime box dictionaries."""
    rewards = {}
    for dictionary in queues.values():
        for group, rows in dictionary.get("groups", {}).items():
            for box in rows:
                unique_id = box_unique_id(box)
                if unique_id and unique_id not in rewards:
                    rewards[unique_id] = (group, box)
    return rewards


def live_stage_label(stage):
    """Human-readable stage context from the current stage's immutable box tier."""
    if not stage or stage.get("act", 0) <= 0 or stage.get("stage", 0) <= 0:
        return "Live stage: —"
    difficulty = DIFFICULTY_NAMES.get(stage.get("difficulty"), "") or DIFFICULTY_BY_NORMAL_BOX_ID.get(stage.get("normalBoxId"), "")
    return f"Live stage: {difficulty + ' ' if difficulty else ''}{stage['act']}-{stage['stage']}"


def clear_tree(tree):
    """Tk raises an error for Treeview.delete() with no item arguments."""
    children = tree.get_children()
    if children:
        tree.delete(*children)


def send_companion_command(command):
    """Send one opt-in command to the local BepInEx companion, if it is loaded."""
    if sys.platform != "win32":
        return False, "Auto Unbox requires Windows."
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.WriteFile.argtypes = (
        wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    )
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateFileW(
        COMPANION_PIPE_NAME, 0x40000000, 0, None, 3, 0, None  # GENERIC_WRITE, OPEN_EXISTING
    )
    invalid_handle = wintypes.HANDLE(-1).value
    if handle == invalid_handle:
        return False, (
            "Auto Unbox companion is not active.\n\n"
            "Close Task Bar Hero completely and open it again. The companion can only load when the game starts."
        )
    try:
        message = (command.strip() + "\n").encode("utf-8")
        written = wintypes.DWORD(0)
        ok = kernel32.WriteFile(handle, message, len(message), ctypes.byref(written), None)
        if not ok or written.value != len(message):
            return False, "Could not send the command to the companion."
        return True, ""
    finally:
        kernel32.CloseHandle(handle)


class DropViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TBH Astrarium — Drop Prediction")
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        window_width = min(1180, max(920, screen_width - 48))
        window_height = min(760, max(580, screen_height - 88))
        self.geometry(
            f"{window_width}x{window_height}+{max(0, (screen_width-window_width)//2)}+"
            f"{max(0, (screen_height-window_height)//2)}"
        )
        self.minsize(920, 580)
        self.storage = None
        self.storage_notice = ""
        self._storage_finalized = False
        try:
            # Let storage perform the one-time product rename migration at the
            # default location. Tests and portable overrides still use their
            # explicitly supplied database path.
            self.storage = TBHStorage() if DATABASE_PATH == default_storage_path() else TBHStorage(DATABASE_PATH)
            self.storage.migrate_legacy(
                watch_paths=(LEGACY_WATCH_LIST_PATH, WATCH_LIST_PATH),
                chest_paths=(LEGACY_CHEST_COOLDOWN_PATH, CHEST_COOLDOWN_PATH),
                cube_paths=(LEGACY_CUBE_SETTINGS_PATH, CUBE_SETTINGS_PATH),
            )
            if self.storage.recovered_from_backup:
                self.storage_notice = "User data was recovered from the local database backup."
        except StorageError as error:
            self.storage_notice = f"Local database unavailable; using JSON backup: {error}"
        ui_settings = load_ui_settings(self.storage)
        self.theme_name = ui_settings.get("theme", "dark")
        if self.theme_name not in THEMES:
            self.theme_name = "dark"
        select_theme_palette(self.theme_name)
        self.theme_button_text = tk.StringVar(value=f"Theme  {self.theme_name.upper()}")
        self.catalog = load_catalog()
        self.watched_ids = load_watch_list(self.catalog, self.storage)
        self.chest_cooldowns = load_chest_cooldowns(self.storage)
        self.chest_cooldown_display = {group: "Ready" for group in CHEST_COOLDOWNS}
        self.auto_unbox_enabled = False
        self.auto_unbox_text = tk.StringVar(value="Auto Unbox  OFF")
        self.auto_stash_text = tk.StringVar(value="Auto Stash  OFF")
        self.auto_stash_enabled = False
        self.auto_stash_paused = False
        self.auto_stash_count = 0
        self.stash_page_buttons = []
        self.stash_page_status = tk.StringVar(value="Ready")
        self.stash_page_in_flight = False
        self.stash_active_page = None
        self._closing = False
        self.auto_stash = AutoStashController(
            bundled_path("agents/autostash.js"), user_data_path("tbh_autostash.jsonl"), self.catalog)
        self.cube = CubeController(bundled_path("agents/cube.js"), user_data_path("tbh_cube.jsonl"), self.catalog)
        self.cube_dialog = None
        self.cube_status = tk.StringVar(value="Auto Combine / Alchemy: Off")
        self.cube_button_text = tk.StringVar(value="Combine / Alchemy")
        self.cube_combine = tk.BooleanVar(value=False)
        self.cube_tier_options = {}
        self.cube_tier_combos = [None, None, None]
        saved = load_cube_settings(self.storage)
        old_tier = saved.get("combineTier") if type(saved.get("combineTier")) is int else None
        saved_tiers = saved.get("categoryTiers") if isinstance(saved.get("categoryTiers"), dict) else {}
        saved_grades = saved.get("categoryGrades") if isinstance(saved.get("categoryGrades"), dict) else {}
        saved_enabled = saved.get("categoryEnabled") if isinstance(saved.get("categoryEnabled"), dict) else {}
        saved_excluded = saved.get("combineExcludedIds") if isinstance(saved.get("combineExcludedIds"), list) else []
        self.cube_excluded_ids = {str(value) for value in saved_excluded if str(value) in self.catalog}
        self._update_auto_stash_protection()
        self.cube_exclude_button_text = tk.StringVar(value=f"Excluded items ({len(self.cube_excluded_ids)})")
        self.cube_exclude_dialog = None
        self.cube_exclude_query = tk.StringVar()
        self.cube_exclude_available = None
        self.cube_exclude_matches = []
        self.cube_exclude_tree = None
        self.cube_exclude_tree_ids = {}
        self.cube_saved_tiers = {
            i: saved_tiers.get(str(i), old_tier) if type(saved_tiers.get(str(i), old_tier)) is int else None
            for i in range(3)
        }
        self.cube_category_enabled = [
            tk.BooleanVar(value=bool(saved_enabled.get(str(i), i != 1))) for i in range(3)
        ]
        self.cube_category_grades = []
        for category in range(3):
            grades = saved_grades.get(str(category), [1, 2])
            if not isinstance(grades, list):
                grades = [1, 2]
            self.cube_category_grades.append([
                tk.BooleanVar(value=grade in grades) for grade in range(9)
            ])
        self.cube_category_tiers = [tk.StringVar(value="Choose synthesis level") for _ in range(3)]
        self.cube_alchemy = tk.BooleanVar(value=False)
        self.cube_gear = tk.StringVar(value="Ignore")
        self.cube_material = tk.StringVar(value="Ignore")
        self.cube_preview_tree = None
        self._owned_chests_seeded = False
        self._prediction_heads = {}
        self._prediction_stage_marker = None
        self.watch_option_ids = {}
        for item_id, item in self.catalog.items():
            details = []
            if item.get("type") == "GEAR":
                details.append(f"{(item.get('gear') or 'Gear').title()} Lv.{item.get('level') or '?'}")
            if item.get("affix"):
                details.append(item["affix"])
            label = " · ".join([
                item["name"], (item.get("grade") or "Unknown").title(), *details, f"#{item_id}",
            ])
            self.watch_option_ids[label] = item_id
        self.status = tk.StringVar(value="Connecting to TaskBarHero.exe…")
        self.stage_context = tk.StringVar(value="Stage: —")
        self.trees = {}
        self.count_labels = {}
        self.queue_trees = {}
        self.queue_count_labels = {}
        self.prediction_row_item_ids = {}
        self.watch_row_item_ids = {}
        self.watch_query = tk.StringVar()
        self.watch_combo = None
        self.watch_suggestions = None
        self.watch_suggestion_popup = None
        self.watch_tree = None
        self.watch_dialog = None
        self.watch_button_text = tk.StringVar()
        self.latest_queues = None
        self.latest_snapshot = None
        self._update_watch_button_text()
        self.queue_summary = tk.StringVar(value="")
        self.last_next = {}
        self.notice = tk.StringVar(value="")
        if self.storage_notice:
            self.notice.set(self.storage_notice)
        self._notice_after = None
        self._configure_style()
        self._build()
        self.after_idle(lambda: self._set_titlebar_theme(self))
        self.after(250, lambda: self._set_titlebar_theme(self))
        self.protocol("WM_DELETE_WINDOW", self.close_viewer)
        self.refresh()
        self.after(200, self._poll_auto_stash)

    def _configure_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        self.option_add("*Font", "{Segoe UI} 9")
        self.option_add("*TCombobox*Listbox.background", UI["surface_alt"])
        self.option_add("*TCombobox*Listbox.foreground", UI["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", UI["raised"])
        self.option_add("*TCombobox*Listbox.selectForeground", UI["text"])
        style.configure("TFrame", background=UI["bg"])
        style.configure("App.TFrame", background=UI["bg"])
        style.configure("Card.TFrame", background=UI["surface"], bordercolor=UI["border"], relief="solid", borderwidth=1)
        style.configure("Header.TFrame", background=UI["surface"])
        style.configure("Header.TLabel", background=UI["surface"], foreground=UI["accent"], font=("Segoe UI Semibold", 18))
        style.configure("HeaderSmall.TLabel", background=UI["surface"], foreground=UI["muted"], font=("Segoe UI", 9))
        style.configure("Stage.TLabel", background=UI["raised"], foreground=UI["text"], font=("Segoe UI Semibold", 9), padding=(10, 5))
        style.configure("Hint.TLabel", background=UI["surface"], foreground=UI["muted"], font=("Segoe UI", 9))
        style.configure("Live.TLabel", background=UI["surface"], foreground=UI["green"], font=("Segoe UI Semibold", 9))
        style.configure("Muted.TLabel", background=UI["bg"], foreground=UI["muted"], font=("Segoe UI", 9))
        style.configure("Notice.TLabel", background=UI["bg"], foreground=UI["green"], font=("Segoe UI Semibold", 9))
        style.configure("Status.TLabel", background=UI["surface"], foreground=UI["muted"], font=("Segoe UI", 9))
        style.configure("Blue.Panel.TLabel", background=UI["blue_panel"], foreground=UI["blue_text"], font=("Segoe UI Semibold", 10), anchor="w", padding=(12, 8))
        style.configure("Red.Panel.TLabel", background=UI["red_panel"], foreground=UI["red_text"], font=("Segoe UI Semibold", 10), anchor="w", padding=(12, 8))
        style.configure("Purple.Panel.TLabel", background=UI["purple_panel"], foreground=UI["purple_text"], font=("Segoe UI Semibold", 10), anchor="w", padding=(12, 8))
        style.configure("TLabel", background=UI["bg"], foreground=UI["text"])
        style.configure("TLabelframe", background=UI["surface"], foreground=UI["text"], bordercolor=UI["border"], relief="solid")
        style.configure("TLabelframe.Label", background=UI["surface"], foreground=UI["text"], font=("Segoe UI Semibold", 9))
        style.configure("TCheckbutton", background=UI["surface"], foreground=UI["text"], indicatorbackground=UI["raised"], indicatormargin=4)
        style.map("TCheckbutton", background=[("active", UI["surface"])], foreground=[("disabled", UI["muted"]), ("active", UI["text"])])
        for check_style, padding, font in (
            ("Switch.TCheckbutton", (10, 5), ("Segoe UI Semibold", 9)),
            ("Chip.TCheckbutton", (8, 4), ("Segoe UI", 9)),
        ):
            style.layout(check_style, [("Checkbutton.padding", {"sticky": "nswe", "children": [
                ("Checkbutton.label", {"sticky": "nswe"}),
            ]})])
            style.configure(check_style, background=UI["surface_alt"], foreground=UI["muted"],
                            bordercolor=UI["border"], borderwidth=1, relief="solid", padding=padding,
                            font=font, anchor="center")
            style.map(check_style,
                      background=[("selected", UI["green_dark"]), ("active", UI["raised"])],
                      foreground=[("selected", UI["green"]), ("active", UI["text"])],
                      bordercolor=[("selected", UI["green_border"]), ("active", UI["muted"])])
        style.configure("Header.TButton", background=UI["surface_alt"], foreground=UI["muted"],
                        bordercolor=UI["border"], padding=(9, 5), font=("Segoe UI Semibold", 9))
        style.map("Header.TButton", background=[("active", UI["raised"]), ("pressed", UI["border"])],
                  foreground=[("active", UI["text"])])
        style.configure("Toolbar.TButton", background=UI["surface_alt"], foreground=UI["text"], bordercolor=UI["border"], padding=(10, 7), font=("Segoe UI Semibold", 9))
        style.map("Toolbar.TButton", background=[("active", UI["raised"]), ("pressed", UI["border"])], foreground=[("disabled", UI["muted"])])
        style.configure("Active.TButton", background=UI["green_dark"], foreground=UI["green"], bordercolor=UI["green_border"], padding=(10, 7), font=("Segoe UI Semibold", 9))
        style.map("Active.TButton", background=[("active", UI["green_hover"]), ("pressed", UI["green_pressed"])], foreground=[("disabled", UI["muted"])])
        style.configure("Small.TButton", background=UI["surface_alt"], foreground=UI["text"], bordercolor=UI["border"], padding=(8, 5), font=("Segoe UI", 9))
        style.map("Small.TButton", background=[("active", UI["raised"]), ("pressed", UI["border"])], foreground=[("disabled", UI["muted"])])
        style.configure("TButton", background=UI["surface_alt"], foreground=UI["text"], bordercolor=UI["border"], padding=(8, 5), font=("Segoe UI", 9))
        style.map("TButton", background=[("active", UI["raised"]), ("pressed", UI["border"])], foreground=[("disabled", UI["muted"])])
        style.configure("TNotebook", background=UI["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", background=UI["surface"], foreground=UI["muted"], padding=(15, 8), font=("Segoe UI Semibold", 9), borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", UI["raised"]), ("active", UI["surface_alt"])], foreground=[("selected", UI["text"]), ("active", UI["text"])])
        style.configure("TCombobox", fieldbackground=UI["surface_alt"], background=UI["surface_alt"], foreground=UI["text"], arrowcolor=UI["muted"], bordercolor=UI["border"], lightcolor=UI["border"], darkcolor=UI["border"])
        style.map("TCombobox", fieldbackground=[("readonly", UI["surface_alt"])], foreground=[("readonly", UI["text"])])
        style.configure("TEntry", fieldbackground=UI["surface_alt"], foreground=UI["text"], insertcolor=UI["text"], bordercolor=UI["border"])
        style.configure("TPanedwindow", background=UI["bg"])
        style.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"}),
        ]})])
        style.configure("Vertical.TScrollbar", width=10, background=UI["raised"], troughcolor=UI["surface"],
                        bordercolor=UI["surface"], darkcolor=UI["raised"], lightcolor=UI["raised"],
                        relief="flat", troughrelief="flat")
        style.map("Vertical.TScrollbar", background=[("active", UI["muted"]), ("pressed", UI["muted"])])
        style.configure("Drop.Treeview", font=("Segoe UI", 10), rowheight=28, background=UI["surface"], fieldbackground=UI["surface"], foreground=UI["text"], borderwidth=0)
        style.configure("Drop.Treeview.Heading", font=("Segoe UI Semibold", 9), background=UI["surface_alt"], foreground=UI["muted"], relief="flat", padding=(5, 7))
        style.map("Drop.Treeview", background=[("selected", UI["raised"])], foreground=[("selected", UI["text"])])
        style.map("Drop.Treeview.Heading", background=[("active", UI["raised"])])

    def _set_titlebar_theme(self, window):
        """Ask Windows to match a top-level title bar to the active app theme."""
        if sys.platform != "win32" or not window or not window.winfo_exists():
            return
        try:
            window.update_idletasks()
            enabled = ctypes.c_int(1 if self.theme_name == "dark" else 0)
            dwmapi = ctypes.WinDLL("dwmapi")
            user32 = ctypes.WinDLL("user32")
            user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
            user32.GetAncestor.restype = wintypes.HWND
            dwmapi.DwmSetWindowAttribute.argtypes = (
                wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
            dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
            widget_handle = wintypes.HWND(window.winfo_id())
            top_handle = user32.GetAncestor(widget_handle, 2) or widget_handle
            for attribute in (20, 19):
                result = dwmapi.DwmSetWindowAttribute(
                    top_handle, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled))
                if result == 0:
                    break
        except (AttributeError, OSError, tk.TclError):
            pass

    @staticmethod
    def _configure_listbox_theme(listbox, surface=None):
        if not listbox or not listbox.winfo_exists():
            return
        listbox.configure(
            background=surface or UI["surface_alt"], foreground=UI["text"],
            selectbackground=UI["raised"], selectforeground=UI["text"],
            highlightbackground=UI["border"], highlightcolor=UI["accent"],
        )

    def _apply_theme(self, name, persist=True, announce=True):
        self.theme_name = name if name in THEMES else "dark"
        select_theme_palette(self.theme_name)
        self.theme_button_text.set(f"Theme  {self.theme_name.upper()}")
        self._configure_style()
        self.configure(background=UI["bg"])

        dialogs = (
            self.cube_dialog, self.cube_exclude_dialog, self.watch_dialog,
            self.watch_suggestion_popup,
        )
        for dialog in dialogs:
            if dialog and dialog.winfo_exists():
                dialog.configure(background=UI["bg"])
                self.after_idle(lambda target=dialog: self._set_titlebar_theme(target))
                self.after(100, lambda target=dialog: self._set_titlebar_theme(target))
        self._configure_listbox_theme(self.cube_exclude_available, UI["surface"])
        self._configure_listbox_theme(self.watch_suggestions)

        for tree in (*self.trees.values(), *self.queue_trees.values(),
                     self.watch_tree, self.cube_exclude_tree, self.cube_preview_tree):
            if not tree or not tree.winfo_exists():
                continue
            for grade, color in GRADE_COLORS.items():
                tree.tag_configure(f"grade_{grade}", foreground=color)
        for tree in self.trees.values():
            if tree and tree.winfo_exists():
                tree.tag_configure("next", background=UI["next_bg"], font=("Segoe UI Semibold", 10))
                tree.tag_configure("later", foreground=UI["muted"])

        self.after_idle(lambda: self._set_titlebar_theme(self))
        self.after(100, lambda: self._set_titlebar_theme(self))
        if persist:
            try:
                self._persist_json_setting("ui_preferences", {"theme": self.theme_name}, UI_SETTINGS_PATH)
            except StorageError as error:
                self.show_notice(f"Cannot save theme: {error}")
                return
        if announce:
            self.show_notice(f"{self.theme_name.title()} theme enabled.")

    def toggle_theme(self):
        self._apply_theme("light" if self.theme_name == "dark" else "dark")

    def _build(self):
        self.configure(background=UI["bg"])
        header = ttk.Frame(self, style="Header.TFrame", padding=(18, 12))
        header.pack(fill="x")
        ttk.Label(header, text="TBH Astrarium", style="Header.TLabel").pack(side="left")
        ttk.Label(header, text="LIVE DROP COMPANION", style="HeaderSmall.TLabel").pack(side="left", padx=(14, 0), pady=(7, 0))
        ttk.Label(header, textvariable=self.stage_context, style="Stage.TLabel").pack(side="right")
        self.theme_button = ttk.Button(header, textvariable=self.theme_button_text, style="Header.TButton",
                                       command=self.toggle_theme)
        self.theme_button.pack(side="right", padx=(0, 8))

        info = ttk.Frame(self, style="Card.TFrame", padding=(12, 8))
        info.pack(fill="x", padx=12, pady=(10, 8))
        ttk.Label(info, text="ⓘ", style="Hint.TLabel", foreground=UI["accent"]).pack(side="left", padx=(0, 7))
        ttk.Label(info, text="Ready marks the next eligible chest roll. Rewards are not guaranteed.",
                  style="Hint.TLabel").pack(side="left")

        controls = ttk.Frame(self, style="Card.TFrame", padding=(10, 9))
        controls.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Label(controls, text="●  LIVE MEMORY", style="Live.TLabel").pack(side="left", padx=(2, 12))
        actions = ttk.Frame(controls, style="Card.TFrame")
        actions.pack(side="right")
        self.auto_unbox_button = ttk.Button(actions, textvariable=self.auto_unbox_text, style="Toolbar.TButton",
                                            command=self.toggle_auto_unbox)
        self.auto_unbox_button.pack(side="left", padx=3)
        self.auto_stash_button = ttk.Button(actions, textvariable=self.auto_stash_text,
                                           style="Toolbar.TButton", command=self.toggle_auto_stash)
        self.auto_stash_button.pack(side="left", padx=3)
        self.cube_button = ttk.Button(actions, textvariable=self.cube_button_text, style="Toolbar.TButton",
                                      command=self.show_cube_dialog)
        self.cube_button.pack(side="left", padx=3)
        ttk.Button(actions, textvariable=self.watch_button_text, style="Toolbar.TButton",
                   command=self.show_watch_dialog).pack(side="left", padx=(3, 0))

        stash_shortcuts = ttk.Frame(self, style="Card.TFrame", padding=(10, 7))
        stash_shortcuts.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Label(stash_shortcuts, text="STASH", style="Live.TLabel").pack(side="left", padx=(2, 10))
        page_names = (
            "1  Keepers", "2  Engraving", "3  Decor Arcane+", "4  Decor Immortal",
            "5  Decor ≤Legendary", "6  Crafting", "7  Accessories",
        )
        for page, label in enumerate(page_names, 1):
            button = ttk.Button(
                stash_shortcuts, text=label, style="Small.TButton",
                command=lambda value=page: self.open_stash_page(value),
            )
            button.pack(side="left", padx=(0, 5))
            self.stash_page_buttons.append(button)
        ttk.Label(stash_shortcuts, textvariable=self.stash_page_status,
                  style="Hint.TLabel").pack(side="right", padx=(8, 2))

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        prediction_tab = ttk.Frame(notebook, style="App.TFrame")
        queue_tab = ttk.Frame(notebook, style="App.TFrame")
        notebook.add(prediction_tab, text="Drop Prediction")
        notebook.add(queue_tab, text="My Chest Queue")

        panels = ttk.Frame(prediction_tab, style="App.TFrame", padding=(2, 0, 2, 2))
        panels.pack(fill="both", expand=True)
        panels.columnconfigure(0, weight=1)
        panels.columnconfigure(1, weight=1)
        panels.rowconfigure(0, weight=1)
        self._create_panel(panels, "0", 0, "Blue.Panel.TLabel")
        self._create_panel(panels, "1", 1, "Red.Panel.TLabel")

        self._create_queue_tab(queue_tab)

        ttk.Label(self, textvariable=self.notice, anchor="center", style="Notice.TLabel", padding=(8, 3)).pack(fill="x")
        ttk.Label(self, textvariable=self.status, anchor="w", style="Status.TLabel", padding=(12, 6)).pack(fill="x")

    def _style_dialog(self, dialog, width=None, height=None, minimum=None):
        dialog.configure(background=UI["bg"])
        if width and height:
            actual_width = min(width, max(700, self.winfo_screenwidth() - 80))
            actual_height = min(height, max(460, self.winfo_screenheight() - 110))
            x = max(0, (self.winfo_screenwidth() - actual_width) // 2)
            y = max(0, (self.winfo_screenheight() - actual_height) // 2)
            dialog.geometry(f"{actual_width}x{actual_height}+{x}+{y}")
        if minimum:
            dialog.minsize(*minimum)
        dialog.after_idle(lambda target=dialog: self._set_titlebar_theme(target))
        dialog.after(100, lambda target=dialog: self._set_titlebar_theme(target))

    def _create_queue_tab(self, parent):
        ttk.Label(parent, text="Only unopened Normal and Stage Boss chests are shown here. Rewards are decoded from live memory.",
                  style="Hint.TLabel", padding=(10, 7)).pack(fill="x", padx=2, pady=(4, 5))
        ttk.Label(parent, textvariable=self.queue_summary, style="Live.TLabel",
                  padding=(8, 3)).pack(fill="x")
        panels = ttk.Frame(parent, style="App.TFrame", padding=(4, 2, 4, 4))
        panels.pack(fill="both", expand=True)
        for column in range(2):
            panels.columnconfigure(column, weight=1)
        panels.rowconfigure(0, weight=1)
        for column, (group, label_style) in enumerate((
            ("0", "Blue.Panel.TLabel"), ("1", "Red.Panel.TLabel"),
        )):
            self._create_owned_chest_panel(panels, group, column, label_style)

    def _create_owned_chest_panel(self, parent, group, column, label_style):
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=0, column=column, sticky="nsew", padx=(0, 4) if column < 2 else 0)
        title = ttk.Label(frame, text=f"{CHEST_TYPE_NAMES[group]} Chests — 0", style=label_style)
        title.pack(fill="x")
        self.queue_count_labels[group] = title
        # Chest/reward IDs and per-row quantity are implementation details.  The
        # panel title already gives chest count; keep this view player-facing.
        columns = ("item_name", "grade", "details")
        tree = ttk.Treeview(frame, columns=columns, show="headings", style="Drop.Treeview")
        for col, label, width, anchor in (
            ("item_name", "Reward", 190, "w"), ("grade", "Grade", 95, "center"),
            ("details", "Gear / Level", 120, "w"),
        ):
            tree.heading(col, text=label)
            tree.column(col, width=width, minwidth=35, anchor=anchor, stretch=col == "item_name")
        # Use the exact same foreground-only grade tags as Drop Prediction.
        # A neutral row background preserves the rarity colour at a glance.
        for grade, color in GRADE_COLORS.items():
            tree.tag_configure(f"grade_{grade}", foreground=color)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=(0, 1))
        scroll.pack(side="right", fill="y", pady=(0, 1))
        self.queue_trees[group] = tree

    def _update_watch_button_text(self):
        self.watch_button_text.set(f"Watch List  {len(self.watched_ids)}")

    def toggle_auto_unbox(self):
        desired = not self.auto_unbox_enabled
        ok, error = send_companion_command("autounbox:on" if desired else "autounbox:off")
        if not ok:
            self.show_notice(error)
            messagebox.showwarning("Auto Unbox unavailable", error, parent=self)
            return
        self.auto_unbox_enabled = desired
        self.auto_unbox_text.set("Auto Unbox  ON" if desired else "Auto Unbox  OFF")
        self.auto_unbox_button.configure(style="Active.TButton" if desired else "Toolbar.TButton")
        self.show_notice("Auto Unbox enabled." if desired else "Auto Unbox disabled.")

    def _persist_json_setting(self, key, value, legacy_path):
        """Save to SQLite first and keep an atomic, human-readable JSON copy."""
        database_saved = False
        database_error = None
        if self.storage is not None:
            try:
                self.storage.set_json(key, value)
                database_saved = True
            except StorageError as error:
                database_error = error
        try:
            atomic_write_json(legacy_path, value)
            json_saved = True
        except OSError:
            json_saved = False
        if not database_saved and not json_saved:
            raise StorageError(str(database_error or f"Cannot write {legacy_path}"))
        if database_error and json_saved:
            self.show_notice("Local database unavailable; changes were saved to the JSON backup.")

    def _save_chest_cooldowns(self):
        try:
            self._persist_json_setting("chest_cooldowns", self.chest_cooldowns, CHEST_COOLDOWN_PATH)
        except StorageError as error:
            self.show_notice(f"Cannot save chest timers: {error}")

    def toggle_auto_stash(self):
        if self.auto_stash.running:
            self.auto_stash_enabled = False
            self.auto_stash.stop()
            self.auto_stash_text.set("Auto Stash  STOPPING…")
            self.auto_stash_button.configure(style="Toolbar.TButton")
            self.auto_stash_button.configure(state="disabled")
        else:
            self._update_auto_stash_protection()
            self.auto_stash_paused = False
            self.auto_stash_count = 0
            self.auto_stash_text.set("Auto Stash  STARTING…")
            self.auto_stash_button.configure(state="disabled")
            self.auto_stash.start()

    def _set_stash_page_buttons(self, state):
        for button in self.stash_page_buttons:
            if button.winfo_exists():
                button.configure(state=state)

    def _show_active_stash_page(self, page=None):
        self.stash_active_page = page
        for index, button in enumerate(self.stash_page_buttons, 1):
            if button.winfo_exists():
                button.configure(style="Active.TButton" if index == page else "Small.TButton")

    def open_stash_page(self, page):
        if self.stash_page_in_flight:
            return
        self.stash_page_in_flight = True
        self._set_stash_page_buttons("disabled")
        self.stash_page_status.set(f"Opening {page}…")
        try:
            self.auto_stash.open_page(page)
        except (RuntimeError, ValueError) as error:
            self.stash_page_in_flight = False
            self._set_stash_page_buttons("normal")
            self.stash_page_status.set("Unavailable")
            self.show_notice(str(error))
            return
        self.show_notice(f"Opening stash page {page} in Task Bar Hero…")

    def show_cube_dialog(self):
        if self.cube_dialog and self.cube_dialog.winfo_exists():
            self.cube_dialog.lift()
            return
        dialog = tk.Toplevel(self)
        self.cube_dialog = dialog
        dialog.title("Auto Combine / Auto Alchemy")
        self._style_dialog(dialog, 1080, 570, (920, 540))
        dialog.transient(self)
        outer = ttk.Frame(dialog, padding=10)
        outer.pack(fill="both", expand=True)
        combine = ttk.LabelFrame(outer, text="Auto Combine · 9 items per batch", padding=(9, 7))
        combine.pack(fill="x", pady=(0, 6))
        ttk.Checkbutton(combine, text="Auto Combine", variable=self.cube_combine,
                        style="Switch.TCheckbutton", command=self._cube_filters_changed).pack(anchor="w")
        for category, label in [(0, "Gear"), (1, "Accessories"), (2, "Materials")]:
            group = ttk.LabelFrame(combine, text=label, padding=(7, 4))
            group.pack(fill="x", pady=(4, 0))
            controls = ttk.Frame(group)
            controls.pack(fill="x")
            ttk.Checkbutton(controls, text="Use category", variable=self.cube_category_enabled[category],
                            style="Switch.TCheckbutton",
                            command=self._cube_filters_changed).pack(side="left")
            if category != 2:
                ttk.Label(controls, text="Synthesis:").pack(side="left", padx=(18, 6))
                combo = ttk.Combobox(controls, textvariable=self.cube_category_tiers[category],
                                     state="readonly", width=37)
                combo.pack(side="left")
                combo.bind("<<ComboboxSelected>>", lambda _event: self._cube_filters_changed())
                self.cube_tier_combos[category] = combo
            else:
                ttk.Label(controls, text="Materials have no item level.").pack(side="left", padx=(18, 6))
            grades = ttk.Frame(group)
            grades.pack(fill="x", pady=(3, 0))
            ttk.Label(grades, text="Rarity:").pack(side="left", padx=(0, 7))
            for grade, name in enumerate(list(GRADE_COLORS)[:9]):
                ttk.Checkbutton(grades, text=name.title(), variable=self.cube_category_grades[category][grade],
                                style="Chip.TCheckbutton", command=self._cube_filters_changed).pack(side="left", padx=2)
        actions = ttk.Frame(combine)
        actions.pack(fill="x", pady=(5, 0))
        ttk.Button(actions, text="Refresh unlocked levels", command=self._refresh_cube_tiers).pack(side="left")
        ttk.Button(actions, textvariable=self.cube_exclude_button_text,
                   command=self._show_cube_exclusion_dialog).pack(side="left", padx=(8, 0))
        ttk.Label(actions, text="Gear and Accessories keep separate synthesis levels; every category keeps separate rarity.").pack(side="left", padx=12)
        self._refresh_cube_tiers()
        alchemy = ttk.LabelFrame(outer, text="Auto Alchemy · consume selected items", padding=(9, 7))
        alchemy.pack(fill="x", pady=(0, 6))
        ttk.Checkbutton(alchemy, text="Auto Alchemy", variable=self.cube_alchemy,
                        style="Switch.TCheckbutton", command=self._cube_filters_changed).grid(
                            row=0, column=0, columnspan=4, sticky="w")
        options = ["Ignore"] + [f"{x.title()} & below" for x in GRADE_COLORS]
        for col, label, var in [(0, "Gear / Accessories:", self.cube_gear), (2, "Materials:", self.cube_material)]:
            ttk.Label(alchemy, text=label).grid(row=1, column=col, padx=5, pady=8)
            combo = ttk.Combobox(alchemy, textvariable=var, values=options, state="readonly", width=22)
            combo.grid(row=1, column=col+1, padx=5)
            combo.bind("<<ComboboxSelected>>", lambda _event: self._cube_filters_changed())
        ttk.Label(outer, text="Inventory + 7 stash pages · Protected and excluded items are skipped · Combine runs before Alchemy.",
                  style="Muted.TLabel").pack(anchor="w")
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="Apply / Start", command=self._cube_filters_changed).pack(side="left")
        ttk.Button(buttons, text="Stop", command=self.cube.stop).pack(side="left")
        ttk.Label(buttons, textvariable=self.cube_status).pack(side="left", padx=12)

    def _show_cube_exclusion_dialog(self):
        if self.cube_exclude_dialog and self.cube_exclude_dialog.winfo_exists():
            self.cube_exclude_dialog.lift()
            self.cube_exclude_dialog.focus_force()
            return
        dialog = tk.Toplevel(self.cube_dialog)
        self.cube_exclude_dialog = dialog
        dialog.title("Items excluded from Auto Combine")
        self._style_dialog(dialog, 900, 500, (760, 400))
        dialog.transient(self.cube_dialog)
        dialog.protocol("WM_DELETE_WINDOW", self._close_cube_exclusion_dialog)
        outer = ttk.Frame(dialog, padding=10)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Select an item name to keep every copy of that item out of Auto Combine. Auto Alchemy settings are unchanged.").pack(anchor="w")
        search = ttk.Frame(outer)
        search.pack(fill="x", pady=(8, 5))
        ttk.Label(search, text="Search item:").pack(side="left")
        entry = ttk.Entry(search, textvariable=self.cube_exclude_query, width=55)
        entry.pack(side="left", padx=6)
        entry.bind("<KeyRelease>", self._filter_cube_exclusion_options)
        ttk.Button(search, text="Add selected", command=self._add_cube_exclusion).pack(side="left")
        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)
        available_frame = ttk.LabelFrame(panes, text="Available items", padding=5)
        excluded_frame = ttk.LabelFrame(panes, text="Excluded from Auto Combine", padding=5)
        panes.add(available_frame, weight=1)
        panes.add(excluded_frame, weight=1)
        available = tk.Listbox(available_frame, activestyle="none", exportselection=False,
                               font=("Segoe UI", 9), background=UI["surface"], foreground=UI["text"],
                               selectbackground=UI["raised"], selectforeground=UI["text"],
                               highlightbackground=UI["border"], highlightcolor=UI["accent"], relief="flat")
        available.pack(side="left", fill="both", expand=True)
        available.bind("<Double-Button-1>", lambda _event: self._add_cube_exclusion())
        scroll = ttk.Scrollbar(available_frame, orient="vertical", command=available.yview)
        available.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.cube_exclude_available = available
        tree = ttk.Treeview(excluded_frame, columns=("item", "grade"), show="headings",
                            style="Drop.Treeview", height=8)
        tree.heading("item", text="Protected item")
        tree.heading("grade", text="Rarity")
        tree.column("item", width=260, stretch=True)
        tree.column("grade", width=90, anchor="center", stretch=False)
        tree.pack(fill="both", expand=True)
        self.cube_exclude_tree = tree
        ttk.Button(excluded_frame, text="Remove selected", command=self._remove_cube_exclusions).pack(anchor="e", pady=(5, 0))
        self._filter_cube_exclusion_options()
        self._refresh_cube_exclusions()
        entry.focus_set()

    def _close_cube_exclusion_dialog(self):
        if self.cube_exclude_dialog:
            self.cube_exclude_dialog.destroy()
        self.cube_exclude_dialog = None
        self.cube_exclude_available = None
        self.cube_exclude_tree = None
        self.cube_exclude_tree_ids = {}

    def _filter_cube_exclusion_options(self, _event=None):
        if not self.cube_exclude_available or not self.cube_exclude_available.winfo_exists():
            return
        terms = self.cube_exclude_query.get().casefold().split()
        self.cube_exclude_matches = [
            label for label, item_id in self.watch_option_ids.items()
            if item_id not in self.cube_excluded_ids
            and self.catalog.get(str(item_id), {}).get("type") in ("GEAR", "MATERIAL")
            and all(term in label.casefold() for term in terms)
        ][:200]
        self.cube_exclude_available.delete(0, tk.END)
        for label in self.cube_exclude_matches:
            self.cube_exclude_available.insert(tk.END, label)

    def _add_cube_exclusion(self):
        if not self.cube_exclude_available:
            return
        selected = self.cube_exclude_available.curselection()
        item_id = self.watch_option_ids.get(self.cube_exclude_matches[selected[0]]) if selected else None
        query = self.cube_exclude_query.get().strip()
        if item_id is None and len(self.cube_exclude_matches) == 1:
            item_id = self.watch_option_ids[self.cube_exclude_matches[0]]
        if item_id is None and query.isdigit() and query in self.catalog:
            item_id = query
        if item_id is None or self.catalog.get(str(item_id), {}).get("type") not in ("GEAR", "MATERIAL"):
            self.show_notice("Select an item to exclude from Auto Combine.")
            return
        self.cube_excluded_ids.add(str(item_id))
        self.cube_exclude_button_text.set(f"Excluded items ({len(self.cube_excluded_ids)})")
        self.cube_exclude_query.set("")
        self._filter_cube_exclusion_options()
        self._refresh_cube_exclusions()
        self._update_auto_stash_protection()
        self._cube_filters_changed()

    def _remove_cube_exclusions(self):
        if not self.cube_exclude_tree:
            return
        item_ids = [self.cube_exclude_tree_ids.get(row) for row in self.cube_exclude_tree.selection()]
        self.cube_excluded_ids.difference_update(item_id for item_id in item_ids if item_id)
        self.cube_exclude_button_text.set(f"Excluded items ({len(self.cube_excluded_ids)})")
        self._filter_cube_exclusion_options()
        self._refresh_cube_exclusions()
        self._update_auto_stash_protection()
        self._cube_filters_changed()

    def _refresh_cube_exclusions(self):
        if not self.cube_exclude_tree or not self.cube_exclude_tree.winfo_exists():
            return
        clear_tree(self.cube_exclude_tree)
        self.cube_exclude_tree_ids = {}
        for item_id in sorted(self.cube_excluded_ids,
                              key=lambda value: self.catalog[value]["name"].casefold()):
            item = self.catalog[item_id]
            row = self.cube_exclude_tree.insert("", "end", values=(
                f"{item['name']}  #{item_id}", (item.get("grade") or "—").title()))
            self.cube_exclude_tree_ids[row] = item_id

    def _refresh_cube_tiers(self):
        selected = {
            category: self.cube_tier_options.get(self.cube_category_tiers[category].get(),
                                                 self.cube_saved_tiers[category])
            for category in range(3)
        }
        try:
            options = read_synthesis_options()
        except (OSError, RuntimeError, ValueError) as error:
            self.cube_status.set("Cannot read synthesis tiers")
            self.show_notice(str(error))
            return
        self.cube_tier_options = {
            f"Lv.{x['minResultLevel']}~{x['maxResultLevel']}": x['tier'] for x in options}
        missing = False
        for category in (0, 1):
            self.cube_tier_combos[category].configure(values=list(self.cube_tier_options))
            label = next((name for name, tier in self.cube_tier_options.items()
                          if tier == selected[category]), None)
            self.cube_category_tiers[category].set(label or "Choose synthesis level")
            missing = missing or (label is None and self.cube_category_enabled[category].get())
        # Materials have no level. The agent still needs a recipe page tier to
        # drive the Cube, so use the highest unlocked one internally only.
        material_label = next(reversed(self.cube_tier_options), None)
        self.cube_category_tiers[2].set(material_label or "")
        if missing and self.cube_combine.get():
            self._cube_filters_changed()

    def _cube_filters_changed(self):
        options = ["Ignore"] + [f"{x.title()} & below" for x in GRADE_COLORS]
        category_settings = []
        invalid = []
        saved = {"categoryTiers": {}, "categoryGrades": {}, "categoryEnabled": {},
                 "combineExcludedIds": sorted(self.cube_excluded_ids, key=int)}
        for category, name in [(0, "Gear"), (1, "Accessories"), (2, "Materials")]:
            tier = (max(self.cube_tier_options.values()) if category == 2 and self.cube_tier_options
                    else self.cube_tier_options.get(self.cube_category_tiers[category].get()))
            grades = [grade for grade, value in enumerate(self.cube_category_grades[category]) if value.get()]
            selected = self.cube_category_enabled[category].get()
            enabled = self.cube_combine.get() and selected
            if enabled and (tier is None or not grades):
                invalid.append(name)
            category_settings.append({"category": category, "enabled": enabled,
                                      "tier": tier, "grades": grades})
            if category != 2:
                # A temporary read failure or newly unsupported game build
                # must not erase the user's last explicit Cube level.
                saved["categoryTiers"][str(category)] = (
                    tier if tier is not None else self.cube_saved_tiers[category]
                )
            saved["categoryGrades"][str(category)] = grades
            saved["categoryEnabled"][str(category)] = selected
            if tier is not None:
                self.cube_saved_tiers[category] = tier
        settings = {"combine": self.cube_combine.get() and not invalid and any(
                        item["enabled"] for item in category_settings),
                    "combineCategories": category_settings,
                    "alchemy": self.cube_alchemy.get(),
                    "gearMax": options.index(self.cube_gear.get()) - 1,
                    "materialMax": options.index(self.cube_material.get()) - 1,
                    "protectedIds": [int(x) for x in self.watched_ids],
                    "combineExcludedIds": [int(x) for x in self.cube_excluded_ids]}
        try:
            self._persist_json_setting("cube_settings", saved, CUBE_SETTINGS_PATH)
        except StorageError as error:
            self.show_notice(f"Cannot save Auto Combine settings: {error}")
        if invalid or (self.cube_combine.get() and not any(item["enabled"] for item in category_settings)):
            if self.cube.running:
                self.cube.stop()
            self.cube_button_text.set("Combine / Alchemy")
            self.cube_button.configure(style="Toolbar.TButton")
            self.cube_status.set("Choose rarity and synthesis level: " + ", ".join(invalid)
                                 if invalid else "Enable an Auto Combine category")
            return
        if not settings["combine"] and not settings["alchemy"]:
            if self.cube.running:
                self.cube.stop()
            self.cube_button_text.set("Combine / Alchemy")
            self.cube_button.configure(style="Toolbar.TButton")
            self.cube_status.set("Off")
            return
        self.cube_status.set("Updating…" if self.cube.running else "Connecting…")
        self.cube_button_text.set("Combine / Alchemy  ON")
        self.cube_button.configure(style="Active.TButton")
        self.cube.apply_settings(settings)

    def _poll_cube(self):
        for event in self.cube.drain():
            kind = event.get("event")
            if kind == "ready":
                self.cube_status.set("Preview only" if event.get("preview") else "Running")
            elif kind in ("preview", "scan"):
                batch = event.get("batch")
                tree = self.cube_preview_tree
                if kind == "preview" and tree and tree.winfo_exists():
                    clear_tree(tree)
                    for item in (batch or {}).get("items", []):
                        name = self.catalog.get(str(item["itemId"]), {}).get("name", str(item["itemId"]))
                        location = "Inventory" if item["source"] == 1 else f"Stash {item['slot'] // 49 + 1}"
                        tree.insert("", "end", values=(batch["mode"].title(), name, list(GRADE_COLORS)[item["grade"]].title(), location))
                if batch:
                    self.cube_status.set("Preview only · ready 9/9")
                else:
                    progress = event.get("progress") or []
                    if progress:
                        best = progress[0]
                        category = {0: "Gear", 1: "Accessories", 2: "Materials"}.get(best["category"], "Items")
                        grade = list(GRADE_COLORS)[best["grade"]].title()
                        prefix = "Preview" if kind == "preview" else "Waiting"
                        tier = best.get("tier")
                        detail = f"{min(best['count'], 9)}/9" if best['count'] < 9 else "needs suitable average level"
                        level = "" if best["category"] == 2 else f"T{tier} "
                        self.cube_status.set(f"{prefix} · {level}{category} {grade} {detail}")
                    else:
                        self.cube_status.set("Preview · no selected items" if kind == "preview" else "Waiting for selected items")
            elif kind == "processed":
                totals = event["total"]
                self.cube_status.set(f"Combined {totals['combine']} · Alchemy {totals['alchemy']}")
            elif kind in ("user_cube_opened", "yielded_to_user"):
                self.cube_status.set("Waiting · Cube is open")
            elif kind == "user_cube_closed":
                self.cube_status.set("Running")
            elif kind == "paused":
                self.cube_status.set("Paused")
                self.cube_button_text.set("Combine / Alchemy")
                self.cube_button.configure(style="Toolbar.TButton")
                self.show_notice("Combine / Alchemy: " + event.get("reason", "Game unavailable"))
            elif kind == "stopped":
                if not self.cube_status.get().startswith(("Choose", "Enable")):
                    self.cube_status.set("Off")
                self.cube_button_text.set("Combine / Alchemy")
                self.cube_button.configure(style="Toolbar.TButton")

    def _poll_auto_stash(self):
        self._poll_cube()
        for event in self.auto_stash.drain():
            kind = event.get("event")
            if kind == "ready":
                self.auto_stash_enabled = True
                self.auto_stash_text.set("Auto Stash  ON · 0")
                self.auto_stash_button.configure(state="normal", style="Active.TButton")
                pages = event.get("accessiblePages", 7)
                self.show_notice(
                    f"Auto Stash enabled — new items are routed into the assigned pages across {pages} owned pages."
                )
            elif kind == "stashed":
                self.auto_stash_count = event["total"]
                self.auto_stash_text.set(f"Auto Stash  ON · {self.auto_stash_count}")
                self.auto_stash_button.configure(style="Active.TButton")
                item = self.catalog.get(str(event["itemId"]), {})
                self.show_notice(f"Stashed: {item.get('name', 'Item')} · {self.auto_stash_count} moved this session.")
            elif kind in ("full", "status"):
                self.auto_stash_text.set("Auto Stash  WAITING")
                self.auto_stash_button.configure(style="Active.TButton")
                if kind == "full":
                    page = event.get("targetPage")
                    target = f"Assigned stash page {page}" if page else "The assigned stash page"
                    self.show_notice(f"{target} is full. The item stays in inventory until space is available.")
            elif kind == "page_opened":
                self.stash_page_in_flight = False
                self._set_stash_page_buttons("normal")
                self._show_active_stash_page(event["page"])
                self.stash_page_status.set(f"Page {event['page']} open")
                self.show_notice(f"Stash page {event['page']} is open in Task Bar Hero.")
            elif kind == "paused":
                if self.stash_page_in_flight:
                    self.stash_page_in_flight = False
                    self._set_stash_page_buttons("normal")
                    self.stash_page_status.set("Game unavailable")
                self.auto_stash_enabled = False
                self.auto_stash_paused = True
                self.auto_stash_text.set("Auto Stash  PAUSED")
                self.auto_stash_button.configure(style="Toolbar.TButton")
                self.show_notice(f"Auto Stash paused: {event.get('reason', 'Game unavailable')}")
            elif kind == "stopped":
                if self.stash_page_in_flight:
                    self.stash_page_in_flight = False
                    self._set_stash_page_buttons("normal")
                    self.stash_page_status.set("Ready")
                self.auto_stash_enabled = False
                if not self.auto_stash_paused:
                    self.auto_stash_text.set("Auto Stash  OFF")
                self.auto_stash_button.configure(state="normal", style="Toolbar.TButton")
        if self._closing:
            if not self.auto_stash.running and not self.cube.running:
                self._finalize_storage()
                self.destroy()
                return
        self.after(200, self._poll_auto_stash)

    @staticmethod
    def _format_duration(seconds):
        minutes, remainder = divmod(max(0, int(seconds)), 60)
        return f"{minutes}:{remainder:02}"

    def _observe_chest_cooldowns(self, owned_chests, prediction_heads, stage_marker):
        """Start cooldowns from a chest arrival, including auto-opened chests.

        A chest can be opened by Auto Unbox between two inventory reads.  The
        future-drop queue still advances in that case, so use a changed queue
        head as an additional arrival signal.  Stage changes only establish a
        fresh baseline and never start or reset a timer.
        """
        current = {group: set() for group in CHEST_COOLDOWNS}
        for chest in owned_chests:
            group, unique_id = chest.get("type"), chest.get("unique_id")
            if group in current and unique_id:
                current[group].add(str(unique_id))
        seen = {group: set(self.chest_cooldowns["seen"].get(group, [])) for group in CHEST_COOLDOWNS}
        changed = False
        arrivals = set()
        if self._owned_chests_seeded:
            for group, identifiers in current.items():
                if identifiers - seen[group]:
                    arrivals.add(group)
        else:
            self._owned_chests_seeded = True

        if stage_marker != self._prediction_stage_marker:
            # A new stage has its own queue view.  Do not mistake that reload
            # for a chest drop or let stage hopping alter Ready.
            self._prediction_stage_marker = stage_marker
            self._prediction_heads = dict(prediction_heads)
        else:
            for group, head in prediction_heads.items():
                previous = self._prediction_heads.get(group)
                if previous and head and previous != head:
                    arrivals.add(group)
            self._prediction_heads.update(prediction_heads)

        if arrivals:
            observed_at = time.time()
            for group in arrivals:
                self.chest_cooldowns["started_at"][group] = observed_at
            changed = True
        for group, identifiers in current.items():
            merged = list(seen[group] | identifiers)[-300:]
            if merged != self.chest_cooldowns["seen"].get(group, []):
                self.chest_cooldowns["seen"][group] = merged
                changed = True
        if changed:
            self._save_chest_cooldowns()
        now = time.time()
        for group, duration in CHEST_COOLDOWNS.items():
            started = self.chest_cooldowns["started_at"].get(group)
            remaining = duration - (now - started) if started else 0
            if remaining <= 0:
                value = "Ready"
            else:
                value = self._format_duration(remaining)
            self.chest_cooldown_display[group] = value

    def close_viewer(self):
        if self._closing:
            return
        self._closing = True
        if self.auto_unbox_enabled:
            send_companion_command("autounbox:off")
        self.auto_stash.stop()
        self.cube.stop()
        self.auto_stash_button.configure(state="disabled")
        self.auto_stash_text.set("Auto Stash  STOPPING…")
        if not self.auto_stash.running and not self.cube.running:
            self._finalize_storage()
            self.destroy()

    def _finalize_storage(self):
        if self._storage_finalized:
            return
        self._storage_finalized = True
        if self.storage is not None:
            try:
                self.storage.backup_current()
            except StorageError:
                pass

    def show_watch_dialog(self):
        if self.watch_dialog and self.watch_dialog.winfo_exists():
            self.watch_dialog.deiconify()
            self.watch_dialog.lift()
            self.watch_dialog.focus_force()
            return
        dialog = tk.Toplevel(self)
        dialog.title("TBH Watch List")
        self._style_dialog(dialog, 900, 420, (720, 300))
        dialog.transient(self)
        self.watch_dialog = dialog
        dialog.protocol("WM_DELETE_WINDOW", self._close_watch_dialog)
        frame = ttk.Frame(dialog, style="App.TFrame", padding=(8, 7))
        frame.pack(fill="both", expand=True)
        controls = ttk.Frame(frame, style="App.TFrame")
        controls.pack(fill="x")
        ttk.Label(controls, text="Search item:", style="Muted.TLabel").pack(side="left")
        combo = ttk.Entry(controls, textvariable=self.watch_query, width=45)
        combo.pack(side="left", padx=(6, 5))
        combo.bind("<KeyRelease>", self._filter_watch_options)
        combo.bind("<FocusIn>", self._filter_watch_options)
        combo.bind("<FocusOut>", lambda _event: self.after(150, self._hide_watch_suggestions))
        combo.bind("<Escape>", lambda _event: self._hide_watch_suggestions())
        self.watch_combo = combo
        ttk.Button(controls, text="Add", style="Small.TButton", command=self.add_watch_from_query).pack(side="left")
        ttk.Button(controls, text="Remove selected", style="Small.TButton", command=self.remove_selected_watches).pack(side="right")
        holder = ttk.Frame(frame, padding=(0, 3, 0, 0))
        holder.pack(fill="both", expand=True)
        columns = ("item_id", "item_name", "grade", "next_drop")
        tree = ttk.Treeview(holder, columns=columns, show="headings", style="Drop.Treeview", height=3)
        for col, label, width, anchor in (
            ("item_id", "Item ID", 85, "center"), ("item_name", "Watched item", 220, "w"), ("grade", "Grade", 95, "center"),
            ("next_drop", "Active queue", 180, "w"),
        ):
            tree.heading(col, text=label)
            tree.column(col, width=width, minwidth=45, anchor=anchor, stretch=col == "item_name")
        for grade, color in GRADE_COLORS.items():
            tree.tag_configure(f"grade_{grade}", foreground=color)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.watch_tree = tree
        if self.latest_queues:
            self._refresh_watch_list(self.latest_queues)

    def _close_watch_dialog(self):
        self._hide_watch_suggestions(destroy=True)
        if self.watch_dialog:
            self.watch_dialog.destroy()
        self.watch_dialog = None
        self.watch_tree = None
        self.watch_combo = None
        self.watch_suggestions = None
        self.watch_suggestion_popup = None

    def _save_watch_list(self):
        values = sorted(self.watched_ids)
        database_saved = False
        database_error = None
        if self.storage is not None:
            try:
                self.storage.replace_watch_items(values)
                database_saved = True
            except StorageError as error:
                database_error = error
        try:
            atomic_write_json(WATCH_LIST_PATH, values)
            json_saved = True
        except OSError:
            json_saved = False
        if not database_saved and not json_saved:
            self.show_notice(f"Cannot save Watch List: {database_error or WATCH_LIST_PATH}")
        elif database_error and json_saved:
            self.show_notice("Local database unavailable; Watch List was saved to the JSON backup.")
        self._update_auto_stash_protection()

    def _update_auto_stash_protection(self):
        protected = set(self.watched_ids)
        protected.update(
            item_id for item_id in getattr(self, "cube_excluded_ids", set())
            if self.catalog.get(str(item_id), {}).get("type") == "GEAR"
        )
        self.auto_stash.set_protected_ids(protected)

    def _matching_watch_options(self, query, limit=50):
        terms = query.casefold().split()
        if not terms:
            return []
        return [label for label, item_id in self.watch_option_ids.items()
                if item_id not in self.watched_ids and all(term in label.casefold() for term in terms)][:limit]

    def _filter_watch_options(self, _event=None):
        if not self.watch_combo or not self.watch_combo.winfo_exists():
            return
        matches = self._matching_watch_options(self.watch_query.get().strip())
        if not matches:
            self._hide_watch_suggestions()
            return
        if not self.watch_suggestion_popup or not self.watch_suggestion_popup.winfo_exists():
            popup = tk.Toplevel(self)
            popup.overrideredirect(True)
            popup.attributes("-topmost", True)
            popup.transient(self.watch_dialog)
            suggestions = tk.Listbox(popup, activestyle="none", exportselection=False,
                                     font=("Segoe UI", 9), background=UI["surface_alt"], foreground=UI["text"],
                                     selectbackground=UI["raised"], selectforeground=UI["text"],
                                     highlightbackground=UI["border"], highlightcolor=UI["accent"], relief="flat")
            suggestions.pack(fill="both", expand=True)
            suggestions.bind("<ButtonRelease-1>", self._choose_watch_suggestion)
            self.watch_suggestion_popup = popup
            self.watch_suggestions = suggestions
        self.watch_suggestions.delete(0, tk.END)
        for label in matches:
            self.watch_suggestions.insert(tk.END, label)
        row_count = min(len(matches), 5)
        width = self.watch_combo.winfo_width()
        height = row_count * 22 + 2
        x = self.watch_combo.winfo_rootx()
        y = self.watch_combo.winfo_rooty() + self.watch_combo.winfo_height()
        self.watch_suggestion_popup.geometry(f"{width}x{height}+{x}+{y}")
        self.watch_suggestion_popup.deiconify()
        self.watch_suggestion_popup.lift()

    def _hide_watch_suggestions(self, destroy=False):
        if not self.watch_suggestion_popup or not self.watch_suggestion_popup.winfo_exists():
            return
        if destroy:
            self.watch_suggestion_popup.destroy()
            self.watch_suggestion_popup = None
            self.watch_suggestions = None
        else:
            self.watch_suggestion_popup.withdraw()

    def _choose_watch_suggestion(self, _event=None):
        if not self.watch_suggestions:
            return
        selected = self.watch_suggestions.curselection()
        if not selected:
            return
        self.watch_query.set(self.watch_suggestions.get(selected[0]))
        self._hide_watch_suggestions()
        self.watch_combo.focus_set()

    def add_watch_from_query(self):
        query = self.watch_query.get().strip()
        item_id = self.watch_option_ids.get(query)
        if item_id is None and query.isdigit() and query in self.catalog:
            item_id = query
        if item_id is None:
            matches = self._matching_watch_options(query, limit=2)
            if len(matches) == 1:
                item_id = self.watch_option_ids[matches[0]]
        if item_id is None:
            self.show_notice("Choose one filtered item, or enter its exact Item ID.")
            return
        self.watched_ids.add(item_id)
        self._save_watch_list()
        self._update_watch_button_text()
        self.watch_query.set("")
        self._filter_watch_options()
        self.show_notice(f"Watching {self.catalog[item_id]['name']}")

    def remove_selected_watches(self):
        selected = self.watch_tree.selection()
        item_ids = [self.watch_row_item_ids.get(row) for row in selected]
        item_ids = [item_id for item_id in item_ids if item_id]
        if not item_ids:
            self.show_notice("Select an item in Watch List to remove it.")
            return
        self.watched_ids.difference_update(item_ids)
        self._save_watch_list()
        self._update_watch_button_text()
        self.show_notice("Removed selected item from Watch List")

    def _show_prediction_menu(self, tree, event):
        row = tree.identify_row(event.y)
        if not row:
            return
        tree.selection_set(row)
        item_id = self.prediction_row_item_ids.get(row)
        if not item_id:
            return
        item = self.catalog.get(str(item_id), {"name": str(item_id)})
        menu = tk.Menu(self, tearoff=False)
        menu.configure(background=UI["surface_alt"], foreground=UI["text"], activebackground=UI["raised"],
                       activeforeground=UI["text"], borderwidth=1, relief="solid")
        if str(item_id) in self.watched_ids:
            menu.add_command(label=f"Stop watching {item['name']}", command=lambda: self._remove_watch(item_id))
        else:
            menu.add_command(label=f"Watch {item['name']}", command=lambda: self._add_watch(item_id))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    def _add_watch(self, item_id):
        self.watched_ids.add(str(item_id))
        self._save_watch_list()
        self._update_watch_button_text()
        self._filter_watch_options()
        self.show_notice(f"Watching {self.catalog[str(item_id)]['name']}")

    def _remove_watch(self, item_id):
        self.watched_ids.discard(str(item_id))
        self._save_watch_list()
        self._update_watch_button_text()
        self.show_notice(f"Stopped watching {self.catalog[str(item_id)]['name']}")

    def _refresh_watch_list(self, queues):
        if not self.watch_tree or not self.watch_tree.winfo_exists():
            return
        selected_ids = {
            self.watch_row_item_ids.get(row)
            for row in self.watch_tree.selection()
        }
        clear_tree(self.watch_tree)
        self.watch_row_item_ids = {}
        queue_labels = {"0": "Normal", "1": "Boss", "2": "Act Boss"}
        matches = {}
        for group, rows in queues.get("bfqn", {}).get("groups", {}).items():
            for order, box in enumerate(rows, start=1):
                item_id = str(box.get("obscuredRewardItemId", 0))
                if item_id in self.watched_ids and item_id not in matches:
                    matches[item_id] = (group, order, box)
        for item_id in sorted(self.watched_ids, key=lambda key: self.catalog[key]["name"].casefold()):
            item = self.catalog[item_id]
            grade = item.get("grade") or "—"
            match = matches.get(item_id)
            if match:
                group, order, box = match
                next_drop = f"{queue_labels.get(group, 'Unknown')} #{order}"
            else:
                next_drop = "Not in active queue"
            tags = (f"grade_{grade}",) if grade in GRADE_COLORS else ()
            row = self.watch_tree.insert("", "end", values=(
                item_id, item["name"], grade.title(), next_drop,
            ), tags=tags)
            self.watch_row_item_ids[row] = item_id
            if item_id in selected_ids:
                self.watch_tree.selection_add(row)
                self.watch_tree.focus(row)

    def _create_panel(self, parent, group, column, label_style):
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=0, column=column, sticky="nsew", padx=(0, 5) if column == 0 else (5, 0))
        title = ttk.Label(frame, text=PREDICTION_NAMES[group], style=label_style)
        title.pack(fill="x")
        self.count_labels[group] = title
        columns = ("order", "item_name", "grade", "details", "ready")
        tree = ttk.Treeview(frame, columns=columns, show="headings", style="Drop.Treeview")
        for col, label, width, anchor in (
            ("order", "#", 36, "center"), ("item_name", "Item Name", 205, "w"),
            ("grade", "Grade", 82, "center"), ("details", "Gear / Level", 112, "w"),
            ("ready", "Ready", 68, "center"),
        ):
            tree.heading(col, text=label)
            tree.column(col, width=width, minwidth=40, anchor=anchor, stretch=col == "item_name")
        # "Next" uses only a neutral background; the foreground always remains the true grade color.
        tree.tag_configure("next", background=UI["next_bg"], font=("Segoe UI Semibold", 10))
        tree.tag_configure("later", foreground=UI["muted"])
        tree.tag_configure("watched", font=("Segoe UI", 10, "bold"))
        for grade, color in GRADE_COLORS.items():
            tree.tag_configure(f"grade_{grade}", foreground=color)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=(0, 1))
        scroll.pack(side="right", fill="y", pady=(0, 1))
        tree.bind("<Button-3>", lambda event, source=tree: self._show_prediction_menu(source, event))
        self.trees[group] = tree

    def show_notice(self, text):
        if self._notice_after:
            self.after_cancel(self._notice_after)
        self.notice.set(text)
        self._notice_after = self.after(5000, lambda: self.notice.set(""))

    def refresh(self):
        try:
            snapshot = tbh_drop_probe.read_snapshot()
            queues = snapshot["queues"]
            self.latest_queues = queues
            self.latest_snapshot = snapshot
            stage = snapshot.get("currentStage")
            self.stage_context.set(live_stage_label(stage))
            expected_box = {
                "0": (stage or {}).get("normalBoxId"),
                "1": (stage or {}).get("bossBoxId"),
            }
            counts = []
            stage_syncing = False
            prediction_heads = {}
            self.prediction_row_item_ids = {}
            # The two panels intentionally match one stage: normal chests on the left,
            # and that stage's boss chest on the right. Act-boss queue data stays out of
            # this view so it cannot be confused with a normal stage's Boss Drops.
            shown = ("0", "1")
            for group in shown:
                tree = self.trees["0" if group == "0" else "1"]
                clear_tree(tree)
                source_rows = queues.get("bfqn", {}).get("groups", {}).get(group, [])
                # StageCache changes just before wp finishes swapping its BoxData.
                # Never briefly show the previous tier's rewards under the new stage.
                is_syncing = bool(source_rows and expected_box[group] and any(
                    row.get("obscuredItemId") != expected_box[group] for row in source_rows
                ))
                rows = [] if is_syncing else source_rows
                stage_syncing = stage_syncing or is_syncing
                if rows:
                    prediction_heads[group] = box_unique_id(rows[0])
                for order, box in enumerate(rows, start=1):
                    item_id = box.get("obscuredRewardItemId", 0)
                    item = self.catalog.get(str(item_id), {"name": f"Unknown item ({item_id})", "grade": "", "type": "", "gear": None, "level": None})
                    item_name = item["name"]
                    watched = str(item_id) in self.watched_ids
                    shown_name = ("★ " if order == 1 else "") + ("◆ " if watched else "") + item_name
                    grade = item.get("grade") or "—"
                    details = ""
                    if item.get("type") == "GEAR":
                        details = f"{(item.get('gear') or 'Gear').title()} · Lv.{item.get('level') or '?'}"
                    elif item.get("type"):
                        details = item["type"].title()
                    tags = ["next"] if order == 1 else []
                    if grade in GRADE_COLORS:
                        tags.append(f"grade_{grade}")
                    elif order != 1:
                        tags.append("later")
                    if watched:
                        tags.append("watched")
                    row = tree.insert("", "end", values=(
                        order, shown_name, grade.title(), details,
                        self.chest_cooldown_display.get(group, "Ready") if order == 1 else "",
                    ), tags=tuple(tags))
                    self.prediction_row_item_ids[row] = item_id
                counts.append(f"{PREDICTION_NAMES[group]}: {'loading' if is_syncing else len(rows)}")
                if group == "0":
                    self.count_labels["0"].configure(
                        text="Normal Drops — loading…" if is_syncing else f"Normal Drops — {len(rows)} items"
                    )
                else:
                    self.count_labels["1"].configure(
                        text="Boss Drops — loading…" if is_syncing else f"Boss Drops — {len(rows)} items"
                    )
                if rows:
                    first = rows[0]
                    item_id = first.get("obscuredRewardItemId", 0)
                    item = self.catalog.get(str(item_id), {"name": item_id, "grade": ""})
                    previous = self.last_next.get(group)
                    self.last_next[group] = item_id
                    if previous is not None and previous != item_id:
                        self.show_notice(f"Next {PREDICTION_NAMES[group]}: {item['name']} · {item.get('grade') or '?'}")

            # This is deliberately *not* the future Drop Prediction list. Ownership
            # is vm.ul.bfdz, the game's live chest inventory, then joins the live
            # BoxData instance to reveal an already-rolled reward.
            for tree in self.queue_trees.values():
                clear_tree(tree)
            owned_chests = snapshot["ownedChests"]
            stage_marker = (
                (stage or {}).get("stageKey"), (stage or {}).get("normalBoxId"), (stage or {}).get("bossBoxId"),
            )
            self._observe_chest_cooldowns(owned_chests, prediction_heads, stage_marker)
            shown_owned_groups = ("0", "1")
            owned_counts = {group: 0 for group in shown_owned_groups}
            live_rewards = live_reward_by_chest_id(queues)
            for chest in owned_chests:
                live_group, box = live_rewards.get(chest["unique_id"], (None, None))
                chest_type = chest["type"] if chest["type"] != "?" else (live_group or "?")
                try:
                    quantity = int(chest["quantity"])
                except (TypeError, ValueError):
                    quantity = 1
                if chest_type in owned_counts:
                    owned_counts[chest_type] += quantity
                if box:
                    item_id = box.get("obscuredRewardItemId", 0)
                    item = self.catalog.get(str(item_id), {"name": f"Unknown item ({item_id})", "grade": "", "type": "", "gear": None, "level": None})
                    grade = item.get("grade") or "—"
                    details = (f"{(item.get('gear') or 'Gear').title()} · Lv.{item.get('level') or '?'}"
                               if item.get("type") == "GEAR" else (item.get("type") or "").title())
                    tags = ([f"grade_{grade}"] if grade in GRADE_COLORS else [])
                else:
                    item_id, item, grade, details, tags = "—", {"name": "Reward not loaded yet"}, "—", "", []
                # An unknown type is a transient save-cache record; do not place it
                # into a wrong chest panel. It will appear as soon as live BoxData
                # supplies the actual chest type.
                if chest_type in self.queue_trees:
                    self.queue_trees[chest_type].insert("", "end", values=(
                        item["name"], grade.title(), details,
                    ), tags=tuple(tags))
            for group in shown_owned_groups:
                self.queue_count_labels[group].configure(
                    text=f"{CHEST_TYPE_NAMES[group]} Chests — {owned_counts[group]}"
                )
            total_owned = sum(owned_counts.values())
            if total_owned:
                self.queue_summary.set(
                    "Unopened chests you own · " + " · ".join(
                        f"{CHEST_TYPE_NAMES[group]}: {owned_counts[group]}" for group in shown_owned_groups)
                )
            else:
                self.queue_summary.set("No unopened Normal or Stage Boss chests in your current inventory.")
            self._refresh_watch_list(queues)
            self.status.set(
                f"Connected · PID {snapshot['processId']} · " + " · ".join(counts) +
                (" · Stage transition syncing" if stage_syncing else "") + " · Drop reads only"
            )
        except Exception as exc:
            if getattr(exc, "winerror", None) == 5 or "Access is denied" in str(exc):
                self.status.set("Access denied — run TBH Astrarium as Administrator to match the game.")
                self.show_notice("Windows blocked the memory read. Close and reopen TBH Astrarium as Administrator.")
            else:
                self.status.set(f"Could not read game memory: {exc}")
                self.show_notice("Memory read unavailable — keep the game open.")
        finally:
            # A low-cost read keeps opened/received chest state feeling immediate.
            self.after(1000, self.refresh)


def main():
    viewer = DropViewer()
    # Explicit launch options let a managed app update resume the two
    # previously enabled utilities without restarting the game.
    if "--auto-unbox" in sys.argv:
        viewer.after(500, viewer.toggle_auto_unbox)
    if "--auto-stash" in sys.argv:
        viewer.after(700, viewer.toggle_auto_stash)
    if "--show-cube" in sys.argv:
        viewer.after(900, viewer.show_cube_dialog)
    if "--auto-combine" in sys.argv:
        def resume_auto_combine():
            viewer.show_cube_dialog()
            if not viewer.cube_tier_options:
                viewer.cube_status.set("Cannot resume · synthesis levels unavailable")
                return
            viewer.cube_combine.set(True)
            viewer._cube_filters_changed()
        viewer.after(1100, resume_auto_combine)
    viewer.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
