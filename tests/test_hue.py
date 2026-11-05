"""Hue wheel geometry, output routing, persistence, and editor round trips."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import ctypes as C
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication
from altclipctrl.hue import HueMemory, wheel_point, wheel_defaults
from altclipctrl.engine import Engine
from altclipctrl.model import action, defaults, validate, save, load
from altclipctrl.platforms import WindowsBackend, PreviewBackend
from altclipctrl.ui import ActionEditor, OptionsDialog
from tests.test_altclipctrl import FakeBackend, TEMP_ROOT


class HueBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.allowed = True
    def click_at(self, x, y, program):
        if self.allowed:
            self.events.append(('click', (x, y, program)))
        return self.allowed


class HueTests(unittest.TestCase):
    def setUp(self):
        self.settings = defaults()
        self.settings['hue_wheel'].update(center_x=100, center_y=100, radius=50, angle=0, step=90)
        self.backend = HueBackend()
        self.memory = HueMemory()
        self.engine = Engine(self.settings, self.backend, hue_memory=self.memory)
        self.wheel = self.settings['hue_wheel']

    def test_geometry_wrap_and_reverse(self):
        self.assertEqual([wheel_point(self.wheel, angle) for angle in (0,90,180,270)], [(100,50),(150,100),(100,150),(50,100)])
        for _ in range(4):
            self.engine.execute(action('hue_next'))
        self.assertEqual(self.memory.angle(self.wheel), 0)
        self.engine.execute(action('hue_previous'))
        self.assertEqual(self.memory.angle(self.wheel), 270)
        self.assertEqual(self.backend.events[-1], ('click',(50,100,'clipstudiopaint')))

    def test_held_dial_and_pressed_turns_use_same_remembered_angle(self):
        b = self.settings['profiles'][0]['bindings']
        b['top_left']['hold'] = action('dial_hue', {'reverse': True})
        self.engine.event('F13', True, 1)
        self.engine.event('F23', True, 1.01)
        self.engine.event('F23', False, 1.02)
        self.assertEqual(self.memory.angle(self.wheel), 270)
        self.engine.event('F24', True, 1.03)
        self.engine.event('F24', False, 1.04)
        self.assertEqual(self.memory.angle(self.wheel), 180)
        self.engine.event('F13', False, 1.05)
        self.engine.reset()
        self.assertEqual(self.memory.angle(self.wheel), 180)

    def test_hold_key_is_released_before_hue_click(self):
        b = self.settings['profiles'][0]['bindings']
        b['top_left']['hold'] = action('hold_dial', {'without_dial':action('hold_key','Space'), 'with_dial':action('dial_hue',{'reverse':False})})
        self.engine.event('F13', True, 1)
        self.engine.poll(1.4)
        self.engine.event('F23', True, 1.5)
        self.assertEqual(self.backend.events[:2], [('down','Space'),('up','Space')])
        self.assertEqual(self.backend.events[2][0], 'click')

    def test_skipped_and_failed_clicks_do_not_move_memory(self):
        self.backend.allowed = False
        self.engine.execute(action('hue_next'))
        self.assertEqual(self.memory.angle(self.wheel), 0)
        with patch.object(self.backend,'click_at',side_effect=OSError('blocked')):
            with self.assertRaises(OSError):
                self.engine.execute(action('hue_next'))
        self.assertEqual(self.memory.angle(self.wheel), 0)

    def test_memory_survives_restart_and_step_changes_but_not_calibration_change(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as d:
            path = Path(d)/'memory.json'
            memory = HueMemory(path)
            memory.remember(self.wheel,270); memory.flush()
            memory = HueMemory(path)
            self.assertEqual(memory.angle(self.wheel),270)
            self.wheel['step']=1
            self.assertEqual(memory.angle(self.wheel),270)
            self.wheel['center_x']=101
            self.assertEqual(memory.angle(self.wheel),0)

    def test_preview_never_clicks_or_changes_saved_angle(self):
        engine=Engine(self.settings,PreviewBackend(),hue_memory=self.memory)
        engine.execute(action('hue_next'))
        self.assertEqual(self.memory.angle(self.wheel),0)

    def test_settings_migrate_and_new_actions_round_trip(self):
        old=defaults();old.pop('hue_wheel');validate(old)
        self.assertEqual(old['hue_wheel'],wheel_defaults())
        b=self.settings['profiles'][0]['bindings']
        b['top_left']['hold']=action('dial_hue',{'reverse':False})
        b['cw']['tap']=action('hue_next'); b['ccw']['tap']=action('hue_previous')
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as d:
            path=Path(d)/'settings.json';save(path,self.settings)
            self.assertEqual(load(path),self.settings)
        for key,value in [('radius',0),('step',0),('step',float('nan')),('angle',361),('program','')]:
            bad=copy.deepcopy(self.settings);bad['hue_wheel'][key]=value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):validate(bad)


class HueEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_options_and_action_editor_keep_geometry_and_reversal(self):
        settings=defaults()
        dialog=OptionsDialog(None,settings)
        dialog.hue_fields['center_x'].setValue(500)
        dialog.hue_fields['step'].setValue(2.5)
        dialog.hue_reset.setChecked(True)
        dialog.commit()
        self.assertEqual(dialog.result_settings['hue_wheel']['center_x'],500)
        self.assertEqual(dialog.result_settings['hue_wheel']['step'],2.5)
        self.assertTrue(dialog.reset_hue)
        editor=ActionEditor(action('dial_hue',{'reverse':True}),settings['profiles'],True)
        self.assertFalse(editor.reverse_direction.isHidden())
        self.assertEqual(editor.read(),action('dial_hue',{'reverse':True}))
        dialog.close();editor.close()


@unittest.skipUnless(sys.platform=='win32','Windows native packet structure')
class WindowsHuePacketTests(unittest.TestCase):
    def setUp(self):
        self.backend=WindowsBackend(lambda *_:False,lambda *_:None)
        user=Mock()
        self.backend.user=user
        self.backend.foreground_token=Mock(return_value=123)
        self.backend.program_for_window=Mock(return_value='CLIPStudioPaint.exe')
        user.GetAsyncKeyState.return_value=0
        def get_cursor(point):
            point._obj.x,point._obj.y=300,200
            return 1
        user.GetCursorPos.side_effect=get_cursor
        user.GetSystemMetrics.side_effect=lambda code:{76:-1920,77:0,78:4480,79:1440}[code]
        user.WindowFromPoint.return_value=321
        user.GetAncestor.return_value=123
        user.SendInput.return_value=4

    def test_atomic_click_packets_restore_cursor_and_use_virtual_desktop(self):
        self.assertTrue(self.backend.send_hue_click(123,1328,'clipstudiopaint',123))
        count,packets,size=self.backend.user.SendInput.call_args.args
        self.assertEqual(count,4)
        self.assertEqual([p.mouse.flags for p in packets],[0xC001,0xC003,0xC005,0xC001])
        self.assertEqual(packets[0].mouse.dx,round((123+1920)*65535/4479))
        self.assertEqual(packets[3].mouse.dx,round((300+1920)*65535/4479))
        self.assertEqual(packets[3].mouse.dy,round(200*65535/1439))

    def test_background_occluded_and_physically_held_mouse_do_not_click(self):
        self.backend.foreground_token.return_value=999
        self.assertFalse(self.backend.send_hue_click(123,1328,'clipstudiopaint',123))
        self.backend.foreground_token.return_value=123
        self.backend.user.GetAncestor.return_value=999
        self.assertFalse(self.backend.send_hue_click(123,1328,'clipstudiopaint',123))
        self.backend.user.GetAncestor.return_value=123
        self.backend.user.GetAsyncKeyState.return_value=0x8000
        self.assertFalse(self.backend.send_hue_click(123,1328,'clipstudiopaint',123))
        self.backend.user.SendInput.assert_not_called()
