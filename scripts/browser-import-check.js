// Run this function in an isolated local Ripple Tank page through a browser test runner.
async () => {
 const $=id=>document.getElementById(id);
 const wait=async p=>{for(let i=0;i<250;i++){if(p())return;await new Promise(r=>setTimeout(r,20));}throw Error('UI timeout');};
 await wait(()=>!$('open').disabled);
 if($('play').getAttribute('aria-pressed')==='true')$('play').click();
 $('view').value='depth';$('view').dispatchEvent(new Event('change'));
 await wait(()=>$('scale-quantity').textContent==='Water depth');
 const n=4096, source={x:.23456789,y:.3456789,frequency_hz:3.123456,amplitude_m:.00015,phase_rad:10,radius_m:.00812345,kind:'point',enabled:true};
 const snapshot={format:'flintglade-ripple',version:1,model:'linear-shallow-capillary-v1',config:{nx:64,ny:64,width_m:.8,depth_m:.008,gravity:9.81,surface_tension:.072,damping:.08,boundary:'reflective'},eta:Array.from({length:n},(_,i)=>.0003*Math.exp(-((i%64-31.5)**2+(Math.floor(i/64)-31.5)**2)/18)),ux:Array(n).fill(0),uy:Array(n).fill(0),depth:Array(n).fill(.008),walls:Array(n).fill(0),sources:[source],time_s:1.25,steps:1000,intensity:Array(n).fill(0)};
 const inject=text=>{const dt=new DataTransfer();dt.items.add(new File([text],'synthetic-square.ripple.json',{type:'application/json'}));$('file').files=dt.files;$('file').dispatchEvent(new Event('change',{bubbles:true}));};
 $('tab-water')?.click();$('depth').focus();$('depth').value='17';
 inject(JSON.stringify(snapshot));await wait(()=>$('status').textContent.startsWith('Loaded synthetic'));
 const rect=$('tank').getBoundingClientRect();
 const result={loaded:true,canvas:[$('tank').width,$('tank').height],aspect:rect.width/rect.height,view:$('view').value,legend:$('scale-quantity').textContent,high:$('scale-high').textContent,grid:$('resolution').value,inputCleared:$('file').value==='',inputsValid:[...document.querySelectorAll('input[type=number]')].every(e=>e.validity.valid)};
 result.authoritativeFocusedImport=$('depth').value==='8';if(!result.authoritativeFocusedImport)throw Error('Focused control did not follow authoritative import');
 if(result.view!=='height'||result.legend!=='Surface height'||result.high!=='+0.3 mm')throw Error('View/legend disagreement');
 $('amplitude').value='.16';$('amplitude').dispatchEvent(new Event('change'));
 await wait(()=>$('amplitude').value==='0.16');
 let blob;const original=URL.createObjectURL;
 try{URL.createObjectURL=value=>{blob=value;return original.call(URL,value);};$('save').click();await wait(()=>!!blob);const saved=JSON.parse(await blob.text());const out=saved.sources[0];result.sourceUntouchedParametersExact=Object.keys(source).every(k=>k==='amplitude_m'||out[k]===source[k]);result.changedAmplitude=out.amplitude_m;if(!result.sourceUntouchedParametersExact)throw Error('Source parameter drift');}finally{URL.createObjectURL=original;}
 $('step').click();await wait(()=>$('time').textContent!=='1.250 s');$('reset').click();await wait(()=>$('time').textContent==='1.250 s');result.resetExactTime=true;
 const before=$('height').textContent;inject('{"version":999}');await wait(()=>$('status').textContent.includes('missing field'));result.invalidFilePreservesField=$('height').textContent===before&&$('tank').width===64;result.invalidFileClearsInput=$('file').value==='';return result;
}
