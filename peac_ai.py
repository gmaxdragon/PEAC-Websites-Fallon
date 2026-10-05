"""Optional extractive summaries via local Ollama.
Only precomputed aggregate facts are sent. A model may select sentences, not
invent numbers or introduce raw notes/campaign text into the summary.
"""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request

class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_local(path: str, payload: dict) -> dict:
    req=urllib.request.Request('http://127.0.0.1:11434'+path,
        data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirects())
    with opener.open(req,timeout=8) as response:
        raw=response.read(100001)
    if len(raw)>100000: raise ValueError('Local response too large')
    result=json.loads(raw)
    if not isinstance(result,dict): raise ValueError('Invalid local response')
    return result


def select_summary(fallback: dict) -> dict:
    if os.getenv('PEAC_USE_OLLAMA','0')!='1': return dict(fallback)
    model=os.getenv('PEAC_OLLAMA_MODEL','llama3.2:3b')
    facts=fallback.get('facts',[])
    try:
        if not facts or len(model)>100 or 'cloud' in model.lower(): raise ValueError('Local model required')
        info=request_local('/api/show',{'model':model})
        if info.get('remote_host') or info.get('remote_model') or info.get('capabilities')==['remote']:
            raise ValueError('Remote models are not enabled for this app')
        prompt=('Select up to five relevant facts for a school program summary. '
                'Respond only with JSON {"indices":[0,1,...]}. Use the given fact indices. '
                'Do not write new facts.\n'+json.dumps(dict(enumerate(facts))))
        result=request_local('/api/generate',{'model':model,'prompt':prompt,'stream':False,'format':'json',
            'options':{'temperature':0,'num_predict':120}})
        chosen=json.loads(result['response'])['indices']
        if not isinstance(chosen,list) or not 1<=len(chosen)<=5 or any(type(i) is not int or not 0<=i<len(facts) for i in chosen):
            raise ValueError('Invalid selected facts')
        ids=list(dict.fromkeys(chosen))
        return {**fallback,'summary':' '.join(facts[i] for i in ids),'source':'ollama_selected_facts',
                'notice':'Local AI selected these highlights. The displayed sentences are computed facts, not model-written claims.'}
    except (ValueError,TypeError,KeyError,urllib.error.URLError,TimeoutError,OSError):
        return {**fallback,'notice':'Local AI unavailable or returned invalid output. Showing the computed factual summary.'}
