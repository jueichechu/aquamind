"""Offline HTTP smoke for the built container; synthetic inputs, no paid calls.

Run via docker exec while the container has --network none, --memory 512m and
--memory-swap 512m. Runtime placeholder configuration must match the CI example.
"""
import concurrent.futures
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

from aquamind_ml.evidence import BillEvidenceContext
from aquamind_ml.meter_import import METER_BODY_LIMIT

WEB='http://127.0.0.1:10000'
KEY='capacity-placeholder-relay-key-123456789'
checks={}
started=time.monotonic()

def request(path,body=None,token=None,base=WEB,relay=False):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    if relay:headers['X-AquaMind-Relay-Key']=KEY
    encoded=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request(base+path,data=encoded,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=20) as response:return response.status,response.read()
    except urllib.error.HTTPError as error:return error.code,error.read()

def get_json(*args,**kwargs):
    status,raw=request(*args,**kwargs)
    return status,json.loads(raw)

while time.monotonic()-started<360:
    try:
        status,html=request('/')
        if status==200:break
    except (OSError,urllib.error.URLError):pass
    time.sleep(.5)
else:raise AssertionError('Website did not become ready')
checks['first_page_followed_by_ready_api']=get_json('/api/aquamind/v1/bills/readiness')==(200,{'status':'ready'})
checks['health_after_gated_startup']=get_json('/api/health')==(200,{'status':'ok'})
page_ready_seconds=round(time.monotonic()-started,3)
evidence_bill=BillEvidenceContext(evidence_id='bill_capacity',household_id='house_capacity',
    origin='synthetic',input_method='manual_entry',reviewed=True,timezone='America/Los_Angeles',
    bill={'period_start':'2026-03-08','period_end_exclusive':'2026-03-09',
          'usage':'0','usage_unit':'us_gallons'})
checks['evidence_contract_timezone_available']=evidence_bill.timezone=='America/Los_Angeles'
for path in ('/analyze','/compare','/demo','/meter'):
    checks['page'+path]=request(path)[0]==200
checks['health']=get_json('/api/health')==(200,{'status':'ok'})
checks['relay_allowlist']=request('/api/aquamind/ready')[0]==404
checks['raw_api_not_exposed']=request('/v1/sessions')[0]==404
checks['session_required']=request('/api/aquamind/v1/bills/normalize',{})[0]==401
status,session=get_json('/api/aquamind/v1/sessions',{})
checks['session_created']=status==201
token=session['session_token']
bill={'period_start':'2026-06-01','period_end_exclusive':'2026-07-01','usage':'8.5','usage_unit':'ccf'}
def normalize(index):
    status,result=get_json('/api/aquamind/v1/bills/normalize',bill,token)
    return status==200 and result['us_gallons_per_day']=='211.948052'
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    checks['eight_bill_calculations']=all(pool.map(normalize,range(8)))
checks['consent_required']=request('/api/aquamind/v1/bills/import',{'share_with_ai':False,'media_type':'image/png','data_base64':'AA=='},token)[0]==422
# Exercise the existing maximum body size without admitting any provider work.
checks['maximum_upload_body_consent_required']=request('/api/aquamind/v1/bills/import',
    {'share_with_ai':False,'media_type':'image/png','data_base64':'A'*(4*((4*1024*1024+2)//3))},token)[0]==422
checks['raw_inference_not_exposed']=request('/api/aquamind/v1/anomaly/predict',{})[0]==404
checks['no_goal_changed']=get_json('/api/aquamind/v1/goals/current',token=token)==(200,{'goal':None})
meter_csv='interval_start,volume\n'+''.join(
    f'{(datetime(2026,6,1,tzinfo=UTC)+timedelta(minutes=15*i)).isoformat()},15\n' for i in range(672))
meter={'csv_text':meter_csv,
    'volume_unit':'us_gallons','interval_minutes':15,'timezone':'UTC',
    'reading_type':'actual','consent_to_process':True}
checks['meter_consent_required']=request('/api/aquamind/v1/meters/import',
    meter|{'consent_to_process':False},token)[0]==422
status,imported=get_json('/api/aquamind/v1/meters/import',meter,token)
checks['meter_imported']=status==201 and imported['total_us_gallons']=='10080.000000' and imported['context']['reading_count']==672 and imported['context']['origin']=='user_provided'
checks['meter_selected_within_session']=get_json('/api/aquamind/v1/meters/current',token=token)==(200,imported)
checks['meter_body_bounded']=request('/api/aquamind/v1/meters/import',
    meter|{'csv_text':'x'*METER_BODY_LIMIT},token)[0]==413
checks['meter_raw_route_not_exposed']=request('/v1/meters/current',token=token)[0]==404
evidence={'text':'Explain this household water bill and selected meter coverage.',
    'bill':bill,'bill_timezone':'UTC','bill_input_method':'manual_entry','bill_reading_type':'unknown',
    'meter_evidence_id':imported['context']['evidence_id'],'bill_reviewed':True,
    'meter_reviewed':True,'same_household':True,'share_with_ai':False}
checks['evidence_sharing_required']=request('/api/aquamind/v1/agent/evidence',evidence,token)[0]==422
evidence['share_with_ai']=True
evidence['bill']=bill|{'period_start':'2024-06-01','period_end_exclusive':'2024-07-01'}
checks['evidence_period_rejected_without_provider']=request('/api/aquamind/v1/agent/evidence',evidence,token)[0]==422
# Audio checks remain invalid before ledger/provider work, inside the six-request window.
from aquamind_ml.voice import MAX_AUDIO_BASE64
checks['voice_consent_required_at_maximum_body']=request('/api/aquamind/v1/audio/transcribe',
    {'media_type':'audio/wav','data_base64':'A'*MAX_AUDIO_BASE64,'share_with_ai':False},token)[0]==422
import base64, struct
pcm=bytes(48000*2*31)
clip=(b'RIFF'+struct.pack('<I',36+len(pcm))+b'WAVEfmt '+struct.pack('<IHHIIHH',16,1,1,48000,96000,2,16)+
      b'data'+struct.pack('<I',len(pcm))+pcm)
checks['voice_overlong_rejected_before_provider']=request('/api/aquamind/v1/audio/transcribe',
    {'media_type':'audio/wav','data_base64':base64.b64encode(clip).decode(),'share_with_ai':True},token)[0]==422
req=urllib.request.Request(WEB+'/api/aquamind/v1/session',method='DELETE',headers={'Authorization':'Bearer '+token})
with urllib.request.urlopen(req,timeout=20) as response:checks['session_revoked']=response.status==204
checks['revoked_meter_unavailable']=request('/api/aquamind/v1/meters/current',token=token)[0]==401
cgroup=Path('/sys/fs/cgroup')
report={'passed':all(checks.values()),'checks':checks,'page_ready_seconds':page_ready_seconds,'memory_peak_bytes':int((cgroup/'memory.peak').read_text()),'memory_max_bytes':int((cgroup/'memory.max').read_text()),'cpu_max':(cgroup/'cpu.max').read_text().strip(),'paid_calls':0,'network':'none','limitations':['Bounded local Linux smoke, not a hosted cold-wake or load/latency guarantee.','No real provider call or visual browser acceptance.']}
print(json.dumps(report),flush=True)
if not report['passed']:raise SystemExit(1)
