import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src'))
from tbhastrarium import autostash as a

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.agent=root/'agent.js';self.agent.write_text('// fixture')
        self.dll=root/'game.dll';self.dll.write_bytes(b'fixture')
        self.controller=a.AutoStashController(self.agent,root/'log.jsonl',{'1':{'type':'GEAR'},'2':{'type':'MATERIAL'},'3':{'type':'STAGEBOX'}})
    def tearDown(self):self.tmp.cleanup()
    def test_eligible_catalog(self):self.assertEqual(self.controller.eligible,[1,2])
    def test_protected_ids_are_normalized(self):
        self.controller.set_protected_ids(['2', 1])
        self.assertEqual(self.controller.protected_ids,{1,2})
    def test_unknown_build_never_attaches(self):
        import frida
        with patch.object(a.probe,'find_pid',return_value=99999),patch.object(a,'game_module_path',return_value=self.dll),patch.object(frida,'attach') as attach:
            self.controller._run();attach.assert_not_called()
        events=self.controller.drain();self.assertTrue(any(x['event']=='paused' and 'Unsupported' in x['reason'] for x in events))
    def test_stop_unloads_and_detaches(self):
        import frida,hashlib
        script=MagicMock();session=MagicMock();session.create_script.return_value=script
        def configure(ids, enabled=True, protected_ids=None):self.controller.stop()
        script.exports_sync.configure.side_effect=configure
        with patch.object(a.probe,'find_pid',return_value=99999),patch.object(a,'game_module_path',return_value=self.dll),patch.object(a,'require_supported',return_value={}),patch.object(frida,'attach',return_value=session):
            self.controller._run()
        script.exports_sync.stop.assert_called_once();script.unload.assert_called_once();session.detach.assert_called_once()
    def test_message_failure_triggers_cleanup(self):
        import frida,hashlib
        script=MagicMock();session=MagicMock();session.create_script.return_value=script
        handlers={};script.on.side_effect=lambda name,fn:handlers.update({name:fn})
        script.load.side_effect=lambda:handlers['message']({'type':'error','description':'fixture error'},None)
        with patch.object(a.probe,'find_pid',return_value=99999),patch.object(a,'game_module_path',return_value=self.dll),patch.object(a,'require_supported',return_value={}),patch.object(frida,'attach',return_value=session):
            self.controller._run()
        self.assertTrue(any(e['event']=='paused' for e in self.controller.drain()));script.unload.assert_called_once();session.detach.assert_called_once()
    def test_open_page_rejects_out_of_range(self):
        with self.assertRaises(ValueError): self.controller.open_page(0)
        with self.assertRaises(ValueError): self.controller.open_page(8)

if __name__=='__main__':unittest.main()
