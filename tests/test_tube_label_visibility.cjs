const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),THREE=require('../static/vendor/three/three.min.js');
const s=fs.readFileSync('static/tube-map.js','utf8'),fn=s.slice(s.indexOf('  function updateFocusLabelVisibility()'),s.indexOf('  function addFocusLabel('));
const camera=new THREE.PerspectiveCamera(48,800/600,.1,100);camera.position.set(0,0,15);camera.lookAt(0,0,0);
const group=new THREE.Group(),body=new THREE.Mesh(new THREE.CylinderGeometry(.4,.4,10,16));body.userData.focusTubeBody=true;group.add(body);
function label(x){const a=new THREE.Sprite();a.position.x=x;a.scale.set(2,.65,1);a.userData.focusLabel=true;group.add(a);return a;}
const overlap=label(0),clear=label(-5),state={extracted:true,three:{camera,focusGroup:group,renderer:{domElement:{clientWidth:800,clientHeight:600}}}};
const c={THREE,state};vm.createContext(c);vm.runInContext(fn,c);c.updateFocusLabelVisibility();assert.equal(overlap.visible,false);assert.equal(clear.visible,true);
group.rotation.y=Math.PI/2;c.updateFocusLabelVisibility();assert.equal(clear.visible,false);assert.equal(overlap.visible,false);
group.rotation.y=0;camera.position.z=7;camera.updateProjectionMatrix();c.updateFocusLabelVisibility();assert.equal(overlap.visible,false);
state.three.renderer.domElement.clientWidth=390;state.three.renderer.domElement.clientHeight=460;camera.aspect=390/460;camera.updateProjectionMatrix();c.updateFocusLabelVisibility();assert.equal(overlap.visible,false);
console.log('Overlapping labels hidden, clear label shown, 90-degree rotation, zoom and narrow viewport passed');
