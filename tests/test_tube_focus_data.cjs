const assert=require('node:assert/strict'),f=require('../static/tube-focus-data.js');
const tube={wall_loss_percent:91.47,minimum_wall_thickness_mm:.18,wall_loss_depth_mm:1.93,indications:[{axial_position_mm:839,position_quality:'RESULT_REPRESENTATIVE',wall_loss_percent:91.47}]};
const d=f.describe(tube,{length_mm:6000,nominal_thickness_mm:2.11});
assert.ok(Math.abs(d.indications[0].ratio-.1398333333)<1e-8);assert.equal(d.indications[0].measured,false);assert.equal(d.indications[0].angle,null);assert.ok(Math.abs(d.retained-.085308)<1e-6);
assert.equal(f.ratio(839000,6000),null);assert.equal(f.ratio(-1,6000),null);assert.equal(f.ratio(null,6000),null);assert.equal(f.ratio(839,null),null);assert.equal(f.ratio(6000,6000),1);assert.equal(f.ratio(0,6000),0);assert.equal(f.ratio(500000,1000000),.5);
assert.equal(f.describe(tube,{length_mm:6000}).inferred,true);assert.equal(f.describe({},{}).retained,null);
assert.equal(f.describe({...tube,minimum_wall_thickness_mm:3},{nominal_thickness_mm:2.11}).retained,null);
assert.equal(f.describe({indications:[{axial_position_mm:100,position_quality:'MEASURED',circumferential_angle_deg:90}]},{length_mm:6000}).indications[0].measured,true);
console.log('6000mm/839mm/91.47%, representative position, missing/outside/long tube, measured angle and invalid thickness passed');
