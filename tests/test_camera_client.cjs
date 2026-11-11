// Optional Node checks for cancellation and upload lifecycle; no camera required.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const flush = () => new Promise(setImmediate);
const settings = {width:640, height:480, fps:10, jpeg_quality:0.75,
                  max_bytes:524288, timeout_seconds:3};
const state = (overrides = {}) => ({
  powered_on: true, monitoring_enabled: true, input_source: 'camera',
  camera_processor_ready: true, camera_capture_status: 'starting',
  camera_session: 'first', camera_settings: settings, ...overrides
});
function setup(getUserMedia, fetch) {
  const status = {textContent:''};
  const video = {srcObject:null, readyState:2, videoWidth:1280, videoHeight:720,
                 play:async()=>{}};
  const canvas = {getContext:()=>({drawImage:()=>{}}),
                  toBlob:(callback)=>callback({size:100})};
  const failures=[];
  const Controller=vm.runInNewContext(
    fs.readFileSync('simulator/camera.js','utf8')+'\nCameraController', {
      navigator:{mediaDevices:{getUserMedia}}, document:{createElement:()=>canvas},
      fetch, setTimeout, clearTimeout, AbortController
    });
  const camera=new Controller(video,status,(message)=>failures.push(message));
  return {camera,video,status,failures,canvas};
}
function stream() {
  const track={stopped:0,stop(){this.stopped++;}};
  return {track,getTracks:()=>[track],getVideoTracks:()=>[track]};
}
test('permission granted after pause immediately releases camera', async()=>{
  let grant;
  const media=stream();
  const {camera,video}=setup(()=>new Promise((resolve)=>{grant=resolve;}));
  camera.update(state());
  camera.update(state({camera_session:null,monitoring_enabled:false,camera_capture_status:'paused'}));
  grant(media);
  await flush();
  assert.equal(media.track.stopped,1);
  assert.equal(video.srcObject,null);
});
test('uploads are sequential, frames fit limits, and stop aborts upload', async()=>{
  const media=stream();
  let calls=0,signal;
  const {camera,canvas}=setup(async()=>media,async(_url,options)=>{
    calls++;
    signal=options.signal;
    await new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(new Error('aborted'))));
  });
  camera.update(state());
  await flush();
  camera.update(state());
  assert.equal(calls,1);
  assert.equal(canvas.width,640);
  assert.equal(canvas.height,360);
  camera.stop();
  await flush();
  assert.equal(signal.aborted,true);
  assert.equal(media.track.stopped,1);
});
test('permission denial reports failure and retains useful status',async()=>{
  const {camera,status,failures}=setup(async()=>{throw {name:'NotAllowedError'};});
  camera.update(state());
  await flush();
  camera.update(state({camera_session:null,camera_capture_status:'unavailable'}));
  assert.equal(failures.length,1);
  assert.match(status.textContent,/permission denied/);
});

test('idle detection snapshots do not reset the video element',()=>{
  const {camera,video}=setup(()=>Promise.reject(new Error('not expected')));
  let resets=0;
  Object.defineProperty(video,'srcObject',{get:()=>null,set(){resets++;}});
  camera.update(state({camera_session:null,monitoring_enabled:false,camera_capture_status:'paused'}));
  camera.update(state({camera_session:null,monitoring_enabled:false,camera_capture_status:'paused'}));
  assert.equal(resets,0);
});

test('capture requires power, monitoring, camera source, processor readiness and an owner token', async()=>{
  let calls=0;
  const {camera}=setup(()=>{calls++; return new Promise(()=>{});});
  for(const overrides of [
    {powered_on:false}, {monitoring_enabled:false}, {input_source:'simulated'},
    {camera_processor_ready:false}, {camera_session:null}
  ]) camera.update(state(overrides));
  await flush();
  assert.equal(calls,0);
  camera.update(state());
  assert.equal(calls,1);
  camera.stop();
});

test('switching to simulated input cancels a pending camera permission request', async()=>{
  let grant;
  const media=stream();
  const {camera,status,video}=setup(()=>new Promise(resolve=>{grant=resolve;}));
  camera.update(state());
  camera.update(state({input_source:'simulated',camera_session:null}));
  grant(media);
  await flush();
  assert.equal(media.track.stopped,1);
  assert.equal(video.srcObject,null);
  assert.match(status.textContent,/simulated input/);
});

test('stopping while reading the upload response aborts it and suppresses late completion',async()=>{
  const media=stream();
  let finish,signal,calls=0;
  const {camera,status,failures}=setup(async()=>media,async(_url,options)=>{
    calls++;
    signal=options.signal;
    return {ok:true,json:()=>new Promise(resolve=>{finish=resolve;})};
  });
  camera.update(state());
  await flush();
  assert.equal(calls,1);
  camera.update(state({input_source:'simulated',camera_session:null}));
  assert.equal(signal.aborted,true);
  finish({sequence:0});
  await flush();
  assert.match(status.textContent,/simulated input/);
  assert.equal(failures.length,0);
  assert.equal(calls,1);
});

test('a late JPEG encoder callback cannot upload after camera capture stops',async()=>{
  const media=stream();
  let encoded,calls=0;
  const {camera,canvas}=setup(async()=>media,async()=>{calls++; return {ok:true,json:async()=>({sequence:0})};});
  canvas.toBlob=callback=>{encoded=callback;};
  camera.update(state());
  await flush();
  camera.stop();
  encoded({size:100});
  await flush();
  assert.equal(calls,0);
  assert.equal(media.track.stopped,1);
});

test('an upload rejection releases camera resources and reports one recoverable failure',async()=>{
  const media=stream();
  const {camera,status,failures}=setup(async()=>media,async()=>({ok:false,status:413}));
  camera.update(state());
  await flush();
  assert.equal(media.track.stopped,1);
  assert.equal(camera.session,null);
  assert.equal(failures.length,1);
  assert.match(status.textContent,/413/);
});

test('playback denial after camera permission is not reported as capture denial',async()=>{
  const media=stream();
  let captures=0,uploads=0;
  const {camera,video,status,failures}=setup(async()=>{captures++; return media;},async()=>{uploads++;});
  video.play=async()=>{throw {name:'NotAllowedError',message:'private native detail'};};
  camera.update(state());
  await flush();
  assert.equal(captures,1);
  assert.equal(uploads,0);
  assert.equal(video.muted,true);
  assert.equal(video.playsInline,true);
  assert.match(status.textContent,/permission was granted.*playback was blocked/);
  assert.doesNotMatch(status.textContent,/permission denied|private native detail/);
  assert.equal(failures.length,1);
  assert.equal(media.track.stopped,1);
});

test('stream attachment errors are identified before playback and upload',async()=>{
  const media=stream();
  let uploads=0;
  const {camera,video,status}=setup(async()=>media,async()=>{uploads++;});
  Object.defineProperty(video,'srcObject',{get:()=>null,set(value){if(value!==null)throw new Error('private attachment detail');}});
  camera.update(state());
  await flush();
  assert.equal(uploads,0);
  assert.equal(media.track.stopped,1);
  assert.match(status.textContent,/could not attach the video stream/);
  assert.doesNotMatch(status.textContent,/private attachment detail/);
});

test('playback completing after pause cannot restart encoding or upload',async()=>{
  const media=stream();
  let finishPlayback,uploads=0;
  const {camera,video,status,failures}=setup(async()=>media,async()=>{uploads++;});
  video.play=()=>new Promise(resolve=>{finishPlayback=resolve;});
  camera.update(state());
  await flush();
  camera.update(state({monitoring_enabled:false,camera_session:null,camera_capture_status:'paused'}));
  finishPlayback();
  await flush();
  assert.equal(uploads,0);
  assert.equal(media.track.stopped,1);
  assert.equal(failures.length,0);
  assert.equal(video.srcObject,null);
  assert.equal(status.textContent,'Camera paused');
});

test('missing canvas context and empty JPEG encoding have specific diagnostics',async()=>{
  for(const failure of ['context','null-frame','empty-frame','drawing']) {
    const media=stream();
    let uploads=0;
    const {camera,canvas,status,failures}=setup(async()=>media,async()=>{uploads++;});
    if(failure==='context')canvas.getContext=()=>null;
    if(failure==='null-frame')canvas.toBlob=callback=>callback(null);
    if(failure==='empty-frame')canvas.toBlob=callback=>callback({size:0});
    if(failure==='drawing')canvas.getContext=()=>({drawImage(){throw new Error('private encoder detail');}});
    camera.update(state());
    await flush();
    assert.equal(uploads,0);
    assert.equal(media.track.stopped,1);
    assert.equal(failures.length,1);
    assert.match(status.textContent,failure==='context'?/frame encoding is unavailable/:failure==='drawing'?/JPEG frame encoding failed/:/JPEG encoding returned no frame/);
    assert.doesNotMatch(status.textContent,/permission denied|private encoder detail/);
  }
});

test('a rejected fetch is reported as an upload failure without exposing native details',async()=>{
  const media=stream();
  const {camera,status,failures}=setup(async()=>media,async()=>{throw new Error('private URL or device detail');});
  camera.update(state());
  await flush();
  assert.match(status.textContent,/Camera frame upload failed/);
  assert.doesNotMatch(status.textContent,/permission denied|private URL or device detail/);
  assert.equal(failures.length,1);
  assert.equal(media.track.stopped,1);
});

test('hidden-tab reason survives unavailable snapshots during permission and active capture',async()=>{
  const reason='Pomo tab hidden. Keep this tab visible and retry the camera.';
  for(const pendingPermission of [true,false]) {
    const media=stream();
    let grant;
    const {camera,status,failures}=setup(pendingPermission?()=>new Promise(resolve=>{grant=resolve;}):async()=>media,async(_url,options)=>new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('aborted')))));
    camera.update(state());
    await flush();
    const generation=camera.generation;
    camera.fail(reason,generation);
    camera.fail(reason,generation);
    camera.update(state({camera_session:null,camera_capture_status:'unavailable'}));
    if(pendingPermission)grant(media);
    await flush();
    assert.equal(failures.length,1);
    assert.equal(status.textContent,reason);
    assert.equal(media.track.stopped,1);
    assert.equal(camera.session,null);
  }
});
