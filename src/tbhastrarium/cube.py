"""Hot-attached Cube automation. The game owns all recipes and item consumption."""
import copy
import queue
from .autostash import AutoStashController, game_module_path
from .builds import require_supported
from . import probe


def read_synthesis_options():
    """Read unlocked recipe options without selecting or purchasing anything."""
    pid = probe.find_pid('TaskBarHero.exe')
    path = game_module_path(pid)
    require_supported(path, 'auto-combine')
    reader = probe.Reader(pid)
    try:
        base = probe.module_base(pid, 'GameAssembly.dll')
        db = reader.u64(reader.u64(reader.u64(base + 0x5fc0780) + 0xb8))
        rules = reader.u64(db + 0x150)
        rule_array, rule_count = reader.u64(rules + 0x10), reader.i32(rules + 0x18)
        if not 0 < rule_count <= 10000:
            raise RuntimeError('Invalid synthesis rules')
        maximums = {}
        for i in range(rule_count):
            rule = reader.u64(rule_array + 0x20 + i * 8)
            tier, maximum = reader.i32(rule + 0x34), reader.i32(rule + 0x40)
            maximums[tier] = max(maximums.get(tier, 0), maximum)
        fields = reader.u64(reader.u64(base + 0x5f4b220) + 0xb8)
        recipes = reader.u64(fields + 0xf8)
        entries, count = reader.u64(recipes + 0x18), reader.i32(recipes + 0x20)
        if not 0 <= count <= 100:
            raise RuntimeError('Invalid Cube recipe catalog')
        options = []
        for i in range(count):
            entry = entries + 0x20 + i * 24
            if reader.i32(entry) < 0 or reader.i32(entry + 8) != 1:
                continue
            values = reader.u64(entry + 16)
            array, size = reader.u64(values + 0x10), reader.i32(values + 0x18)
            if not 0 <= size <= 100:
                raise RuntimeError('Invalid synthesis level list')
            for index in range(size):
                option = reader.u64(array + 0x20 + index * 8)
                info = reader.u64(option + 0x20)
                # ObscuredBool: default zero is false; non-default decrypts
                # to 0xb5 for false. The agent checks the native getter again.
                data = reader.read(option + 0x8c, 12)
                hidden, key = int.from_bytes(data[4:8], 'little'), data[8]
                unlocked = any(data[:9]) and ((hidden - key) ^ key) != 0xb5
                if unlocked:
                    tier = reader.i32(info + 0x38)
                    required = reader.i32(info + 0x40)
                    if tier in maximums:
                        # The Cube itself presents an option by its Cube-level
                        # floor and the highest result it can produce, e.g.
                        # "Lv.80~90". Keep that display wording separate from
                        # the per-category recipe checks used by the agent.
                        options.append({'tier': tier, 'requiredLevel': required,
                                        'minResultLevel': required, 'maxResultLevel': maximums[tier]})
        return sorted(options, key=lambda x: x['tier'])
    finally:
        reader.close()


class CubeController(AutoStashController):
    mutex_name = 'Cube'

    def __init__(self, agent_path, log_path, catalog):
        super().__init__(agent_path, log_path, catalog)
        self.settings = None
        self.preview = False
        self.rehearse = False
        self._settings_requests = queue.Queue()

    def start_with(self, settings, preview=False, rehearse=False):
        if self.running:
            raise RuntimeError('Stop Cube automation before changing its filters.')
        # A queued change from a stopped session must never replace the tier
        # explicitly selected for the new session.
        while True:
            try:
                self._settings_requests.get_nowait()
            except queue.Empty:
                break
        self.settings = copy.deepcopy(settings)
        self.preview = preview
        self.rehearse = rehearse
        return self.start()

    def _configure_agent(self, script):
        script.exports_sync.configure(self.settings, self.preview, self.rehearse)

    def apply_settings(self, settings):
        """Apply filters immediately without detaching from the game."""
        self.settings = copy.deepcopy(settings)
        if self.running:
            self._settings_requests.put(copy.deepcopy(settings))
            return True
        return self.start_with(settings)

    def _service_requests(self, script):
        latest = None
        while True:
            try:
                latest = self._settings_requests.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            script.exports_sync.configure(latest, False, False)
