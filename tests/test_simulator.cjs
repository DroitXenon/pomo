const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function setup(t) {
  const nodes = new Map();
  const events = {};
  const node = (id) => {
    if (!nodes.has(id)) {
      const element={children:[],hidden:false,width:640,height:480,attributes:{},
        datasetWrites:{},textWrites:0,
        setAttribute(name,value){this.attributes[name]=value;},
        getContext:()=>({clearRect(){},strokeRect(){}}),prepend(){},replaceChildren(){}};
      element.dataset=new Proxy({}, {set(target,name,value){
        element.datasetWrites[name]=(element.datasetWrites[name]||0)+1;
        target[name]=value;
        return true;
      }});
      let content='';
      Object.defineProperty(element,'textContent',{
        get:()=>content,set(value){content=value;element.textWrites++;}
      });
      nodes.set(id,element);
    }
    return nodes.get(id);
  };
  const previews=['ready','possible_absence','reminding','unavailable'].map(display=>{
    const button=node(`preview-${display}`);
    button.dataset.preview=display;
    return button;
  });
  const sockets=[];
  class Socket {
    static OPEN=1;
    constructor(){this.readyState=1;sockets.push(this);}
    close() {this.onclose?.();}
    send(value){this.sent=value;}
  }
  class Camera {update(){} stop(){}}
  const context = vm.createContext({
    document:{getElementById:node,querySelectorAll:()=>previews,createElement:()=>node('li'),
              addEventListener:(name,fn)=>{events[name]=fn;}},
    window:{location:{href:'http://localhost:8000/'},addEventListener:(name,fn)=>{events[name]=fn;}},
    location:{protocol:'http:'},WebSocket:Socket,CameraController:Camera,
    URL,Date,setTimeout,clearTimeout
  });
  vm.runInContext(fs.readFileSync('simulator/app.js','utf8'),context);
  t.after(()=>events.pagehide());
  const state = {protocol_version:6,type:'state',monitoring_enabled:true,display:'ready',
    camera_status:'available',revision:1,dev_controls:true,camera_session:'session',
    behaviour:{status:'present',armed:true,reminder_active:false,absence_seconds:0},
    head_direction:'left',observation:{presence:'present',reason:'usable',
      head_pose:{yaw:40,pitch:0,roll:0},blendshapes:{jawOpen:0.25}}};
  const message=(next)=>sockets[0].onmessage({data:JSON.stringify(next)});
  return {node,state,message,sockets};
}
test('shows observations without a reminder',t=>{
  const {node,state,message}=setup(t);
  message(state);
  assert.equal(node('face-presence').textContent,'Present');
  assert.equal(node('head-direction').textContent,'left');
  assert.equal(node('dismiss-reminder').hidden,true);
  assert.match(node('mouth-movement').textContent,/jawOpen: 0.25/);
});
test('real reminders can be dismissed while manual previews have no prompt',t=>{
  const {node,state,message,sockets}=setup(t);
  state.display='reminding';
  message(state);
  assert.equal(node('reminder-message').hidden,true);
  state.behaviour.reminder_active=true;
  message(state);
  assert.equal(node('dismiss-reminder').disabled,false);
  assert.equal(node('reminder-message').hidden,false);
  node('dismiss-reminder').onclick();
  assert.equal(JSON.parse(sockets[0].sent).type,'dismiss_reminder');
});
test('uncertain input has independent camera status',t=>{
  const {node,state,message}=setup(t);
  state.observation={presence:'unknown',reason:'low_light'};
  state.display='unavailable';
  state.behaviour.status='uncertain';
  message(state);
  assert.equal(node('face-presence').textContent,'Unknown');
  assert.equal(node('image-quality').textContent,'Low light');
  assert.match(node('detection-status').textContent,/reminders suspended/);
});

test('head direction and angles appear automatically',t=>{
  const {node,state,message}=setup(t);
  message(state);
  assert.equal(node('head-direction').textContent,'left');
  assert.match(node('head-angles').textContent,/Yaw 40°/);
  assert.match(node('head-angles').textContent,/roll 0°/);
});

test('eye and mouth movement have separate labels and scores',t=>{
  const {node,state,message}=setup(t);
  state.observation.eye_movement={eyeLeft:{direction:'up',blink_score:0.55},eyeRight:{direction:'right',blink_score:0.48}};
  state.observation.blendshapes={eyeBlinkLeft:0.33,eyeBlinkRight:0.288,
    jawOpen:0,mouthSmileLeft:0,mouthSmileRight:0};
  message(state);
  assert.equal(node('eye-movement').textContent,
    'eyeLeft: up · eyeRight: right · eyeBlinkLeft: 0.55 · eyeBlinkRight: 0.48');
  assert.equal(node('mouth-movement').textContent,
    'jawOpen: 0.00 · mouthSmileLeft: 0.00 · mouthSmileRight: 0.00');
  state.observation={presence:'unknown'};
  message(state);
  assert.equal(node('eye-movement').textContent,
    'eyeLeft: unknown · eyeRight: unknown · eyeBlinkLeft: — · eyeBlinkRight: —');
  assert.equal(node('mouth-movement').textContent,
    'jawOpen: — · mouthSmileLeft: — · mouthSmileRight: —');
});

test('blink display follows continuous scores independently of the closed label',t=>{
  const {node,state,message}=setup(t);
  state.observation.eye_movement={eyeLeft:{direction:'center',blink_score:0},
                                  eyeRight:{direction:'center',blink_score:0.2}};
  for (const [direction,score,text] of [
    ['center',0.50,'0.50'],['center',0.67,'0.67'],['center',0.83,'0.83'],
    ['closed',0.92,'0.92'],['closed',1,'1.00'],['closed',0.92,'0.92'],['center',0.5,'0.50']
  ]) {
    state.observation.eye_movement.eyeLeft={direction,blink_score:score};
    message(state);
    assert.match(node('eye-movement').textContent,new RegExp(`eyeLeft: ${direction}`));
    assert.ok(node('eye-movement').textContent.includes(`eyeBlinkLeft: ${text}`));
    assert.match(node('eye-movement').textContent,/eyeBlinkRight: 0.20/);
  }
});

test('vertical model signals are visible independently of blink and mouth scores',t=>{
  const {node,state,message}=setup(t);
  state.observation.blendshapes={eyeLookUpLeft:0.7,eyeLookDownLeft:0.1,
    eyeLookUpRight:0.2,eyeLookDownRight:0.6};
  message(state);
  assert.equal(node('eye-vertical-signals').textContent,
    'eyeLookUpLeft: 0.70 · eyeLookDownLeft: 0.10 · eyeLookUpRight: 0.20 · eyeLookDownRight: 0.60');
  state.observation=null;
  message(state);
  assert.equal(node('eye-vertical-signals').textContent,
    'eyeLookUpLeft: — · eyeLookDownLeft: — · eyeLookUpRight: — · eyeLookDownRight: —');
});

test('detection snapshots preserve manual expression and do not repaint unchanged robot content',t=>{
  const {node,state,message}=setup(t);
  state.display='possible_absence';
  message(state);
  const expressionWrites=node('screen').datasetWrites.display;
  const titleWrites=node('state-title').textWrites;
  for (const status of ['present','possible_absence','reminding','uncertain','stale']) {
    state.revision++;
    state.behaviour.status=status;
    state.behaviour.reminder_active=status==='reminding';
    message(state);
    assert.equal(node('screen').dataset.display,'possible_absence');
    assert.equal(node('preview-possible_absence').attributes['aria-pressed'],'true');
    assert.equal(node('preview-reminding').attributes['aria-pressed'],'false');
    assert.equal(node('screen').datasetWrites.display,expressionWrites);
    assert.equal(node('state-title').textWrites,titleWrites);
  }
  state.display='ready';
  message(state);
  assert.equal(node('screen').dataset.display,'ready');
  assert.equal(node('screen').datasetWrites.display,expressionWrites+1);
});

test('signed iris offsets are visible for center and upward evaluation',t=>{
  const {node,state,message}=setup(t);
  state.observation.eye_movement={eyeLeft:{direction:'up',vertical_offset:-0.125},
                                  eyeRight:{direction:'center',vertical_offset:0.015}};
  message(state);
  assert.equal(node('eye-vertical-offsets').textContent,'eyeLeft: -0.125 · eyeRight: 0.015');
  state.observation=null;
  message(state);
  assert.equal(node('eye-vertical-offsets').textContent,'eyeLeft: — · eyeRight: —');
});

test('absence duration and possible-absence status render from the same snapshot',t=>{
  const {node,state,message}=setup(t);
  state.observation={presence:'not_detected',reason:'no_face'};
  state.behaviour={status:'possible_absence',armed:false,absence_seconds:2.5,reminder_active:false};
  message(state);
  assert.equal(node('absence-duration').textContent,'2.5 s');
  assert.equal(node('detection-status').textContent,'Possible absence');
  assert.equal(node('screen').dataset.display,'ready');
});
