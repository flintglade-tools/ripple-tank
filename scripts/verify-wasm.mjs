import fs from 'node:fs';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
const {instance} = await WebAssembly.instantiate(fs.readFileSync('web/ripple.wasm'), {});
const e = instance.exports, encoder = new TextEncoder(), decoder = new TextDecoder();
function wasm(v) {
  const b=encoder.encode(JSON.stringify(v));
  const input = e.ripple_input_ptr();
  new Uint8Array(e.memory.buffer,input,b.length).set(b);
  e.ripple_request(b.length);
  return JSON.parse(decoder.decode(new Uint8Array(e.memory.buffer,e.ripple_output_ptr(),e.ripple_output_len())));
}
const commands=[{op:'new',config:{nx:64,ny:40,boundary:'periodic',damping:0},preset:'pulse'},
  {op:'advance',steps:128},{op:'snapshot'},
  {op:'paint',x:.4,y:.3,radius:.08,tool:'depth',depth_m:.003},
  {op:'paint',x:.7,y:.5,radius:.02,tool:'wall'},
  {op:'sources',sources:[{x:.2,y:.4,frequency_hz:5,amplitude_m:.0001,phase_rad:1.1,kind:'point',enabled:true}]},
  {op:'advance',steps:256},{op:'snapshot'},
  {op:'set',config:{surface_tension:0,boundary:'reflective'}},{op:'advance',steps:200},{op:'snapshot'}];
const native=spawnSync('target/release/flintglade-ripple',['serve'],{input:commands.map(v=>JSON.stringify(v)).join('\n')+'\n',maxBuffer:64*1024*1024,encoding:'utf8'});
assert.equal(native.status,0,native.stderr);
const expected=native.stdout.trim().split('\n').map(v=>JSON.parse(v));
let largest=0;
for(let i=0;i<commands.length;i++){
  const actual=wasm(commands[i]);assert.equal(actual.ok,true,actual.error);assert.equal(expected[i].ok,true);assert.equal(actual.view,expected[i].view);
  if(actual.snapshot){
    for(const key of ['eta','ux','uy','depth','intensity']){
      assert.equal(actual.snapshot[key].length,expected[i].snapshot[key].length);
      for(let j=0;j<actual.snapshot[key].length;j++){
        const delta=Math.abs(actual.snapshot[key][j]-expected[i].snapshot[key][j]);
        largest=Math.max(largest,delta);assert.ok(delta<1e-13,`${i} ${key}[${j}] Δ=${delta}`);
      }
    }
    assert.equal(actual.snapshot.time_s,expected[i].snapshot.time_s);
    assert.deepEqual(actual.snapshot.walls,expected[i].snapshot.walls);
  }
}
const state=expected.at(-1).snapshot;
assert.equal(wasm({op:'view',name:'depth'}).view,'depth');
assert.equal(wasm({op:'load',snapshot:state}).view,'height');
assert.equal(wasm({op:'snapshot'}).snapshot.eta.length,64*40);
const before=wasm({op:'snapshot'}).snapshot;
for(const snapshot of [{...state,version:9},{...state,eta:[0]},{...state,depth:state.depth.map(()=>-1)}]){
  assert.equal(wasm({op:'load',snapshot}).ok,false);
  assert.deepEqual(wasm({op:'snapshot'}).snapshot,before);
}
const pixels=new Uint8Array(e.memory.buffer,e.ripple_pixels_ptr(),e.ripple_pixels_len());
assert.equal(pixels.length,64*40*4);assert.ok(pixels.some(v=>v!==0));
console.log(JSON.stringify({pass:true,native_wasm_commands:commands.length,snapshot_fields_compared:5,largest_absolute_difference:largest,invalid_loads_preserve_state:3,wasm_bytes:fs.statSync('web/ripple.wasm').size}));
