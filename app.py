"""CLI: inspect market conditions or compare a Jev paper replay. Never sends orders."""
import argparse
import json
import urllib.request
from pathlib import Path
import pandas as pd
from jev import Jev, load_config, make_payload, hard_checks
from research.backtest import features, snapshot, load, simulate
ROOT=Path(__file__).resolve().parent

def latest(cfg):
    with urllib.request.urlopen('https://fapi.binance.com/fapi/v1/time',timeout=15) as r: now=json.load(r)['serverTime']
    with urllib.request.urlopen('https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=1000',timeout=15) as r: rows=json.load(r)
    rows=[x for x in rows if int(x[6])<now]
    if len(rows)<600:raise ValueError('Insufficient completed candles')
    if now-int(rows[-1][6])>1200000:raise ValueError('Stale market data; no decision')
    d=pd.DataFrame([[int(x[0])]+[float(y) for y in x[1:6]] for x in rows],columns=['open_time','open','high','low','close','volume'])
    if not (d.open_time.diff().dropna()==900000).all():raise ValueError('Market data gap')
    d['time']=pd.to_datetime(d.open_time,unit='ms',utc=True)
    return features(d,cfg)

def main():
    p=argparse.ArgumentParser(description='Binance + Jev 모의투자 연구 도구 (실주문 없음)')
    p.add_argument('command',choices=['inspect','replay'])
    p.add_argument('--strategy',choices=['trend','breakout','range'],default='trend')
    p.add_argument('--config',default=str(ROOT/'conditions.json'))
    p.add_argument('--jev',action='store_true',help='실제 Jev API 호출. API 비용 발생 가능.')
    p.add_argument('--start',default='2026-06-01');p.add_argument('--end',default='2026-09-01')
    p.add_argument('--max-calls',type=int,default=2000)
    args=p.parse_args();cfg=load_config(args.config)
    runtime=ROOT/'runtime';runtime.mkdir(exist_ok=True)
    if args.command=='inspect':
        d=latest(cfg);state=snapshot(d,len(d)-1,args.strategy,cfg)
        result={'state':state,'hard_checks_pass':hard_checks(state,cfg['extra_entry_checks']),'jev_called':False}
        if args.jev:
            result['jev']=Jev(cfg,cache=runtime/'jev-cache',max_calls=args.max_calls).evaluate(state);result['jev_called']=True
        else:result['request_preview']=make_payload(state,cfg)
        (runtime/'latest-decision.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2))
    else:
        d=load(cfg)
        start=pd.Timestamp(args.start,tz='UTC');end=pd.Timestamp(args.end,tz='UTC')
        if start>=end or start<d.time.min()+pd.Timedelta(days=7) or end>d.time.max()+pd.Timedelta(minutes=15):raise ValueError('Invalid range or insufficient warmup/data')
        baseline,_,_=simulate(d,args.strategy,args.start,args.end,cfg=cfg)
        report={'baseline':baseline,'jev':None,'conditions':cfg}
        if args.jev:
            gate=Jev(cfg,cache=runtime/'jev-cache',max_calls=args.max_calls)
            ai,trades,curve=simulate(d,args.strategy,args.start,args.end,cfg=cfg,gate=gate)
            report.update({'jev':ai,'jev_calls':gate.calls,'trades':trades,'equity':curve})
        path=runtime/'comparison.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k not in ['trades','equity','conditions']},ensure_ascii=False,indent=2))
        print('Saved:',path)
if __name__=='__main__':main()
