"""Exercise the real Tk selector with a fake Cube controller; no item actions."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from tbhastrarium import app as ui


class Controller:
    running = False
    def __init__(self):
        self.calls = []
    def apply_settings(self, settings):
        self.calls.append(settings)
        self.running = True
    def stop(self):
        self.running = False


ui.DropViewer.refresh = lambda self: None
ui.load_catalog = lambda: {
    '1001': {'name': 'Keeper Sword', 'grade': 'RARE', 'type': 'GEAR', 'gear': 'sword', 'level': 80, 'affix': None},
    '1002': {'name': 'Keeper Orb', 'grade': 'UNCOMMON', 'type': 'GEAR', 'gear': 'orb', 'level': 80, 'affix': None},
    '2001': {'name': 'Keeper Material', 'grade': 'COMMON', 'type': 'MATERIAL', 'gear': None, 'level': None, 'affix': None},
}
ui.read_synthesis_options = lambda: [
    {'tier': 8, 'requiredLevel': 70, 'minResultLevel': 70, 'maxResultLevel': 80},
    {'tier': 9, 'requiredLevel': 80, 'minResultLevel': 80, 'maxResultLevel': 90}]
with tempfile.TemporaryDirectory(prefix='tbh-cube-ui-') as directory:
    ui.DATABASE_PATH = Path(directory) / 'TBHAstrarium.db'
    ui.WATCH_LIST_PATH = Path(directory) / 'watch.json'
    ui.CHEST_COOLDOWN_PATH = Path(directory) / 'cooldowns.json'
    ui.CUBE_SETTINGS_PATH = Path(directory) / 'settings.json'
    ui.UI_SETTINGS_PATH = Path(directory) / 'ui.json'
    app = ui.DropViewer()
    app.withdraw()
    app.cube = Controller()
    try:
        app.show_cube_dialog()
        app.update_idletasks()
        assert all(str(combo['state']) == 'readonly' for combo in app.cube_tier_combos[:2])
        assert all(len(combo['values']) == 2 for combo in app.cube_tier_combos[:2])
        assert app.cube_tier_combos[2] is None, 'Materials must not expose a level selector'
        assert any('Lv.80~90' in value for value in app.cube_tier_combos[0]['values'])
        assert all(value.get() == 'Choose synthesis level' for value in app.cube_category_tiers[:2])
        assert app.cube_tier_options[app.cube_category_tiers[2].get()] == 9
        app.cube_combine.set(True)
        app._cube_filters_changed()
        assert not app.cube.calls, 'Must not start before the user chooses a tier'
        tier9 = next(k for k, v in app.cube_tier_options.items() if v == 9)
        tier8 = next(k for k, v in app.cube_tier_options.items() if v == 8)
        app.cube_category_tiers[0].set(tier9)
        app.cube_category_enabled[2].set(False)
        for grade, value in enumerate(app.cube_category_grades[0]):
            value.set(grade in (0, 1, 2))
        app._cube_filters_changed()
        gear = app.cube.calls[-1]['combineCategories'][0]
        assert gear == {'category': 0, 'enabled': True, 'tier': 9, 'grades': [0, 1, 2]}
        app.cube_category_enabled[2].set(True)
        for grade, value in enumerate(app.cube_category_grades[2]):
            value.set(grade in (0, 1))
        app.cube_category_enabled[1].set(True)
        app.cube_category_tiers[1].set(tier8)
        for grade, value in enumerate(app.cube_category_grades[1]):
            value.set(grade == 1)
        app._cube_filters_changed()
        categories = app.cube.calls[-1]['combineCategories']
        assert categories[0]['tier'] == 9 and categories[0]['grades'] == [0, 1, 2]
        assert categories[1]['tier'] == 8 and categories[1]['grades'] == [1]
        assert categories[2]['tier'] == 9 and categories[2]['grades'] == [0, 1]
        stored = json.loads(ui.CUBE_SETTINGS_PATH.read_text())
        assert stored['categoryTiers'] == {'0': 9, '1': 8}
        assert stored['categoryGrades']['0'] == [0, 1, 2]
        assert stored['categoryGrades']['2'] == [0, 1]
        app._show_cube_exclusion_dialog()
        assert app.theme_name == 'dark'
        app.toggle_theme()
        app.update_idletasks()
        assert app.theme_name == 'light'
        assert app.theme_button_text.get() == 'Theme  LIGHT'
        assert app['background'] == ui.THEMES['light']['bg']
        assert app.cube_dialog['background'] == ui.THEMES['light']['bg']
        assert app.cube_exclude_available['background'] == ui.THEMES['light']['surface']
        assert json.loads(ui.UI_SETTINGS_PATH.read_text()) == {'theme': 'light'}
        assert app.storage.get_json('ui_preferences') == {'theme': 'light'}
        app.toggle_theme()
        assert app.theme_name == 'dark'
        for item_id in ('1001', '1002'):
            app.cube_exclude_query.set(item_id)
            app._filter_cube_exclusion_options()
            app.cube_exclude_available.selection_set(0)
            app._add_cube_exclusion()
        assert app.cube_excluded_ids == {'1001', '1002'}
        assert set(app.cube.calls[-1]['combineExcludedIds']) == {1001, 1002}
        assert json.loads(ui.CUBE_SETTINGS_PATH.read_text())['combineExcludedIds'] == ['1001', '1002']
        remove_row = next(row for row, item_id in app.cube_exclude_tree_ids.items() if item_id == '1001')
        app.cube_exclude_tree.selection_set(remove_row)
        app._remove_cube_exclusions()
        assert app.cube_excluded_ids == {'1002'}
        assert app.cube.calls[-1]['combineExcludedIds'] == [1002]
        app.cube_dialog.destroy()
        app.show_cube_dialog()
        assert app.cube_tier_options[app.cube_category_tiers[0].get()] == 9
        assert app.cube_tier_options[app.cube_category_tiers[1].get()] == 8
        assert app.cube_tier_combos[2] is None
        assert app.cube_tier_options[app.cube_category_tiers[2].get()] == 9
        # Refresh cannot silently substitute an unlocked lower tier.
        ui.read_synthesis_options = lambda: [{'tier': 9, 'requiredLevel': 80, 'minResultLevel': 80, 'maxResultLevel': 90}]
        app._refresh_cube_tiers()
        assert not app.cube.running
        assert app.cube_category_tiers[0].get() == tier9
        assert app.cube_category_tiers[1].get() == 'Choose synthesis level'
        assert app.cube_tier_options[app.cube_category_tiers[2].get()] == 9
        assert json.loads(ui.CUBE_SETTINGS_PATH.read_text())['categoryTiers'] == {'0': 9, '1': 8}
        print('PASS category controls plus searchable, persisted, live-updating Auto Combine exclusion add/remove UI')
    finally:
        app.destroy()
