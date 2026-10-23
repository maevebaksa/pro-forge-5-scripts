"""Macro interpreter tests, not hardware/firmware or switch-timing certification."""
import ast, configparser, copy, pathlib, re, shlex, sys
from types import SimpleNamespace as NS
import jinja2
ROOT=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/pf-new/config')
cp=configparser.RawConfigParser(strict=False,inline_comment_prefixes=('#',';'))
for name in ['mainsail.cfg','macros.cfg','calibrate-offsets.cfg']:
 cp.read(ROOT/name)
cp.read(pathlib.Path(__file__).with_name('reseat.cfg'))
env=jinja2.Environment(block_start_string='{%',block_end_string='%}',variable_start_string='{',variable_end_string='}',undefined=jinja2.StrictUndefined)
macros={s.split(' ',1)[1].upper():env.from_string(cp[s]['gcode']) for s in cp.sections() if s.startswith('gcode_macro ')}
for sec in cp.sections():
 if sec.startswith('delayed_gcode '):env.from_string(cp[sec]['gcode'])
class Stop(Exception):pass
class Sim:
 def __init__(self,mounted=-1,loose=(),printing=False,fail_pick=False,fail_push=False,fail_dock=False):
  self.p={};self.stack=[];self.trace=[];self.saved={};self.relative=False;self.g92=[0,0,0];self.phys=mounted
  self.loose=set(loose);self.fail_pick=fail_pick;self.fail_push=fail_push;self.fail_dock=fail_dock;self.pick_count=0;self.dock_count=0;self.home_count=0
  for sec in cp.sections():
   if sec.startswith('gcode_macro '):
    vals={}
    for key,val in cp[sec].items():
     if key.startswith('variable_'):vals[key[9:]]=ast.literal_eval(val)
    self.p[sec]=vals
  v={'active_tools':5}
  for i,k in enumerate(['zero','one','two','three','four']):
   v.update({k+'_select_x':-99,k+'_dock_x':-99,k+'_select_y':[6,109,211,313,417][i],k+'_dock_y':[6,109,213,315,417][i]})
   for ax in ['x','y','z']:v[k+'_'+ax+'_offset']=i*0.2
  self.p['save_variables']={'variables':v}
  self.p['toolhead']={'position':NS(x=100.,y=100.,z=10.),'axis_minimum':NS(x=-120,y=-20,z=-3.5),'axis_maximum':NS(x=500,y=450,z=500),'homed_axes':'xyz','extruder':'extruder' if mounted<1 else 'extruder'+str(mounted),'max_accel':5000.}
  old=max(mounted,0)*0.2
  self.p['gcode_move']={'gcode_position':NS(x=100-old,y=100-old,z=10-old+0.15),'homing_origin':NS(x=old,y=old,z=old-0.15)}
  self.p['print_stats']={'state':'printing' if printing else 'standby'};self.p['pause_resume']={'is_paused':False}
  self.p['configfile']={'settings':{'servo toolchanger':{'minimum_pulse_width':.0005,'maximum_pulse_width':.0025,'maximum_servo_angle':180},'idle_timeout':{'timeout':600}}}
  self.p['servo toolchanger']={'value':0.0}
  for i in range(5):self.p['extruder' if i==0 else 'extruder'+str(i)]={'temperature':20.,'target':210.}
  self.p['virtual_sdcard']={'is_active':printing};self.sensors()
 def sensors(self):
  self.p['gcode_button carriage_tool_sensor']={'state':'PRESSED' if self.phys>=0 else 'RELEASED'}
  for i in range(5):self.p['gcode_button t%d_dock_sensor'%i]={'state':'RELEASED' if i==self.phys or i in self.loose else 'PRESSED'}
 def hook(self,name,params):
  if name=='_RS_LOCK_CHECK':
   self.pick_count+=1
   if not self.fail_pick or (self.fail_pick=='once' and self.home_count>0):self.phys=int(params['TOOL'])
   self.sensors()
  if name=='_RS_DOCK_CHECK':
   self.dock_count+=1
   if not self.fail_dock or (self.fail_dock=='once' and self.dock_count>1):self.phys=-1
   self.sensors()
  if name=='_RS_PUSH_STEP' and not self.fail_push:
   if float(params['X'])<=-45:self.loose.discard(int(params['TOOL']));self.sensors()
 def run(self,name,**params):
  name=name.upper();params={k:str(v) for k,v in params.items()}
  assert name not in self.stack,('recursive macro',name,self.stack)
  self.hook(name,params);self.stack.append(name)
  try:
   def error(msg):raise Stop(msg)
   # Snapshot status for entire render, just as Klipper does.
   snap=copy.deepcopy(self.p)
   vars=next((v for k,v in snap.items() if k.lower()=='gcode_macro '+name.lower()),{})
   rendered=macros[name].render(printer=snap,params=params,rawparams='',action_raise_error=error,action_respond_info=lambda msg:'',**vars)
   for line in rendered.splitlines():
    line=line.split('#',1)[0].split(';',1)[0].strip()
    if line:self.execute(line)
  finally:self.stack.pop()
 def execute(self,line):
  self.trace.append(line)
  words=shlex.split(line);cmd=words[0].upper()
  args=dict(x.split('=',1) for x in words[1:] if '=' in x)
  if cmd in macros:return self.run(cmd,**args)
  if cmd=='SET_GCODE_VARIABLE':
   key=next(k for k in self.p if k.lower()=='gcode_macro '+args['MACRO'].lower());self.p[key][args['VARIABLE']]=ast.literal_eval(args['VALUE']);return
  if cmd=='G90':self.relative=False
  elif cmd=='G91':self.relative=True
  elif cmd in ['G0','G1']:
   assert all('=' not in x for x in words[1:]),line
   pos=self.p['toolhead']['position'];g=self.p['gcode_move']['gcode_position'];origin=self.p['gcode_move']['homing_origin']
   for x in words[1:]:
    ax=x[0].lower()
    if ax in 'xyz':
     val=float(x[1:]); val=val+getattr(g,ax) if self.relative else val
     setattr(g,ax,val);setattr(pos,ax,val+getattr(origin,ax)+self.g92['xyz'.index(ax)])
  elif cmd=='G28':
   assert self.phys<0,'homing with tool mounted';self.home_count+=1
  elif cmd=='SET_GCODE_OFFSET':
   origin=self.p['gcode_move']['homing_origin'];g=self.p['gcode_move']['gcode_position']
   for ax in 'xyz':
    if ax.upper() in args:
     new=float(args[ax.upper()]);setattr(g,ax,getattr(g,ax)+getattr(origin,ax)-new);setattr(origin,ax,new)
  elif cmd=='SAVE_GCODE_STATE':self.saved[args['NAME']]=(copy.deepcopy(self.p['gcode_move']['homing_origin']),self.relative,list(self.g92))
  elif cmd=='RESTORE_GCODE_STATE':
   origin,self.relative,self.g92=copy.deepcopy(self.saved[args['NAME']]);self.p['gcode_move']['homing_origin']=origin
   for ax in 'xyz':setattr(self.p['gcode_move']['gcode_position'],ax,getattr(self.p['toolhead']['position'],ax)-getattr(origin,ax)-self.g92['xyz'.index(ax)])
  elif cmd=='ACTIVATE_EXTRUDER':self.p['toolhead']['extruder']=args['EXTRUDER']
  elif cmd=='SET_SERVO':self.p['servo toolchanger']['value']=(.0005+.002*float(args['ANGLE'])/180)/.02
  elif cmd=='SET_VELOCITY_LIMIT':self.p['toolhead']['max_accel']=float(args['ACCEL'])
  elif cmd=='PAUSE_BASE':self.p['pause_resume']['is_paused']=True;self.p['print_stats']['state']='paused'
  elif cmd in ['M400','G4','UPDATE_DELAYED_GCODE','SET_IDLE_TIMEOUT','G92','M117','M118','RESPOND']:pass
  elif cmd in ['TURN_OFF_HEATERS','M84','M107','BED_MESH_CLEAR','RESUME_BASE']:pass
  else:raise AssertionError('unmodeled '+line)
 def state(self):return self.p['gcode_macro _RS']

def ok(title,sim,cmd,**args):
 sim.run(cmd,**args);assert not sim.state()['busy'];assert not sim.state()['failed'];print('PASS',title);return sim
for t in range(5):
 s=ok('empty pickup PH%d'%(t+1),Sim(),'SELECT_PH%d'%(t+1));assert s.phys==t
s=ok('mounted normal change',Sim(0),'SELECT_PH3');assert s.phys==2
s=ok('already selected',Sim(2),'SELECT_PH3');assert s.pick_count==0 and s.dock_count==0
s=Sim(0,[2,4]);s.state()['mounted']=0
s=ok('mounted two loose docks',s,'SELECT_PH2');assert s.phys==1 and not s.loose
s=ok('empty borrow reseat return select',Sim(-1,[2,4]),'SELECT_PH3');assert s.phys==2 and not s.loose and s.pick_count==2
s=ok('empty borrow reseat return DOCK',Sim(-1,[3]),'DOCK');assert s.phys==-1
s=ok('empty borrow PF_RESEAT',Sim(-1,[3]),'PF_RESEAT');assert s.phys==-1
s=Sim(1,[3]);s.state()['mounted']=1
s=ok('mounted PF_RESEAT retains tool',s,'PF_RESEAT');assert s.phys==1
s=ok('failed pickup XY retry',Sim(fail_pick='once'),'SELECT_PH2');assert s.home_count==1
s=ok('dock retry',Sim(0,fail_dock='once'),'DOCK');assert s.dock_count==2
s=ok('print return and live Z preserved',Sim(0,printing=True),'SELECT_PH3')
assert abs(s.p['gcode_move']['homing_origin'].z-(.4-.15))<1e-8
assert abs(s.p['gcode_move']['gcode_position'].z-10.15)<1e-8
assert abs(s.p['toolhead']['position'].z-10.4)<1e-8
s=ok('calibration pickup once',Sim(),'_CAL_SELECT_T2');assert s.pick_count==1
for label,sim,cmd in [('unknown mounted plus loose',Sim(0,[1]),'DOCK'),('no borrow candidate',Sim(-1,range(5)),'PF_RESEAT'),('push exhausted',Sim(-1,[2],printing=True,fail_push=True),'SELECT_PH3'),('pickup exhausted',Sim(printing=True,fail_pick=True),'SELECT_PH2'),('dock exhausted',Sim(0,fail_dock=True),'DOCK')]:
 try:sim.run(cmd);raise AssertionError('should stop')
 except Stop:pass
 assert sim.state()['failed'];print('PASS',label)
 assert sim.home_count<=1 and sim.dock_count<=2
 if label=='push exhausted':
  assert sim.p['pause_resume']['is_paused'];sim.fail_push=False
  sim.run('PF_RETRY');assert not sim.state()['busy'] and sim.phys==2
  assert sim.p['pause_resume']['is_paused'];print('PASS PF_RETRY completes without autoresume')
s=Sim();del s.p['save_variables']['variables']['one_x_offset']
try:s.run('SELECT_PH2');raise AssertionError('should stop')
except Stop:pass
assert not any(x.startswith('G1 ') for x in s.trace);print('PASS missing offsets fail before motion')
print('All macro templates compile; scenario checks passed.')
# Exhaust the physically consistent initial sensor combinations with a trusted
# mounted identity, and all 32 empty-carriage dock patterns.
for m in range(5):
 others=[i for i in range(5) if i!=m]
 for bits in range(16):
  loose=[t for j,t in enumerate(others) if bits & (1<<j)]
  s=Sim(m,loose);s.state()['mounted']=m;s.run('SELECT_PH%d'%((m+1)%5+1))
  assert s.phys==(m+1)%5 and not s.loose and not s.state()['busy']
for bits in range(32):
 s=Sim(-1,[i for i in range(5) if bits&(1<<i)])
 if bits==31:
  try:s.run('DOCK');raise AssertionError('no donor should stop')
  except Stop:pass
 else:
  s.run('DOCK');assert s.phys==-1 and not s.loose and not s.state()['busy']
print('PASS 112 initial sensor-pattern cases')
s=Sim(0,[2]);s.state()['mounted']=0
hook=s.hook
def lost(name,params):
 hook(name,params)
 if name=='_RS_PUSH_STEP':s.phys=-1;s.sensors()
s.hook=lost
try:s.run('PF_RESEAT');raise AssertionError('loss should stop')
except Stop:pass
assert s.state()['failed'];assert not any(x.startswith('G1 ') for x in s.trace[s.trace.index('_RS_PUSH_STEP TOOL=2 X=-42.5')+1:])
print('PASS carriage loss aborts before next push')
s=Sim();s.state()['busy']=1
try:s.run('SELECT_PH1');raise AssertionError('nested entry should stop')
except Stop:pass
assert not any(x.startswith(('G1 ', 'SET_SERVO ')) for x in s.trace);print('PASS reentrant toolchange rejected before motion')
for name in ['_delayed_post_select_check','_delayed_post_dock_check']:
 assert not cp['delayed_gcode '+name]['gcode'].strip()
print('PASS old timer bodies disabled')
