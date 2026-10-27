"""In-process Qt workflow verification; no user's windows or input are controlled."""
import json
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
import ripple
from PySide6.QtTest import QTest

app = ripple.W.QApplication([])
app.setStyleSheet(ripple.STYLE)
w = ripple.Window()
w.show()
app.processEvents()
checks = []

def check(name, condition):
    assert condition, name
    checks.append(name)

check("initial physical grid", w.engine.last["config"]["nx"] == 200)
w.scenario.setCurrentText("Pulse")
check("preset injects real wave", w.engine.last["diagnostics"]["max_height_m"] > 0.00029)
QTest.mouseClick(w.play, ripple.QtCore.Qt.MouseButton.LeftButton)
QTest.qWait(150)
QTest.mouseClick(w.play, ripple.QtCore.Qt.MouseButton.LeftButton)
check("play advances simulation and pauses", w.engine.last["diagnostics"]["time_s"] > 0 and not w.running)
w.toggle()
box=w.controls["depth_m"][0]
box.setFocus()
box.lineEdit().selectAll()
QTest.keyClicks(box.lineEdit(),"12")
QTest.qWait(100)
check("typing survives running frames", box.lineEdit().text()=="12")
QTest.keyClick(box.lineEdit(),ripple.QtCore.Qt.Key.Key_Return)
check("live numeric edit reaches engine", w.engine.last["config"]["depth_m"]==0.012)
w.toggle()
before = w.engine.last["diagnostics"]["steps"]
w.step_once()
check("step advances exactly once", w.engine.last["diagnostics"]["steps"] == before+1)
w.tool.setCurrentText("wall")
w.apply_tool(.5,.5)
check("wall physically changes geometry", w.engine.request({"op":"probe","x":.5,"y":.5})["probe"]["solid"])
w.tool.setCurrentText("erase")
w.apply_tool(.5,.5)
check("erase reopens geometry", not w.engine.request({"op":"probe","x":.5,"y":.5})["probe"]["solid"])
w.tool.setCurrentText("depth")
w.paint_depth.setValue(2)
w.apply_tool(.5,.5)
check("depth brush uses millimeters", w.engine.request({"op":"probe","x":.5,"y":.5})["probe"]["depth_m"] == .002)
w.tool.setCurrentText("source")
w.apply_tool(.25,.3)
w.freq.setValue(6)
check("source controls update engine", w.engine.last["sources"][0]["frequency_hz"] == 6)
precise = dict(w.engine.last["sources"][0], phase_rad=10.0, frequency_hz=3.123456, radius_m=0.00812345)
w.perform({"op":"sources","sources":[precise]})
w.amp.setValue(0.16)
changed = w.engine.last["sources"][0]
check("source edit preserves unrelated precise parameters", all(changed[k]==precise[k] for k in precise if k!="amplitude_m"))
check("phase display represents imported angle modulo turn", abs(w.phase.value()-__import__('math').degrees(__import__('math').remainder(10.0,__import__('math').tau)))<0.051)
w.remove_source()
check("source removal changes driver list", not w.engine.last["sources"])
w.field.setFocus()
w.tool.setCurrentText("pulse")
before = w.engine.last["diagnostics"]["max_height_m"]
QTest.keyClick(w.field, ripple.QtCore.Qt.Key.Key_Right)
QTest.keyClick(w.field, ripple.QtCore.Qt.Key.Key_Return)
check("keyboard field editing", w.engine.last["diagnostics"]["max_height_m"] >= before)
w.perform({"op":"advance","steps":100})
with tempfile.TemporaryDirectory(prefix="ripple-qt-") as temp:
    file = Path(temp)/"experiment.ripple.json"
    w.write_snapshot(file)
    saved=json.loads(file.read_text())
    w.perform({"op":"clear"})
    w.load_snapshot(file)
    check("save/load full state", w.engine.request({"op":"snapshot"})["snapshot"] == saved)
    w.perform({"op":"advance","steps":2})
    w.reset_experiment()
    check("loaded experiment reset is exact", w.engine.request({"op":"snapshot"})["snapshot"] == saved)
    bad=Path(temp)/"bad.json"
    bad.write_text('{"version":999}')
    w.load_snapshot(bad)
    check("bad file preserves experiment", w.engine.request({"op":"snapshot"})["snapshot"] == saved)
    check("bad file has visible error", "missing field" in w.message.text().lower())
w.resize(960,680)
app.processEvents()
check("narrow desktop keeps canvas positive", w.field.width()>300 and w.field.height()>200)
dest=Path(os.environ.get("RIPPLE_VERIFY_DIR", "/tmp"))
dest.mkdir(parents=True,exist_ok=True)
w.grab().save(str(dest/"native-verified.png"))
w.close()
print(json.dumps({"pass":True,"checks":checks,"count":len(checks)}))
