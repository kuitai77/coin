import copy
import unittest
from pathlib import Path
import pandas as pd
from jev import load_config, parse, hard_checks, make_payload
from research.backtest import features, snapshot, simulate
ROOT=Path(__file__).resolve().parents[1]
class CoreTests(unittest.TestCase):
 def setUp(self):self.cfg=load_config(ROOT/'conditions.json')
 def data(self):
  t=pd.date_range('2026-01-01',periods=270,freq='15min',tz='UTC')
  d=pd.DataFrame({'time':t,'open_time':t.astype('int64')//1000000,'open':100.,'high':101.,'low':99.,'close':100.,'volume':10.,'funding':0.})
  d=features(d,self.cfg);d['trend']=0;d.loc[260,'trend']=1
  return d
 def period(self,d):return str(d.time.iloc[261].tz_localize(None)),str((d.time.iloc[-1]+pd.Timedelta(minutes=15)).tz_localize(None))
 def response(self):
  def a(choice,p):return {'type':'choice','choice':choice,'confidence':.9,'probabilities':p}
  return {'model':'jev-1.13.0','answers':{'entry_fit':a('ALLOW',{'ALLOW':.95,'BLOCK':.03,'UNKNOWN':.02}),'exit_action':a('HOLD',{'CLOSE':.03,'HOLD':.95,'UNKNOWN':.02})}}
 def test_jev_allow(self):self.assertTrue(parse(self.response(),self.cfg)['allow_entry'])
 def test_low_confidence_blocks(self):
  r=self.response();r['answers']['entry_fit']['confidence']=.1
  self.assertFalse(parse(r,self.cfg)['allow_entry'])
 def test_invalid_probability_blocks(self):
  r=self.response();r['answers']['entry_fit']['probabilities']['ALLOW']=float('nan')
  with self.assertRaises(ValueError):parse(r,self.cfg)
 def test_unknown_action_blocks(self):
  r=self.response();r['answers']['entry_fit']['choice']='BUY_ALL'
  with self.assertRaises(ValueError):parse(r,self.cfg)
 def test_numeric_rules_cannot_be_overridden(self):
  state=snapshot(self.data(),260,'trend',self.cfg)
  self.assertFalse(hard_checks(state,[{'field':'close','op':'lt','value':99}]))
  with self.assertRaises(ValueError):hard_checks(state,[{'field':'future_price','op':'gt','value':99}])
 def test_future_candles_do_not_change_features(self):
  d=self.data();a=features(d,self.cfg);d.loc[261:,'close']=150;b=features(d,self.cfg)
  for k in ['atr','ema20','ema50','ema200','trend','breakout','range']:pd.testing.assert_series_equal(a[k].iloc[:261],b[k].iloc[:261])
 def test_entry_is_next_bar(self):
  d=self.data();r,t,c=simulate(d,'trend',*self.period(d),cfg=self.cfg)
  self.assertEqual(t[0]['entry_time'],str(d.time.iloc[261]))
  self.assertAlmostEqual(sum(x['pnl'] for x in t),r['final_equity']-10000)
 def test_both_levels_hit_assumes_stop(self):
  d=self.data();d.loc[261,['high','low']]=[110,90]
  r,t,c=simulate(d,'trend',*self.period(d),cfg=self.cfg)
  self.assertEqual(t[0]['reason'],'stop');self.assertLess(t[0]['pnl'],0)
 def test_jev_block_means_no_entry(self):
  class Gate:
   def evaluate(self,state):return {'allow_entry':False,'close_position':False,'status':'ok'}
  d=self.data();r,t,c=simulate(d,'trend',*self.period(d),cfg=self.cfg,gate=Gate())
  self.assertEqual(r['trades'],0)
 def test_ai_failure_preserves_stop(self):
  class Gate:
   def __init__(self):self.calls=0
   def evaluate(self,state):
    self.calls+=1
    return {'allow_entry':self.calls==1,'close_position':False,'status':'ok' if self.calls==1 else 'error'}
  d=self.data();d.loc[262,'low']=90
  r,t,c=simulate(d,'trend',*self.period(d),cfg=self.cfg,gate=Gate())
  self.assertEqual(t[0]['reason'],'stop');self.assertGreater(r['jev_errors'],0)
 def test_funding_is_accounted_for(self):
  d=self.data();d.loc[262,'funding']=.0001
  r,t,c=simulate(d,'trend',*self.period(d),cfg=self.cfg)
  self.assertLess(r['funding_pnl'],0);self.assertAlmostEqual(t[0]['funding_pnl'],r['funding_pnl'])
 def test_custom_text_is_sent(self):
  cfg=copy.deepcopy(self.cfg);cfg['jev']['entry_conditions']=['사용자 조건 예시']
  req=make_payload(snapshot(self.data(),260,'trend',cfg),cfg)
  self.assertEqual(req['questions']['entry_fit']['instructions']['entry_conditions'],['사용자 조건 예시'])
if __name__=='__main__':unittest.main()
