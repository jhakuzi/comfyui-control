const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../comfyui_control/mobile/web');
const sandbox = { window: {}, confirm: () => true, document: new Proxy({}, {get() { throw Error('Unexpected DOM access on load'); }}) };
vm.createContext(sandbox);
for (const name of ['feature_generate.js', 'feature_image_api.js', 'feature_image_actions.js'])
  vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), sandbox);
const plain = value => JSON.parse(JSON.stringify(value));

async function main() {
  let now = 0;
  const Feedback = sandbox.window.ComfyGenerateFeedback;
  const progress = new Feedback({now: () => now});
  assert.equal(progress.update({jobs:[{id:'old',status:'complete'}]}).kind, 'idle');
  const view = (status, extra = {}, state = {}) => progress.update({jobs:[{id:'job',status,...extra}], ...state});
  assert.equal(view('queued').kind, 'indeterminate');
  let result = view('running', {progress:{value:8,max:20}});
  assert.equal(result.progress, .4);
  assert.equal(result.label, 'Sampling · 40%');
  assert.equal(view('running', {}, {connected:false}).kind, 'paused');
  assert.equal(view('running', {phase:'processing'}).progress, .4);
  assert.equal(view('running', {progress:{value:20,max:20}}).label, 'Sampling · 100%');
  assert.equal(view('running', {progress:{value:20,max:20}}).progress, 1);
  assert.equal(view('running', {progress:{value:1,max:10}}).progress, .1);
  assert.equal(view('running', {phase:'sampling',progress:{value:99,max:100}}).progress, .99);
  assert.equal(view('running', {phase:'processing',progress:{value:99,max:100}}).kind, 'indeterminate');
  assert.equal(view('running', {phase:'preparing',progress:{value:4,max:10}}).label, 'Loading models');
  assert.equal(view('running', {progress:{value:4,max:0}}).kind, 'indeterminate');
  assert.equal(view('running', {progress:{value:'4',max:10}}).kind, 'indeterminate');
  assert.equal(view('complete').kind, 'success');
  now = 1500;
  assert.equal(view('complete').kind, 'idle');
  assert.equal(view('queued').kind, 'indeterminate');
  assert.equal(view('failed').kind, 'failed');
  view('queued');
  assert.equal(view('cancelled').kind, 'cancelled');
  progress.reset();
  assert.equal(view('complete').kind, 'idle');
  progress.rejected('rejected-job');
  assert.equal(progress.update().label, 'Submission failed');
  now += 1500;
  assert.equal(progress.update().kind, 'idle');
  const style = {}, button = {dataset:{}, style:{setProperty:(key,value)=>style[key]=value}, setAttribute:(key,value)=>button[key]=value};
  const label = {};
  Feedback.paint(button, label, result);
  assert.equal(label.textContent, 'Sampling · 40%');
  assert.equal(style['--generation-progress'], .4);
  assert.equal(button['aria-busy'], 'true');

  const API = sandbox.window.ComfyImageFeatureAPI;
  let pending = null, calls = [], accepted = [], attempts = 0;
  const api = new API({readPending:()=>pending,writePending:value=>pending=value,requestId:()=> 'same-request-id',
    accepted: job => accepted.push(job.id), api:async (url, options)=> {
      calls.push([url, plain(options)]);
      if (!attempts++) throw Error('Connection lost');
      return {job:{id:'same-request-id',status:'queued'}};
    }});
  await assert.rejects(api.workflow({id:'selected-image',modified:'123'},'edit',{prompt:'golden light'}), /Connection lost/);
  assert.equal(pending.action.prompt, 'golden light');
  await assert.rejects(api.workflow({id:'other'},'upscale'), /pending submission/);
  const job = await api.retry();
  assert.equal(job.id,'same-request-id');
  assert.equal(pending,null);
  assert.equal(calls[0][1].body,calls[1][1].body);
  assert.equal(calls[0][0],'/api/images/selected-image/actions');
  assert.deepEqual(accepted,['same-request-id']);
  // The live controller owns busy/reconnect/feedback around the same transport.
  let orchestrated=0;
  const integrated = new API({readPending:()=>pending,writePending:value=>pending=value,requestId:()=> 'integrated-id',
    api:async()=>({job:{id:'integrated-id'}}),submit:async value=> {
      orchestrated++;
      assert.equal(value,pending);
      return integrated.retry();
    }});
  await integrated.workflow({id:'selected',modified:'123'},'upscale');
  assert.equal(orchestrated,1);
  assert.equal(pending,null);
  api.api = async ()=> {const error = Error('Invalid');error.status=400;throw error;};
  await assert.rejects(api.workflow({id:'x',modified:'1'},'upscale',{multiplier:1.5}),/Invalid/);
  assert.equal(pending,null);
  api.api = async ()=> ({job:{id:'wrong'}});
  await assert.rejects(api.workflow({id:'x',modified:'1'},'upscale'),/pending request is retained/);
  assert.ok(pending);
  pending=null;
  assert.throws(()=> api.deletePermanently(['token'],false),/confirm/);
  api.api = async (url, options) => {calls.push([url, options]);return {};};
  await api.cleanupVRAM();
  assert.equal(calls.at(-1)[0],'/api/vram/cleanup');
  await api.deletePermanently(['token'],true);
  assert.deepEqual(JSON.parse(calls.at(-1)[1].body),{tokens:['token'],confirm:true});

  // A fast favourite refresh can advance selection while an action is pending.
  // It must re-enable the current controls using their current capabilities.
  class Element {
    constructor() {this.children=[];this.dataset={};this.classList={add(){}};}
    append(...nodes) {this.children.push(...nodes);}
    addEventListener() {}
    setAttribute(key,value) {this[key]=value;}
  }
  sandbox.document = {createElement:()=>new Element()};
  const capabilities = {kept:false,modified:'123',actions:Object.fromEntries(['keep','trash','edit','upscale'].map(key=>[key,{available:true}]))};
  let actionView, mutation;
  actionView = new sandbox.window.ComfySavedImageActions(new Element(), {
    api:async (url, options)=> {if(options) mutation=JSON.parse(options.body);return capabilities;},
    workflow:async()=>{},changed:async()=>actionView.select({id:'new-image',modified:'123',kept:true})
  });
  await actionView.select({id:'old-image',modified:'123',kept:false});
  await actionView.perform('keep');
  assert.equal(mutation.keep,true);
  assert.equal(actionView.item.id,'new-image');
  assert.equal(actionView.pending,false);
  assert.equal(actionView.buttons.get('keep').disabled,false);
  assert.equal(actionView.buttons.get('trash').textContent,'Delete');
  actionView.api = ()=> {throw Error('Disconnected selection must not request capabilities');};
  await actionView.select({id:'paused',kept:false},{connected:false});
  assert.ok([...actionView.buttons.values()].every(button=>button.disabled));
  assert.match(actionView.status.textContent,/Reconnect/);
  console.log('Unloaded feature state, exact retry, malformed/uncertain responses, safety confirmation and action-refresh race passed');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
