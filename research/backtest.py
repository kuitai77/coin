"""Research backtest only. No API keys, Jev calls or live-order functions.
Python 3.10+, pandas, numpy. Run download.py then backtest.py.
"""
from pathlib import Path
import zipfile, json, math
import pandas as pd
import numpy as np
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jev import load_config, hard_checks, DESCRIPTIONS
ROOT=Path(__file__).resolve().parent
CONFIG_PATH=Path(__file__).resolve().parents[1]/"conditions.json"
NAMES={'trend':'추세 눌림목','breakout':'거래량 돌파','range':'횡보장 반등'}
def load(cfg=None):
 cfg=cfg or load_config(CONFIG_PATH)
 frames=[]; funding=[]
 expected=[f'2025-{m:02}' for m in range(8,13)]+[f'2026-{m:02}' for m in range(1,9)]
 for month in expected:
  for kind in ['klines','fundingRate']:
   if not (ROOT/'data'/f'{kind}-{month}.zip').exists():raise ValueError('Missing archive: '+kind+'-'+month+'; run download.py')
 for p in sorted((ROOT/'data').glob('*.zip')):
  with zipfile.ZipFile(p) as z:
   with z.open(z.namelist()[0]) as f: a=pd.read_csv(f)
  if p.name.startswith('klines'):
   if not {'open_time','open','high','low','close','volume'}.issubset(a.columns): raise ValueError(f'Unknown columns {p}: {a.columns}')
   frames.append(a[['open_time','open','high','low','close','volume']])
  else:
   if not {'calc_time','last_funding_rate'}.issubset(a.columns): raise ValueError(f'Unknown funding columns {p}: {a.columns}')
   funding.append(a[['calc_time','last_funding_rate']])
 d=pd.concat(frames).sort_values('open_time').reset_index(drop=True)
 if d.open_time.duplicated().any() or not (d.open_time.diff().dropna()==900000).all(): raise ValueError('Duplicate or missing 15-minute candles')
 if not ((d.high>=d[['open','close','low']].max(axis=1)) & (d.low<=d[['open','close','high']].min(axis=1))).all(): raise ValueError('Invalid OHLC')
 d['time']=pd.to_datetime(d.open_time,unit='ms',utc=True)
 f=pd.concat(funding).sort_values('calc_time')
 if f.calc_time.duplicated().any(): raise ValueError('Duplicate funding')
 if not ((f.calc_time//900000).diff().dropna()==32).all(): raise ValueError('Funding interval gap; inspect before proceeding')
 if f.calc_time.min()//900000>d.open_time.min()//900000 or f.calc_time.max()<d.open_time.max()-28800000: raise ValueError('Funding coverage incomplete')
 # Funding timestamps are assigned to containing bar. Open price approximates mark price.
 fr={int(t//900000*900000):float(v) for t,v in zip(f.calc_time,f.last_funding_rate)}
 d['funding']=d.open_time.map(fr).fillna(0.)
 return features(d,cfg)

def features(d,cfg):
 d=d.copy();v=cfg['indicators']
 c=d.close
 for label,key in [(20,'pullback_ema'),(50,'trend_ema'),(200,'slow_ema')]: d[f'ema{label}']=c.ewm(span=v[key],adjust=False).mean()
 tr=pd.concat([d.high-d.low,(d.high-c.shift()).abs(),(d.low-c.shift()).abs()],axis=1).max(axis=1)
 d['atr']=tr.ewm(alpha=1/v['atr_period'],adjust=False).mean()
 delta=c.diff(); gain=delta.clip(lower=0).ewm(alpha=1/v['rsi_period'],adjust=False).mean(); loss=(-delta.clip(upper=0)).ewm(alpha=1/v['rsi_period'],adjust=False).mean()
 d['rsi']=100-100/(1+gain/loss.replace(0,np.nan))
 avg=c.rolling(v['bollinger_bars']).mean(); sd=c.rolling(v['bollinger_bars']).std(ddof=0)
 d['lower']=avg-v['bollinger_std']*sd;d['upper']=avg+v['bollinger_std']*sd
 trendlong=(d.ema50>d.ema200)&(c>d.ema200)&(c>d.ema20)&(c.shift()<=d.ema20.shift())
 trendshort=(d.ema50<d.ema200)&(c<d.ema200)&(c<d.ema20)&(c.shift()>=d.ema20.shift())
 vol=d.volume>d.volume.shift().rolling(v['volume_bars']).mean()*v['volume_multiplier']
 bl=(c>d.high.shift().rolling(v['breakout_bars']).max())&vol&(c>d.ema200)
 bs=(c<d.low.shift().rolling(v['breakout_bars']).min())&vol&(c<d.ema200)
 flat=(d.ema50-d.ema200).abs()/c<v['range_ema_distance']
 rl=flat&(c.shift()<d.lower.shift())&(c>=d.lower)&(d.rsi.shift()<v['range_rsi_long'])
 rs=flat&(c.shift()>d.upper.shift())&(c<=d.upper)&(d.rsi.shift()>v['range_rsi_short'])
 for name,long,short in [('trend',trendlong,trendshort),('breakout',bl,bs),('range',rl,rs)]:d[name]=np.select([long,short],[1,-1],default=0)
 return d

def snapshot(d,i,name,cfg,pos=None):
 row=d.iloc[i]
 keys=['close','ema20','ema50','ema200','atr','rsi','lower','upper','volume']
 indicators={k:float(row[k]) for k in keys}
 indicators['atr_pct']=float(row.atr/row.close)
 indicators['volume_ratio']=float(row.volume/d.volume.iloc[max(0,i-cfg['indicators']['volume_bars']):i].mean())
 indicators={k:(v if np.isfinite(v) else None) for k,v in indicators.items()}
 candles=[]
 for _,r in d.iloc[max(0,i-19):i+1].iterrows():
  candles.append({'open_time':str(r.time),**{k:float(r[k]) for k in ['open','high','low','close','volume']}})
 position=None if pos is None else {k:pos[k] for k in ['time','side','entry','stop','target']}
 return {'symbol':cfg['symbol'],'interval':cfg['interval'],'as_of_closed_bar':str(row.time+pd.Timedelta(minutes=15)),
         'strategy':name,'strategy_description':DESCRIPTIONS[name],'indicator_parameters':cfg['indicators'],
         'proposed_side':int(row[name]) if position is None else 0,'position':position,
         'indicators':indicators,'closed_candles':candles,'numeric_extra_checks':cfg['extra_entry_checks'],
         'context':'Research/paper only. No news or order book is supplied. Use only this snapshot.'}

def simulate(d,name,start,end,fee=None,slip=None,cfg=None,gate=None):
 cfg=cfg or load_config(CONFIG_PATH)
 fee=cfg['fee_per_side'] if fee is None else fee
 slip=cfg['slippage_per_side'] if slip is None else slip
 INITIAL=cfg['initial_equity']
 # Signals use completed candle i-1; entry occurs at open i with adverse slippage.
 idx=np.flatnonzero((d.time>=pd.Timestamp(start,tz='UTC'))&(d.time<pd.Timestamp(end,tz='UTC')))
 ai_errors=0;cash=INITIAL;peak=INITIAL;pos=None;cool=-1;day=None;daybase=INITIAL;dayhalt=False;kill=False
 trades=[];curve=[];fundtotal=0.;fees=0.
 arr=d.to_dict('list')
 def close(raw,i,why):
  nonlocal cash,pos,cool,fees
  p=pos;px=raw*(1-p['side']*slip);feeout=p['q']*px*fee
  cash+=p['side']*p['q']*(px-p['entry'])-feeout;fees+=feeout
  trades.append({'entry_time':p['time'],'exit_time':str(arr['time'][i]),'side':'LONG' if p['side']==1 else 'SHORT','entry':p['entry'],'exit':px,'quantity':p['q'],'pnl':cash-p['before'],'funding_pnl':p['funding'],'reason':why})
  pos=None;cool=i+cfg['cooldown_bars']
 for i in idx:
  o,h,l,c=[float(arr[k][i]) for k in ['open','high','low','close']]
  today=str(arr['time'][i].date())
  if today!=day:
   day=today;daybase=cash+(pos['side']*pos['q']*(o-pos['entry']) if pos else 0);dayhalt=False
  if pos:
   funding=-pos['side']*pos['q']*o*arr['funding'][i]
   cash+=funding;fundtotal+=funding;pos['funding']+=funding
   s=pos['side'];stop=pos['stop'];target=pos['target']
   # Gap fill at open. When both levels touched inside one bar, stop assumed first.
   if s*(o-stop)<=0:close(o,i,'gap_stop')
   elif s*(o-target)>=0:close(o,i,'gap_target')
   elif i-pos['i']>=cfg['max_holding_bars']:close(o,i,'time_limit')
  eqopen=cash+(pos['side']*pos['q']*(o-pos['entry']) if pos else 0)
  if eqopen<=daybase*(1-cfg['daily_loss_limit']):dayhalt=True
  if eqopen<=peak*(1-cfg['max_drawdown_limit']):kill=True
  if (dayhalt or kill) and pos:close(o,i,'risk_limit')
  decision=None
  if gate and not kill and not dayhalt and (pos or (i>cool and i!=idx[-1] and int(arr[name][i-1]))):
   decision=gate.evaluate(snapshot(d,i-1,name,cfg,pos))
   ai_errors+=int(decision['status']=='error')
   if pos and decision['close_position']:close(o,i,'jev_exit')
  if pos is None and not dayhalt and not kill and i>cool and i>0 and i!=idx[-1]:
   s=int(arr[name][i-1]);atr=float(arr['atr'][i-1])
   if s and np.isfinite(atr) and atr>0 and hard_checks(snapshot(d,i-1,name,cfg,None),cfg['extra_entry_checks']) and (not gate or (decision and decision['allow_entry'])):
    entry=o*(1+s*slip);dist=cfg['stop_atr']*atr
    # 0.5% budget includes approximate round-trip fees and slippage; gaps may exceed it.
    q=min(cash*cfg['risk_per_trade']/(dist+entry*2*(fee+slip)),cash*cfg['max_notional_equity_ratio']/entry)
    q=math.floor(q/cfg['quantity_step'])*cfg['quantity_step']
    if q*entry>=cfg['minimum_notional']:
     before=cash;entryfee=q*entry*fee;cash-=entryfee;fees+=entryfee
     pos={'i':i,'time':str(arr['time'][i]),'side':s,'q':q,'entry':entry,'stop':entry-s*dist,'target':entry+s*atr*cfg['target_atr'][name],'before':before,'funding':0.}
  if pos:
   s=pos['side'];stop=pos['stop'];target=pos['target']
   hitstop=l<=stop if s==1 else h>=stop
   hittarget=h>=target if s==1 else l<=target
   if hitstop:close(stop,i,'stop')
   elif hittarget:close(target,i,'target')
  eq=cash+(pos['side']*pos['q']*(c-pos['entry']) if pos else 0)
  peak=max(peak,eq)
  if eq<=daybase*(1-cfg['daily_loss_limit']):dayhalt=True
  if eq<=peak*(1-cfg['max_drawdown_limit']):kill=True
  if pos and (dayhalt or kill or i==idx[-1]):
   close(c,i,'risk_limit' if dayhalt or kill else 'period_end');eq=cash
  curve.append({'time':str(arr['time'][i]),'equity':eq})
 pnls=np.array([t['pnl'] for t in trades]);eqs=np.array([INITIAL]+[x['equity'] for x in curve]);dd=1-eqs/np.maximum.accumulate(eqs)
 wins=pnls[pnls>0].sum();loss=-pnls[pnls<0].sum()
 result={'jev_enabled':bool(gate),'jev_errors':ai_errors,'strategy':name,'start':start,'end_exclusive':end,'return_pct':(cash/INITIAL-1)*100,'final_equity':cash,'max_drawdown_pct':float(dd.max()*100),'trades':len(trades),'win_rate_pct':float((pnls>0).mean()*100) if len(pnls) else 0,'profit_factor':float(wins/loss) if loss else None,'fees':fees,'funding_pnl':fundtotal,'last_exit_time':trades[-1]['exit_time'] if trades else None,'permanent_halt':kill,'fee_per_side':fee,'slippage_per_side':slip}
 assert abs(cash-INITIAL-pnls.sum())<1e-6,'PnL reconciliation failed'
 assert all(t['quantity']>0 for t in trades)
 return result,trades,curve

def main():
 cfg=load_config(CONFIG_PATH);d=load(cfg);out=[]
 periods={'full':('2025-09-01','2026-09-01'),'reference':('2025-09-01','2026-06-01'),'evaluation':('2026-06-01','2026-09-01')}
 for period,(start,end) in periods.items():
  for name in NAMES:
   r,t,c=simulate(d,name,start,end);r['period']=period;out.append(r)
   (ROOT/f'{period}_{name}.json').write_text(json.dumps({'summary':r,'trades':t,'equity':c},ensure_ascii=False))
 for name in NAMES:
  r,t,c=simulate(d,name,'2026-06-01','2026-09-01',fee=.0005,slip=.0005);r['period']='evaluation_stress';out.append(r)
 (ROOT/'results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
 print(json.dumps(out,ensure_ascii=False,indent=2))
 print('DATA',len(d),str(d.time.min()),str(d.time.max()))
if __name__=='__main__':main()
