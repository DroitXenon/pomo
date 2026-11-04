// Optional Node checks for cancellation and upload lifecycle; no camera required.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const flush = () => new Promise(setImmediate);
const settings = {width:640, height:480, fps:10, jpeg_quality:0.75,
                  max_bytes:524288, timeout_seconds:3};
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
  camera.update({camera_session:'first',camera_settings:settings});
  camera.update({camera_session:null,camera_status:'paused'});
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
  camera.update({camera_session:'first',camera_settings:settings});
  await flush();
  camera.update({camera_session:'first',camera_settings:settings});
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
  camera.update({camera_session:'first',camera_settings:settings});
  await flush();
  camera.update({camera_session:null,camera_status:'unavailable'});
  assert.equal(failures.length,1);
  assert.match(status.textContent,/permission denied/);
});

test('idle detection snapshots do not reset the video element',()=>{
  const {camera,video}=setup(()=>Promise.reject(new Error('not expected')));
  let resets=0;
  Object.defineProperty(video,'srcObject',{get:()=>null,set(){resets++;}});
  camera.update({camera_session:null,camera_status:'paused'});
  camera.update({camera_session:null,camera_status:'paused'});
  assert.equal(resets,0);
});
