from pathlib import Path
import urllib.request, concurrent.futures, hashlib, json, time
ROOT=Path(__file__).resolve().parent
months=[f'2025-{m:02}' for m in range(8,13)]+[f'2026-{m:02}' for m in range(1,9)]
def fetch(job):
 month,kind=job
 suffix=f'/15m/BTCUSDT-15m-{month}.zip' if kind=='klines' else f'/BTCUSDT-fundingRate-{month}.zip'
 url=f'https://data.binance.vision/data/futures/um/monthly/{kind}/BTCUSDT'+suffix
 dest=ROOT/'data'/f'{kind}-{month}.zip'
 for attempt in range(3):
  try:
   if not dest.exists():
    with urllib.request.urlopen(url,timeout=35) as r: dest.write_bytes(r.read())
   b=dest.read_bytes()
   return {'url':url,'file':dest.name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
  except Exception as e:
   if attempt==2: return {'url':url,'error':str(e)}
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
 out=list(pool.map(fetch,[(m,k) for m in months for k in ['klines','fundingRate']]))
(ROOT/'data'/'manifest.json').write_text(json.dumps(out,indent=2))
print(json.dumps({'success':sum('error' not in x for x in out),'errors':[x for x in out if 'error' in x]},indent=2))

if any('error' in x for x in out):raise SystemExit('Incomplete download. Run again to retry missing archives.')
