"""Credential-free JSONL fixture. Never launches Codex or sends network traffic."""
import json
import os
import sys

case, log = sys.argv[1:]
for line in sys.stdin:
    req = json.loads(line)
    method = req.get('method')
    with open(log, 'a', encoding='utf-8') as out:
        out.write(json.dumps({'method': method, 'id': req.get('id'), 'params': req.get('params'), 'blocked_environment_names_present':[n for n in ['SYMPHONY_G5_OBSERVER_KEY_HEX','SYMPHONY_G5_OBSERVER_EVENTS','GITHUB_TOKEN','GH_TOKEN','OPENAI_API_KEY','CODEX_API_KEY','AZURE_OPENAI_API_KEY','OPENAI_BASE_URL','OPENAI_API_BASE'] if n in os.environ]})+'\n')
    if 'id' not in req:
        continue
    result = {}
    if method == 'account/read':
        result = {'requiresOpenaiAuth': True, 'account': {'type': 'chatgpt'}}
        if case == 'api': result['account']['type'] = 'apiKey'
        if case == 'missing': result['account'] = None
        if case == 'no-auth': result['requiresOpenaiAuth'] = False
        if case == 'notice':
            print(json.dumps({'method':'account/updated','params':{'email':'STATIC_SENSITIVE_SENTINEL'}}),flush=True)
        if case == 'error':
            print(json.dumps({'id':req['id'],'error':{'message':'STATIC_SENSITIVE_SENTINEL'}}),flush=True)
            continue
    elif method == 'config/read':
        cfg={'model_provider':None,'model_providers':{},'forced_login_method':None,
             'service_tier':'default','openai_base_url':None,
             'chatgpt_base_url':'https://chatgpt.com/backend-api/'}
        if case == 'custom': cfg['openai_base_url']='https://proxy.invalid'
        if case == 'paid': cfg['service_tier']='fast'
        if case == 'fallback':cfg['paid_provider_fallback_configured']=True
        if case == 'metered': cfg['metered_fallback_configured']=True
        if case == 'provider-fallback': cfg['model_provider_fallback']='paid'
        if case == 'billing':cfg['billing_route']=0
        if case == 'partial':cfg.pop('openai_base_url')
        if case == 'explicit':cfg['model_provider']='openai'
        result={'config':cfg}
    elif method == 'thread/start':
        result={'thread':{'id':'STATIC_THREAD'}}
    elif method == 'turn/start':
        result={'turn':{'id':'STATIC_TURN'}}
    print(json.dumps({'id':req['id'],'result':result}),flush=True)
    if method == 'turn/start':
        print(json.dumps({'method':'turn/completed','params':{'turn':{'id':'STATIC_TURN','status':'completed'}}}),flush=True)
