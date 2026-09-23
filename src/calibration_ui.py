"""Native calibration on a frozen WeChat window snapshot; preview never calls models."""
import threading
import tempfile
from pathlib import Path
import objc
import AppKit as A
import Quartz as Q
from Foundation import NSObject, NSMakeRect, NSURL
from calibration import Calibration, validate_input_region
import ui_style
from perception import find_wechat_window, capture_image, capture_window, read_calibrated
from settings_config import read_document, write_settings
import userconfig


class SelectionView(A.NSView):
    def isFlipped(self): return True

    def drawRect_(self, rect):
        self.picture.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
            self.bounds(), NSMakeRect(0,0,0,0), A.NSCompositingOperationSourceOver, 1., True, None)
        A.NSColor.colorWithWhite_alpha_(0.,.30).set()
        mask = A.NSBezierPath.bezierPathWithRect_(self.bounds())
        if self.selection:
            mask.appendBezierPathWithRect_(NSMakeRect(*self.selection))
            mask.setWindingRule_(A.NSEvenOddWindingRule)
        mask.fill()
        if self.selection:
            ui_style.PALETTE["green"].set()
            border = A.NSBezierPath.bezierPathWithRect_(NSMakeRect(*self.selection))
            border.setLineWidth_(2); border.stroke()
        for m in self.messages:
            r=NSMakeRect(m.x*self.bounds().size.width,m.y*self.bounds().size.height,
                         m.w*self.bounds().size.width,m.h*self.bounds().size.height)
            (ui_style.PALETTE["amber"] if m.side=='unknown' else ui_style.PALETTE["green"]).set()
            A.NSBezierPath.bezierPathWithRect_(r).stroke()
            label={'them':'对方','me':'我','unknown':'未确认'}[m.side]
            A.NSString.stringWithString_(label).drawAtPoint_withAttributes_(
                (r.origin.x,max(0,r.origin.y-14)),
                {A.NSFontAttributeName:A.NSFont.boldSystemFontOfSize_(11),
                 A.NSForegroundColorAttributeName:ui_style.PALETTE["text"],
                 A.NSBackgroundColorAttributeName:A.NSColor.whiteColor()})

    def mouseDown_(self, event):
        if self.owner.busy: return
        p=self.convertPoint_fromView_(event.locationInWindow(),None)
        self.anchor=(p.x,p.y); self.edge=None
        if self.selection:
            x,y,w,h=self.selection
            for name,value,current in [('left',x,p.x),('right',x+w,p.x),('top',y,p.y),('bottom',y+h,p.y)]:
                if abs(value-current)<7:
                    self.edge=name; break
        self.owner.invalidate()

    def mouseDragged_(self, event):
        if self.owner.busy or not hasattr(self,'anchor'): return
        p=self.convertPoint_fromView_(event.locationInWindow(),None)
        px=max(0,min(p.x,self.bounds().size.width)); py=max(0,min(p.y,self.bounds().size.height))
        if self.edge:
            x,y,w,h=self.selection; r,b=x+w,y+h
            if self.edge=='left': x=min(px,r-5)
            if self.edge=='right': r=max(px,x+5)
            if self.edge=='top': y=min(py,b-5)
            if self.edge=='bottom': b=max(py,y+5)
            self.selection=(x,y,r-x,b-y)
        else:
            x,y=self.anchor
            self.selection=(min(x,px),min(y,py),abs(px-x),abs(py-y))
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event):
        self.mouseDragged_(event)


class CalibrationController(NSObject):
    @objc.python_method
    def build(self, callback, saved='', image=None, win=None, mode='messages', message_region=None):
        self.mode = mode
        self.message_region = message_region
        self.callback=callback; self.busy=False; self.preview=None; self.closed=False
        self.win=win or find_wechat_window()
        if self.win is None: raise ValueError('请先打开微信聊天窗口。')
        self.image=image if image is not None else capture_image(self.win.wid)
        if self.image is None:
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/'window.png'
                if capture_window(self.win.wid,path):
                    source=Q.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(path)),None)
                    self.image=Q.CGImageSourceCreateImageAtIndex(source,0,None) if source else None
        if self.image is None: raise ValueError('无法读取微信窗口，请检查屏幕录制权限。')
        self.path=userconfig.env_files()[0]
        self.original=read_document(self.path)
        palette = ui_style.PALETTE
        screen=A.NSScreen.mainScreen().visibleFrame().size
        scale=min(1.,min(1000,screen.width-96)/self.win.w,
                  min(660,screen.height-300)/self.win.h)
        cw,ch=self.win.w*scale,self.win.h*scale
        width=max(760,cw+48); height=ch+244
        self.window=A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0,0,width,height),A.NSWindowStyleMaskTitled|A.NSWindowStyleMaskClosable,
            A.NSBackingStoreBuffered,False)
        self.window.setReleasedWhenClosed_(False); self.window.setDelegate_(self)
        title = '校准输入区域' if mode == 'input' else '校准消息区域'
        self.window.setTitle_(title+' · 确认后立即生效')
        self.window.setLevel_(A.NSFloatingWindowLevel+1)
        self.window.setAppearance_(A.NSAppearance.appearanceNamed_(A.NSAppearanceNameAqua))
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(A.NSColor.clearColor())
        self.window.setHasShadow_(True)
        view=A.NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0,0,width,height))
        view.setMaterial_(A.NSVisualEffectMaterialSidebar)
        view.setBlendingMode_(A.NSVisualEffectBlendingModeBehindWindow)
        view.setState_(A.NSVisualEffectStateActive)
        view.setWantsLayer_(True)
        reduced=A.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceTransparency()
        surface=ui_style.SOLID_PALETTE if reduced else palette
        view.layer().setBackgroundColor_(surface['bg'].CGColor())
        self.window.setContentView_(view)
        view.addSubview_(ui_style.make_label(title,24,height-52,width-48,30,22,bold=True))
        instruction=('框选完整文字编辑区，排除表情、附件、语音和发送按钮。'
                     if mode == 'input' else
                     '框选双方头像、昵称和气泡；排除联系人列表、标题、公告和输入区。')
        view.addSubview_(ui_style.make_label(instruction,24,height-80,width-48,20,12,palette['muted']))
        card=ui_style.make_surface(12,surface['surface'],surface['edge'])
        card.setFrame_(NSMakeRect(16,116,width-32,ch+16));view.addSubview_(card)
        self.canvas=SelectionView.alloc().initWithFrame_(NSMakeRect((width-cw)/2,124,cw,ch))
        self.canvas.picture=A.NSImage.alloc().initWithCGImage_size_(self.image,(cw,ch))
        self.canvas.owner=self;self.canvas.selection=None;self.canvas.messages=[]
        self.canvas.setAccessibilityLabel_('微信窗口截图，拖动框选区域，拖动边缘调整')
        view.addSubview_(self.canvas)
        if saved:
            try:
                c=Calibration.parse(saved)
                if c.matches(self.win):self.canvas.selection=(c.x*scale,c.y*scale,c.width*scale,c.height*scale)
            except (ValueError,TypeError):pass
        notice=ui_style.make_surface(10,palette['amber'].colorWithAlphaComponent_(.10),
                                    palette['amber'].colorWithAlphaComponent_(.18))
        notice.setFrame_(NSMakeRect(24,64,width-48,42));view.addSubview_(notice)
        self.status=ui_style.make_label('拖动框选后预览；调整窗口、分栏或输入区后请重新校准。',
            36,74,width-72,22,12,palette['accent'],bold=True)
        view.addSubview_(self.status)
        hint=('仅在你点击「填入」时写入；有草稿则停止，不发送。' if mode=='input'
              else '预览仅本地 OCR · 输入区需单独校准才能填入')
        view.addSubview_(ui_style.make_label(hint,24,18,width-400,30,11,palette['muted']))
        for title,action,x in [('取消','cancel:',width-364),('预览识别','preview:',width-248),('确认并启用','save:',width-132)]:
            button=A.NSButton.buttonWithTitle_target_action_(title,self,action)
            button.setFrame_(NSMakeRect(x,18,108,32))
            ui_style.style_button(button,font_size=12,primary=action=='save:')
            view.addSubview_(button)
            if action=='save:':self.save_button=button;button.setEnabled_(False);button.setKeyEquivalent_('\r')
            if action=='preview:':
                self.preview_button=button
                if mode=='input':button.setTitle_('预览选区')
            if action=='cancel:':button.setKeyEquivalent_('\x1b')
        self.window.center();self.window.makeKeyAndOrderFront_(None)
        A.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        return self

    @objc.python_method
    def invalidate(self):
        self.preview=None;self.canvas.messages=[];self.save_button.setEnabled_(False)
        self.status.setStringValue_('选区已调整，请预览识别；可拖动四条边微调。')

    @objc.python_method
    def selection(self):
        if not self.canvas.selection: raise ValueError('请先拖动框选消息区域。')
        scale=self.canvas.bounds().size.width/self.win.w
        return Calibration(self.win.w,self.win.h,*(v/scale for v in self.canvas.selection))

    def preview_(self,sender):
        if self.busy:return
        try:
            c=self.selection()
            if self.mode=='input':validate_input_region(self.message_region,c)
        except ValueError as e:self.status.setStringValue_(str(e));return
        self.busy=True;self.save_button.setEnabled_(False);self.preview_button.setEnabled_(False)
        self.status.setStringValue_('正在检查选区…' if self.mode=='input' else '正在本地识别，请稍候…')
        def run():
            try:
                win=dict(wid=self.win.wid,w=self.win.w,h=self.win.h,x=self.win.x,y=self.win.y,title=self.win.title)
                if self.mode=='input':
                    res={'messages':[]}
                else:
                    res=read_calibrated(self.image,c,win,100)
                result=(c,res,None)
            except Exception as e:result=(c,None,type(e).__name__)
            self.performSelectorOnMainThread_withObject_waitUntilDone_('previewDone:',result,False)
        threading.Thread(target=run,daemon=True).start()

    def previewDone_(self,result):
        if self.closed:return
        self.busy=False;self.preview_button.setEnabled_(True)
        c,res,error=result
        if error:self.status.setStringValue_('识别失败：'+error);return
        self.preview=c;self.canvas.messages=res['messages'];self.canvas.setNeedsDisplay_(True)
        counts={s:sum(m.side==s for m in res['messages']) for s in ('them','me','unknown')}
        self.status.setStringValue_(f"预览：对方 {counts['them']} · 我 {counts['me']} · 未确认 {counts['unknown']}。确认选区后启用；未确认不自动回复。")
        if self.mode=='input':
            self.status.setStringValue_('请确认覆盖整个编辑区且不含工具栏；不会清空草稿或发送消息。')
        self.save_button.setEnabled_(True)

    def save_(self,sender):
        if self.preview is None or self.busy:return
        current=find_wechat_window(self.win.wid)
        if current is None or current.wid!=self.win.wid or not self.preview.matches(current):
            self.status.setStringValue_('微信窗口已改变，请取消后重新校准。');return
        try:
            write_settings(self.path,self.original,{('JEV_INPUT_REGION' if self.mode=='input' else 'JEV_MESSAGE_REGION'):self.preview.serialize()})
        except (ValueError,OSError) as e:self.status.setStringValue_(str(e));return
        self.callback(self.preview,self.win.wid);self.closed=True;self.window.close()

    def cancel_(self,sender):self.window.close()

    def windowWillClose_(self,notification):
        if not self.closed:
            self.closed=True;self.callback(None,None)
