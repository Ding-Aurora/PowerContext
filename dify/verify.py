"""Run against real PowerContext; fixture text is not a model-generated game round."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from datetime import datetime, timezone
import uuid
import yaml

ROOT=Path(__file__).resolve().parent

def main():
    dsl=yaml.safe_load((ROOT/'pawnshop.yml').read_text(encoding='utf-8-sig'))
    nodes={n['id']:n['data'] for n in dsl['workflow']['graph']['nodes']}
    for edge in dsl['workflow']['graph']['edges']:
        assert edge['source'] in nodes and edge['target'] in nodes
    funcs={}
    for key,node in nodes.items():
        if node['type']=='code':
            ns={}; exec(compile(node['code'],key,'exec'),ns); funcs[key]=ns['main']
    a=json.loads(funcs['110']('alice','one')['body'])
    assert a==json.loads(funcs['110']('alice','one')['body'])
    assert a!=json.loads(funcs['110']('bob','one')['body'])
    assert a!=json.loads(funcs['110']('alice','two')['body'])
    assert '失败' in funcs['190']('{}',500,'test')['answer']
    try: funcs['150']('{}',500)
    except ValueError: pass
    else: raise AssertionError('must reject service failure')
    report={'timestamp':datetime.now(timezone.utc).isoformat(),'dsl_static_checks':'passed','code_node_checks':'passed','dify_import':'NOT RUN','real_model_gameplay':'NOT RUN','fixture_note':'人工交易夹具，仅验证真实 PowerContext 读写，非实际 Dify 或 LLM 输出','powercontext_version':'1.5.1'}
    base=os.environ.get('POWERCONTEXT_URL','http://127.0.0.1:8000').rstrip('/')
    def post(path,payload):
        headers={'Content-Type':'application/json'}
        if os.environ.get('POWERCONTEXT_TOKEN'): headers['Authorization']='Bearer '+os.environ['POWERCONTEXT_TOKEN']
        with urlopen(Request(base+path,json.dumps(payload).encode(),headers,method='POST'),timeout=90) as r:
            return json.load(r)
    try:
        scope=post('/v1/scopes',{'title':'Pawnshop integration verification','summary':'Synthetic game fixture for actual memory roundtrip','idempotency_key':'test-'+uuid.uuid4().hex})
        sid=scope['scope_id']; report['scope_id']=sid
        empty=post('/v1/context/prepare',{'scope_id':sid,'query':'pawnledger','max_bytes':6000})
        assert empty['status']=='empty',empty
        payload=json.loads(funcs['170'](sid,'典当周一的伞','【柜台收据】已成交：周一的伞，换得一张周五通行证。')['body'])
        saved=post('/v1/memory/remember',payload)
        assert saved.get('records'),saved
        recalled=post('/v1/context/prepare',{'scope_id':sid,'query':'pawnledger','max_bytes':6000})
        assert recalled['status']=='ready' and '周一' in (recalled.get('content') or ''),recalled
        report.update(powercontext_roundtrip='passed',empty_response=empty,save_response=saved,recall_response=recalled)
    except Exception as exc:
        report.update(powercontext_roundtrip='FAILED',error=str(exc))
        raise
    finally:
        (ROOT/'evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: DSL code checks and REAL PowerContext empty -> save -> recall. Dify/model NOT RUN.')

if __name__=='__main__': main()

