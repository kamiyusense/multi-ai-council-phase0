import os,json,errno
from pathlib import Path
forbidden=('GITHUB_TOKEN','GH_TOKEN','OPENAI_API_KEY','CODEX_API_KEY','AZURE_OPENAI_API_KEY','OPENAI_BASE_URL','OPENAI_API_BASE','ACTIONS_RUNTIME_TOKEN','SYMPHONY_G5_OBSERVER_KEY_HEX','SYMPHONY_G5_OBSERVER_EVENTS')
assert not any(k in os.environ for k in forbidden)
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert os.geteuid()==65534 and int(status['CapEff'].strip(),16)==0 and status['NoNewPrivs'].strip()=='1'
mounts=[r.split() for r in Path('/proc/mounts').read_text().splitlines()]
ro={p:any(r[1]==p and 'ro' in r[3].split(',') for r in mounts) for p in ('/','/source','/candidate')}
assert all(ro.values())
assert os.statvfs('/').f_flag & os.ST_RDONLY
interfaces=[r.split(':')[0].strip() for r in Path('/proc/net/dev').read_text().splitlines()[2:]]
assert interfaces==['lo'] and not Path('/var/run/docker.sock').exists() and not Path('/run/docker.sock').exists()
limits={p:Path('/sys/fs/cgroup',p).read_text().strip() for p in ('memory.max','pids.max','cpu.max')}
assert limits['memory.max']=='268435456' and limits['pids.max']=='64'
quota,period=map(int,limits['cpu.max'].split());assert quota==2*period
attempts={}
for target in ('/isolation-root-write','/source/isolation-source-write','/candidate/isolation-candidate-write'):
 try:
  Path(target).write_text('must not succeed')
 except OSError as e:attempts[target]={'blocked':True,'errno':e.errno}
 else:raise RuntimeError('readonly write unexpectedly succeeded')
assert not Path('/source/.git').exists()
print(json.dumps({'runtime_isolation':'PASS','uid':os.geteuid(),'cap_eff':status['CapEff'].strip(),'no_new_privileges':True,'readonly':ro,'write_attempts':attempts,'interfaces':interfaces,'docker_socket':False,'forbidden_selector_names_present':[],'cgroup_limits':limits,'model_starts':0,'real_candidate_verified':False}))
