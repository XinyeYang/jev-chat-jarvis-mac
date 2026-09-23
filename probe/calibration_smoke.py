"""Native calibration smoke test using a supplied screenshot, never live credentials.

Example: python -B probe/calibration_smoke.py screenshot.png --window 1039 1055
         --region 672 51 361 799
Coordinates are window points. Does not save to the real user env or call a model.
"""
import argparse
import sys,time,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pathlib import Path
from unittest.mock import patch,Mock
import AppKit as A,Quartz as Q
from Foundation import NSDate,NSURL
import userconfig
app=A.NSApplication.sharedApplication();app.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
with patch.object(userconfig,'load'),patch.object(userconfig,'get',return_value=''):
 import hud
 with patch.object(hud,'make_judge',return_value=Mock()),patch.object(hud,'Generator',return_value=Mock()):
  h=hud.HudController.alloc().init()
h._paused=True
assert h._calibration is None and not h._calibrating
from calibration_ui import CalibrationController
from perception import WindowInfo
parser=argparse.ArgumentParser()
parser.add_argument('image')
parser.add_argument('--window',type=float,nargs=2,required=True)
parser.add_argument('--region',type=float,nargs=4,required=True)
args=parser.parse_args()
f=str(Path(args.image).resolve())
s=Q.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(f),None);i=Q.CGImageSourceCreateImageAtIndex(s,0,None)
win=WindowInfo(99,1,'微信',0,0,*args.window)
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'env';p.write_text('# test\nCUSTOM=preserved\n')
 with patch.object(userconfig,'env_files',return_value=[p]),patch('calibration_ui.find_wechat_window',return_value=win),patch('calibration_ui.capture_image',return_value=i):
  h.calibrateMessages_(None)
 c=h.calibration_controller
 assert h._calibrating
 scale=c.canvas.bounds().size.width/win.w
 c.canvas.selection=tuple(v*scale for v in args.region)
 c.preview_(None)
 limit=time.monotonic()+30
 while c.busy and time.monotonic()<limit:
  A.NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(.05))
 assert c.preview and c.save_button.isEnabled()
 # Render native content with its explicit background, controls and status.
 v=c.window.contentView();v.display();rep=v.bitmapImageRepForCachingDisplayInRect_(v.bounds());v.cacheDisplayInRect_toBitmapImageRep_(v.bounds(),rep)
 rep.representationUsingType_properties_(A.NSBitmapImageFileTypePNG,{}).writeToFile_atomically_('/tmp/jev-calibration-ui.png',True)
 with patch('calibration_ui.find_wechat_window',return_value=win):c.save_(None)
 assert h._calibration and h._calibration_wid==99 and not h._calibrating
 assert 'CUSTOM=preserved' in p.read_text() and p.stat().st_mode&0o777==0o600
 before=h._calibration
 with patch.object(userconfig,'env_files',return_value=[p]),patch('calibration_ui.find_wechat_window',return_value=win),patch('calibration_ui.capture_image',return_value=i):
  h.calibrateMessages_(None)
 h.calibration_controller.cancel_(None)
 assert h._calibration==before and not h._calibrating
 h.reanalyze_(None)
 assert h._calibration==before,'reanalyze must preserve calibration'
 with patch.object(userconfig,'env_files',return_value=[p]):h.clearCalibration_(None)
 assert h._calibration is None and not h._calibration_required
 print('PASS native HUD entry, preview, save, reanalyze, restore; no real credentials changed')
h.panel.orderOut_(None);h._ov_panel.orderOut_(None)
