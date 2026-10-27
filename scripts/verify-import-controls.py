"""Regression probes for authoritative imports, paused probes and supported window size."""
import json
import os
from pathlib import Path
import sys
import tempfile
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
import ripple
app=ripple.W.QApplication([])
ripple.configure(app)
results=[]
def case(name,probe):
    w=ripple.Window();w.show();app.processEvents()
    try:
        probe(w)
        results.append({'name':name,'pass':True})
    except Exception as e:
        results.append({'name':name,'pass':False,'error':str(e)})
    finally:w.close();app.processEvents()
def load(w,s):
    with tempfile.TemporaryDirectory(prefix='ripple-import-') as d:
        p=Path(d)/'synthetic.ripple.json';p.write_text(json.dumps(s));w.load_snapshot(p)
    app.processEvents()
def source_dimensions(w):
    s=w.engine.request({'op':'snapshot'})['snapshot'];s['config']['width_m']*=2
    load(w,s)
    c,s0=w.engine.last['config'],w.engine.last['sources'][0]
    expected=ripple.to_frac(s0['x'],c['nx'])*c['width_m']*100
    assert abs(w.source_x.value()-expected)<.0051,(w.source_x.value(),expected)
def focused_import(w):
    w.tabs.setCurrentIndex(2);box=w.controls['depth_m'][0];box.setFocus();app.processEvents()
    assert box.hasFocus(),'test requires actual focused Water control'
    s=w.engine.request({'op':'snapshot'})['snapshot'];s['config']['depth_m']=.012;s['depth']=[.012]*len(s['depth'])
    load(w,s)
    assert w.engine.last['config']['depth_m']==.012
    assert box.value()==12,(box.value(),12)
    w.field.setFocus();w.step_once();assert box.value()==12

def paused_depth(w):
    w.scenario.setCurrentText('Empty tank');w.tool.setCurrentText('probe');w.apply_tool(.72,.5)
    w.tool.setCurrentText('depth');w.paint_depth.setValue(2);w.apply_tool(.72,.5)
    assert w.engine.request({'op':'probe','x':.72,'y':.5})['probe']['depth_m']==.002
    assert w.probe_depth.text()=='H 2.00 mm',w.probe_depth.text()
def paused_height(w):
    w.scenario.setCurrentText('Empty tank');w.tool.setCurrentText('probe');w.apply_tool(.72,.5)
    w.tool.setCurrentText('pulse');w.apply_tool(.72,.5)
    v=w.engine.request({'op':'probe','x':.72,'y':.5})['probe']['height_m']*1000
    assert v>.2
    assert abs(float(w.probe_value.text().replace('−','-').split()[0])-v)<.000051,(w.probe_value.text(),v)
    assert len({t for t,_ in w.trace.points})==len(w.trace.points),'duplicate-time trace samples'
def probe_tie(w):
    c=dict(w.engine.last['config'],nx=34,ny=34)
    assert w.perform({'op':'new','preset':'empty','config':c})
    w.field.probe=(.5,.5);w.update_probe()
    expected=(17.5/34)*c['width_m']*100
    assert w.probe_pos.text()==f'x {ripple.fixed(expected,1)} cm, y {ripple.fixed(expected,1)} cm',w.probe_pos.text()
def clipping(w):
    w.resize(960,680);w.scenario.setCurrentText('Empty tank')
    w.perform({'op':'pulse','x':.5,'y':.5,'radius':.03,'amplitude_m':.002});app.processEvents();w.grab();app.processEvents()
    assert w.clip.isVisible(),'pulse must exercise the visible clipping message'
    assert w.minimumSizeHint().width()<=960, w.minimumSizeHint().width()
    for button in w.view.buttons.values():
        assert button.width()>=button.fontMetrics().horizontalAdvance(button.text())+12,button.text()
    assert w.field.width()>300 and w.field.height()>200
for name,fn in [('source dimensions',source_dimensions),('focused import',focused_import),('paused depth probe',paused_depth),('paused height probe',paused_height),('probe rounding tie',probe_tie),('960px clipping layout',clipping)]:case(name,fn)
print(json.dumps({'pass':all(r['pass'] for r in results),'checks':results,'count':len(results)}))
sys.exit(0 if all(r['pass'] for r in results) else 1)
