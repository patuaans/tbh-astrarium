"""Exercise the permanent one-click Stash shortcuts without attaching to the game."""
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tbhastrarium import app as ui


class Controller:
    running = False

    def __init__(self):
        self.calls = []
        self.events = []

    def open_page(self, page):
        self.calls.append(page)
        return True

    def drain(self):
        result, self.events = self.events, []
        return result

    def stop(self):
        pass


ui.DropViewer.refresh = lambda self: None
ui.load_catalog = lambda: {
    "1001": {"name": "Fixture", "grade": "COMMON", "type": "GEAR",
             "gear": "sword", "level": 80, "affix": None},
}

with tempfile.TemporaryDirectory(prefix="tbh-stash-shortcuts-") as directory:
    root = Path(directory)
    ui.DATABASE_PATH = root / "TBHAstrarium.db"
    ui.WATCH_LIST_PATH = root / "watch.json"
    ui.CHEST_COOLDOWN_PATH = root / "cooldowns.json"
    ui.CUBE_SETTINGS_PATH = root / "cube.json"
    ui.UI_SETTINGS_PATH = root / "ui.json"
    app = ui.DropViewer()
    app.withdraw()
    controller = Controller()
    app.auto_stash = controller
    try:
        app.update_idletasks()
        assert app.title() == "TBH Astrarium — Drop Prediction"
        assert len(app.stash_page_buttons) == 7
        assert [button.cget("text").split()[0] for button in app.stash_page_buttons] == [
            "1", "2", "3", "4", "5", "6", "7"]
        app.stash_page_buttons[3].invoke()
        assert controller.calls == [4]
        assert app.stash_page_status.get() == "Opening 4…"
        assert all(str(button["state"]) == "disabled" for button in app.stash_page_buttons)
        controller.events.append({"event": "page_opened", "page": 4, "openedWindow": True})
        app._poll_auto_stash()
        assert app.stash_active_page == 4
        assert app.stash_page_status.get() == "Page 4 open"
        assert app.stash_page_buttons[3].cget("style") == "Active.TButton"
        assert all(str(button["state"]) == "normal" for button in app.stash_page_buttons)
        print("PASS seven permanent one-click Stash shortcuts with active-page feedback")
    finally:
        app.destroy()
