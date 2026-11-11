import json,subprocess,sys,os
R="kamiyusense/multi-ai-council-phase0"
S=os.path.dirname(os.path.abspath(__file__))
def sh(*a): return subprocess.run(a,capture_output=True,text=True,cwd="/home/claude/multi-ai-council-phase0").stdout
def tree(ref):
    out=sh("git","ls-tree","-r",ref)
    d={}
    for l in out.splitlines():
        meta,path=l.split("\t",1); d[path]=meta.split()[2]
    return d
lanes={"#4 Relay":"refs/tmp/p4","#203 Blue":"origin/feature/blue-work-jules-webhook-loop","#217 Blue":"refs/tmp/p217","#220 LoopA":"refs/tmp/p220","Signal canonical":"origin/feature/signal-observed-v1","#236 Signal":"refs/tmp/p236"}
lt={k:tree(v) for k,v in lanes.items()}
refs={"main":tree("origin/main"),"carrier":tree("origin/feature/chat-work-command-bus"),"stack":tree("origin/claude/full-stack-verification-final")}
def ident_t(t,paths): return sum(1 for p,s_,_ in paths if t.get(p)==s_)
rows=[json.loads(l) for l in open(S+"/prs.jsonl")]
lane={4:"Relay lane PR",203:"Blue lane PR (ancestor of #217)",217:"Blue lane PR",220:"Claude x Jules Loop A lane PR",236:"Signal lane PR",237:"this batch: carrier->main",165:"Cloud Work yellow carrier",166:"Cloud Work green carrier",167:"Cloud Work blue carrier",171:"Cloud Work red carrier",172:"Cloud Work replacement proof"}
out=[]
for r in sorted(rows,key=lambda x:x['n']):
    n=r['n']
    rec=dict(n=n,head=r['head'][:8],base=r['base'],draft=r['draft'],title=r['title'][:70],nfiles=r['files'])
    if n in lane:
        rec.update(cls="F",note=lane[n]); out.append(rec); continue
    fs=[]
    for pg in (1,2,3):
        chunk=json.loads(sh("gh","api",f"repos/{R}/pulls/{n}/files?per_page=100&page={pg}"))
        fs+=chunk
        if len(chunk)<100: break
    rec['nfiles']=len(fs)
    if len(fs)>=300:
        rec.update(cls="H",note="300+ files, not blob-compared"); out.append(rec); continue
    paths=[(f['filename'],f['sha'],f['status']) for f in fs if f['status']!="removed"]
    if not paths:
        rec.update(cls="H",note="no added/modified files"); out.append(rec); continue
    def ident(t): return sum(1 for p,s,_ in paths if t.get(p)==s)
    def exist(t): return sum(1 for p,s,_ in paths if p in t)
    m,c,k=ident(refs['main']),ident(refs['carrier']),ident(refs['stack'])
    N=len(paths)
    rec['lanes']={k:ident_t(t,paths) for k,t in lt.items() if ident_t(t,paths)}
    rec.update(files=N,ident_main=m,ident_carrier=c,ident_stack=k,exist_stack=exist(refs['stack']))
    if m==N: rec.update(cls="A",note="identical in main")
    elif any(v==N for v in rec["lanes"].values()): rec.update(cls="B",note="identical in "+", ".join(k_ for k_,v in rec["lanes"].items() if v==N))
    elif k==N: rec.update(cls="B",note="identical in full-stack (a lane branch/PR carries it)")
    elif c==N: rec.update(cls="B",note="identical in carrier")
    elif rec['exist_stack']>0 and k>0: rec.update(cls="C",note=f"{k}/{N} files identical, others modified in stack")
    elif rec['exist_stack']==N: rec.update(cls="C",note="all paths exist in stack with different content (superseded/modified)")
    else: rec.update(cls="D?",note=f"{N-exist(refs['stack'])}/{N} paths absent from every lane tree: useful-unadopted candidate or UNKNOWN")
    out.append(rec)
json.dump(out,open(S+"/classified.json","w"),indent=1)
from collections import Counter
print(Counter(o['cls'] for o in out))
