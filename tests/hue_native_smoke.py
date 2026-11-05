"""Opt-in Windows click verification against this process's isolated Qt receiver."""
import argparse
import json
from pathlib import Path
import sys
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget
from altclipctrl.platforms import WindowsBackend
from altclipctrl.pointer import cursor_position


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
    if sys.platform!='win32':raise RuntimeError('Windows only')
    app=QApplication([])
    backend=WindowsBackend(lambda *_:False,lambda *_:None)
    events=[]
    class Receiver(QWidget):
        def mousePressEvent(self,event):events.append(('down',event.position().x(),event.position().y()))
        def mouseReleaseEvent(self,event):events.append(('up',event.position().x(),event.position().y()))
    receiver=Receiver();receiver.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint);receiver.setWindowTitle('Alt Clip Ctrl · Isolated hue click check')
    receiver.resize(240,180);receiver.move(350,250);receiver.show();receiver.raise_();receiver.activateWindow()
    result={}
    def finish():
        try:
            assert [e[0] for e in events]==['down','up'],events
            assert all(abs(e[1]-120)<=2 and abs(e[2]-90)<=2 for e in events),events
            assert cursor_position()==result['cursor_before'],(cursor_position(),result)
            result['status']='PASS';result['events']=events
        except Exception as exc:
            result['status']='FAIL';result['error']=str(exc)
        args.report.write_text(json.dumps(result,indent=2),encoding='utf-8')
        receiver.close();app.quit()
    def run():
        try:
            handle=int(receiver.winId())
            from ctypes import wintypes as W
            import ctypes as C
            backend.user.ShowWindow.argtypes=[W.HWND,C.c_int]
            backend.user.SetForegroundWindow.argtypes=[W.HWND]
            backend.user.ShowWindow(handle,5)
            backend.user.SetForegroundWindow(handle)
            app.processEvents()
            result['receiver']=handle
            result['foreground']=backend.foreground_token()
            if backend.foreground_token()!=handle:
                result.update(status='BLOCKED', error='Windows did not allow the isolated receiver to acquire focus; no click was sent.')
                args.report.write_text(json.dumps(result,indent=2),encoding='utf-8')
                receiver.close();app.quit();return
            point=W.POINT(120,90)
            backend.user.ClientToScreen.argtypes=[W.HWND,C.POINTER(W.POINT)]
            assert backend.user.ClientToScreen(handle,C.byref(point))
            result['cursor_before']=cursor_position()
            assert backend.send_hue_click(point.x,point.y,'@self',handle),'Click was skipped'
            QTimer.singleShot(250,finish)
        except Exception as exc:
            result.update(status='FAIL',error=str(exc));args.report.write_text(json.dumps(result),encoding='utf-8');receiver.close();app.quit()
    QTimer.singleShot(500,run)
    app.exec()
    return 0 if result.get('status')=='PASS' else 2 if result.get('status')=='BLOCKED' else 1

if __name__=='__main__':raise SystemExit(main())
