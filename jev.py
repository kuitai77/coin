"""TypeSafe Jev adapter. Source: https://docs.typesafe.ai/api (2026-09-22).
Only sends public market data and user-configured strategy descriptions.
Never sends API secrets in the payload. No Binance order capability.
"""
import hashlib
import json
import math
import os
import urllib.request
from pathlib import Path

ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
DESCRIPTIONS = {
    'trend': 'EMA trend alignment plus close crossing back over the pullback EMA; short is the exact inverse.',
    'breakout': 'Close breaks prior lookback high/low, volume exceeds its prior average multiplier, and slow EMA agrees.',
    'range': 'Small trend/slow EMA separation; previous close outside Bollinger band and current close re-enters; previous RSI is extreme.'
}

class CallBudgetExceeded(RuntimeError):
    pass

def load_config(path='conditions.json'):
    cfg = json.loads(Path(path).read_text(encoding='utf-8'))
    for key in ['initial_equity','risk_per_trade','max_notional_equity_ratio','daily_loss_limit','max_drawdown_limit','stop_atr','quantity_step','minimum_notional']:
        if not isinstance(cfg[key], (float,int)) or not math.isfinite(cfg[key]) or cfg[key]<=0:
            raise ValueError(f'Invalid positive setting: {key}')
    for key in ['risk_per_trade','daily_loss_limit','max_drawdown_limit']:
        if cfg[key]>=1: raise ValueError(f'{key} must be below 1')
    for key in ['fee_per_side','slippage_per_side']:
        if not 0 <= cfg[key] < .1: raise ValueError(f'Invalid cost: {key}')
    if cfg['max_notional_equity_ratio']>2:
        raise ValueError('Research simulator supports a maximum 2x exposure; liquidation is not simulated.')
    if cfg['symbol']!='BTCUSDT' or cfg['interval']!='15m':
        raise ValueError('This initial data pipeline supports BTCUSDT 15m only.')
    for key in ['max_holding_bars','cooldown_bars']:
        if not isinstance(cfg[key],int) or cfg[key]<1:raise ValueError(f'Invalid integer: {key}')
    iv=cfg['indicators']
    for k in ['pullback_ema','trend_ema','slow_ema','atr_period','rsi_period','breakout_bars','volume_bars','bollinger_bars']:
        if not isinstance(iv[k],int) or not 2<=iv[k]<=300:raise ValueError('Indicator period must be 2..300: '+k)
    for k in ['volume_multiplier','bollinger_std','range_ema_distance']:
        if not isinstance(iv[k],(float,int)) or not math.isfinite(iv[k]) or iv[k]<=0:raise ValueError('Invalid indicator: '+k)
    for k in ['range_rsi_long','range_rsi_short']:
        if not 0<=iv[k]<=100:raise ValueError('Invalid RSI threshold')
    for k in ['entry_conditions','exit_conditions']:
        if not isinstance(cfg['jev'][k],list) or not cfg['jev'][k] or not all(isinstance(x,str) and x.strip() for x in cfg['jev'][k]):raise ValueError('Conditions must be a nonempty list of text')
    for value in cfg['target_atr'].values():
        if not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise ValueError('Invalid target ATR')
    for key in ['min_confidence','minimum_choice_probability']:
        if not 0<=cfg['jev'][key]<=1:raise ValueError(f'Invalid threshold: {key}')
    return cfg

def hard_checks(snapshot, checks):
    ops={'gt':lambda a,b:a>b,'gte':lambda a,b:a>=b,'lt':lambda a,b:a<b,'lte':lambda a,b:a<=b}
    for item in checks:
        op=ops.get(item.get('op'))
        value=snapshot['indicators'].get(item.get('field'))
        threshold=item.get('value')
        if op is None or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in [value,threshold]):
            raise ValueError('Unknown or invalid extra_entry_checks field/operator/value')
        if not op(value,threshold):return False
    return True

def make_payload(snapshot,cfg):
    return {
        'model':cfg['jev']['model'],
        'state':snapshot,
        'questions':{
            'entry_fit':{
                'type':'choice',
                'instructions':{'task':'Evaluate ONLY entry_conditions using the supplied state; answer UNKNOWN when evidence is absent. Numeric rules cannot be overridden.',
                                'entry_conditions':cfg['jev']['entry_conditions']},
                'criteria':{'ALLOW':'Proposed entry satisfies all supplied entry conditions.','BLOCK':'At least one entry condition is contradicted.','UNKNOWN':'No proposed entry, missing evidence, or ambiguous conditions.'}
            },
            'exit_action':{
                'type':'choice',
                'instructions':{'task':'Evaluate ONLY exit_conditions for the existing position. Do not infer a position if it is null.',
                                'exit_conditions':cfg['jev']['exit_conditions']},
                'criteria':{'CLOSE':'Existing position clearly meets an early-exit condition.','HOLD':'No early-exit condition holds.','UNKNOWN':'No position, missing evidence, or ambiguity.'}
            }
        }
    }

def validate_answer(raw,key,expected):
    a=raw['answers'][key]
    if a.get('type')!='choice' or a.get('choice') not in expected:raise ValueError('Invalid Jev choice')
    p=a['probabilities']; confidence=a['confidence']
    if set(p)!=set(expected):raise ValueError('Incomplete probability distribution')
    vals=list(p.values())+[confidence]
    if any(isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) or not 0<=x<=1 for x in vals):raise ValueError('Invalid probability/confidence')
    if abs(sum(p.values())-1)>.001:raise ValueError('Probabilities do not sum to one')
    if p[a['choice']]+1e-6<max(p.values()):raise ValueError('Choice does not match distribution')
    return a

def parse(raw,cfg):
    if not isinstance(raw.get('model'),str):raise ValueError('Missing model version')
    if raw['model']!=cfg['jev']['model']:raise ValueError('Unexpected model version')
    entry=validate_answer(raw,'entry_fit',{'ALLOW','BLOCK','UNKNOWN'})
    closing=validate_answer(raw,'exit_action',{'CLOSE','HOLD','UNKNOWN'})
    def passes(a,choice):
        return a['choice']==choice and a['confidence']>=cfg['jev']['min_confidence'] and a['probabilities'][choice]>=cfg['jev']['minimum_choice_probability']
    return {'allow_entry':passes(entry,'ALLOW'),'close_position':passes(closing,'CLOSE'),'model':raw['model'],'entry':entry,'exit':closing,'status':'ok'}

class Jev:
    def __init__(self,cfg,cache='runtime/jev-cache',max_calls=2000):
        self.cfg=cfg;self.cache=Path(cache);self.cache.mkdir(parents=True,exist_ok=True)
        self.calls=0;self.max_calls=max_calls
        self.key=os.environ.get('TYPESAFE_API_KEY')
        if not self.key:raise ValueError('TYPESAFE_API_KEY is required; set it locally, never paste it in chat.')
    def evaluate(self,snapshot):
        payload=make_payload(snapshot,self.cfg)
        body=json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()
        digest=hashlib.sha256(body).hexdigest();path=self.cache/(digest+'.json')
        if path.exists():return parse(json.loads(path.read_text())['response'],self.cfg)
        if self.calls>=self.max_calls:raise CallBudgetExceeded('Jev call budget exhausted; comparison aborted, not a completed trial.')
        self.calls+=1
        req=urllib.request.Request(ENDPOINT,data=body,headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'},method='POST')
        try:
            # Deliberately no automatic retry: avoid bursts/costs. Next candle can retry.
            with urllib.request.urlopen(req,timeout=15) as response: raw=json.load(response)
            result=parse(raw,self.cfg)
            path.write_text(json.dumps({'request':payload,'response':raw},ensure_ascii=False),encoding='utf-8')
            return result
        except Exception as exc:
            # Failed decisions are not cached as valid evaluations. Preserve fixed stops.
            with (self.cache/'errors.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps({'request_hash':digest,'error_type':type(exc).__name__})+'\n')
            return {'allow_entry':False,'close_position':False,'status':'error','error_type':type(exc).__name__}
