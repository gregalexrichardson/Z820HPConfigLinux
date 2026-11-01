import contextlib
import curses
import io
import unittest
from unittest.mock import patch
import tui

class Window:
    def __init__(self, keys, size=(20,80)):
        self.keys = iter(keys); self.lines=[]; self.size=size
    def keypad(self, val): pass
    def getmaxyx(self): return self.size
    def erase(self): pass
    def addnstr(self, y, x, text, n, attr=0): self.lines.append(text[:n])
    def refresh(self): pass
    def get_wch(self): return next(self.keys)

class TuiTests(unittest.TestCase):
    def setUp(self):
        self.row = {'name':'Num Lock', 'type':'enumeration', 'read_only':False,
                    'value':'*Off,On', 'current_value':'Off', 'possible_values':['Off','On'], 'path':'Advanced'}
    def run_ui(self, keys, row=None, fail=False, size=(20,80)):
        win = Window(keys, size)
        writes=[]
        def read(_): return [row or self.row]
        def write(directory, rows, name, value, password):
            writes.append((name,value,password))
            if fail: raise ValueError('rejected')
            return 'Verified'
        with patch.object(curses, 'curs_set'):
            tui._run(win, None, read, write)
        return win, writes
    def test_select_confirm(self):
        win, writes=self.run_ui(['\n', curses.KEY_DOWN, '\n', 'y', 'x', 'q'])
        self.assertEqual(writes, [('Num Lock','On',None)])
        self.assertIn('Verified', win.lines)
    def test_cancel_before_write(self):
        _, writes=self.run_ui(['\n', curses.KEY_DOWN, '\n', 'n', 'q'])
        self.assertEqual(writes, [])
    def test_read_only(self):
        win, writes=self.run_ui(['\n','q'],dict(self.row,read_only=True))
        self.assertFalse(writes)
        self.assertTrue(any('cannot be edited' in s for s in win.lines))
    def test_failure(self):
        win, writes=self.run_ui(['\n', curses.KEY_DOWN, '\n', 'y', 'x', 'q'],fail=True)
        self.assertEqual(len(writes),1)
        self.assertTrue(any('rejected' in s for s in win.lines))
    def test_filter_and_small_terminal(self):
        win, writes=self.run_ui(['/','z','z','\n','q'])
        self.assertTrue(any('(0/1)' in s for s in win.lines))
        _, writes=self.run_ui(['\n','q'],size=(5,20))
        self.assertFalse(writes)
    def test_view_details(self):
        win, writes=self.run_ui(['d','q','q'])
        self.assertTrue(any('possible_values:' in s for s in win.lines))
        self.assertFalse(writes)
