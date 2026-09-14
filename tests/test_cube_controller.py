import queue
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tbhastrarium.cube import CubeController


class Exports:
    def __init__(self):
        self.calls = []

    def configure(self, settings, preview, rehearse):
        self.calls.append((settings, preview, rehearse))


class Script:
    def __init__(self):
        self.exports_sync = Exports()


controller = object.__new__(CubeController)
controller.settings = None
controller.preview = False
controller.rehearse = False
controller._settings_requests = queue.Queue()
controller._thread = None
settings1 = {"combine": True, "grades": [1]}
settings2 = {"combine": True, "grades": [1, 2]}
controller._settings_requests.put(settings1)
controller._settings_requests.put(settings2)
script = Script()
controller._service_requests(script)
assert script.exports_sync.calls == [(settings2, False, False)]
print("PASS Cube live filter update coalesces to newest settings")
controller._settings_requests.put({"combine": True, "combineTier": 3})
controller.start = lambda: True
controller.start_with({"combine": True, "combineTier": 9})
assert controller._settings_requests.empty()
controller._configure_agent(script)
assert script.exports_sync.calls[-1][0]["combineTier"] == 9
print("PASS restarting cannot apply a stale lower-tier setting")
