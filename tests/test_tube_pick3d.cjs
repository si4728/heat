const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),THREE=require('../static/vendor/three/three.min.js');
const source=fs.readFileSync('static/tube-map.js','utf8');
const fn=source.slice(source.indexOf('  function pickThreeTube('),source.indexOf('  function disposeGroup('));
const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(48,800/600,.1,100);camera.position.set(0,2,15);camera.lookAt(0,0,0);camera.updateProjectionMatrix();
const group=new THREE.Group();scene.add(group);const tubes=[{tube_id:1},{tube_id:2}];
for(let i=0;i<2;i++){const mesh=new THREE.Mesh(new THREE.CylinderGeometry(.03,.03,4,12),new THREE.MeshBasicMaterial());mesh.position.x=(i-.5)*4;mesh.userData.tube=tubes[i];group.add(mesh);}
const rect={left:20,top:30,width:800,height:600,right:820,bottom:630};
const state={extracted:false,three:{scene,camera,group,renderer:{domElement:{getBoundingClientRect:()=>rect}}}};
const ctx={THREE,state,tubeDimensions:()=>({height:4})};vm.createContext(ctx);vm.runInContext(fn,ctx);
function screen(mesh){scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);const p=mesh.getWorldPosition(new THREE.Vector3()).project(camera);return [rect.left+(p.x+1)*400,rect.top+(1-p.y)*300];}
for(let i=0;i<2;i++){const [x,y]=screen(group.children[i]);assert.equal(ctx.pickThreeTube(x,y).tube_id,i+1);assert.equal(ctx.pickThreeTube(x+5,y).tube_id,i+1);}
assert.equal(ctx.pickThreeTube(21,31),null);assert.equal(ctx.pickThreeTube(0,0),null);
group.rotation.y=.7;group.children[1].position.y=3;const [x,y]=screen(group.children[1]);assert.equal(ctx.pickThreeTube(x,y).tube_id,2);
state.extracted=true;assert.equal(ctx.pickThreeTube(x,y),null);
console.log('Real THREE raycast: both tubes, 5px near-miss, empty/outside, rotated/lifted geometry, single-view guard passed');
const draw=source.slice(source.indexOf('  function draw2d()'),source.indexOf('  function canMove('));
const drawCtx={state:{data:{tubes:[]}},canvas:{hidden:true,clientWidth:800,clientHeight:0},ctx:new Proxy({}, {get(){throw new Error('Hidden canvas must not render');}})};
vm.createContext(drawCtx);vm.runInContext(draw,drawCtx);assert.doesNotThrow(()=>drawCtx.draw2d());drawCtx.canvas.hidden=false;assert.doesNotThrow(()=>drawCtx.draw2d());drawCtx.canvas.clientHeight=600;drawCtx.canvas.clientWidth=0;assert.doesNotThrow(()=>drawCtx.draw2d());
console.log('3D hidden 2D canvas and zero-size resize regressions passed');
