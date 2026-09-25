import json
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool
from leagues import builder_runs, settlement_incident_repair as repair
from leagues.picks_db import PublishedSlip

def _leg(stored, proposed, evidence=True):
    return {"stored_outcome":stored,"proposed_outcome":proposed,"stored_evidence":None,"score_evidence":({"provider":"espn","provider_event_id":"e","home_score":2,"away_score":0,"match_status":"FINAL"} if evidence else None),"unresolved_reason":None if evidence else "FINAL_SCORE_UNVERIFIED"}
def _reports(pid, fp):
    pub={"score_source":"espn","unresolved_legs":[],"likely_historical_false_voids":[],"slips":[{"slip_id":pid,"date":"2026-09-15","category":"banker","stored_status":"void","proposed_status":"won","legs":[_leg("void","won")]}]}
    build={"score_source":"espn","unresolved_builder_legs":[],"final_status_changes":[],"predictions":[{"selection_fingerprint":fp,"created_at":"2026-09-16T00:00:00+00:00","target_odds":2.0,"horizon":"week","stored_final_status":"void","proposed_final_status":"won","legs":[_leg("void","won")]}]}
    return pub,build
@pytest.fixture
def db(monkeypatch):
 e=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False}); PublishedSlip.__table__.create(e); builder_runs.builder_predictions.create(e)
 monkeypatch.setattr('database.engine',e); monkeypatch.setattr(builder_runs,'engine',e)
 with e.begin() as c:
  p=PublishedSlip(date='2026-09-15',category='banker',picks=json.dumps([{'status':'void','odds':1.5}]),total_odds=1.5,status='void'); c.execute(PublishedSlip.__table__.insert().values(date=p.date,category=p.category,picks=p.picks,total_odds=1.5,status='void'))
  c.execute(builder_runs.builder_predictions.insert().values(selection_fingerprint='b',created_at=datetime(2026,9,16,tzinfo=timezone.utc),target_odds=2.0,horizon='week',generated_odds=1.5,leg_count=1,picks=json.dumps([{'status':'void','odds':1.5}]),final_status='void'))
 with e.connect() as c: pid=c.execute(select(PublishedSlip.id)).scalar_one()
 return e,pid
def test_combined_dry_run_zero_writes(monkeypatch,db):
 e,pid=db;monkeypatch.setattr(repair,'_reports',lambda:_reports(pid,'b'));writes=[]
 event.listen(e,'before_cursor_execute',lambda *a: writes.append(a[2]) if a[2].lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) else None)
 assert repair.run()['dry_run'];assert writes==[]
def test_combined_apply_updates_both_and_backup(monkeypatch,db,tmp_path):
 e,pid=db;monkeypatch.setattr(repair,'_reports',lambda:_reports(pid,'b'))
 out=repair.run(apply=True,confirmation=repair.CONFIRM_TOKEN,backup_dir=tmp_path);assert out['transaction_status']=='committed';assert 'published_slips' in json.loads(open(out['backup_path']).read())
 with e.connect() as c:
  assert c.execute(select(PublishedSlip.status)).scalar_one()=='won'; r=c.execute(select(builder_runs.builder_predictions)).mappings().one();assert r['final_status']=='won' and r['actual_settled_return']==1.5 and r['target_reached'] is False
def test_precondition_mismatch_aborts_both(monkeypatch,db,tmp_path):
 e,pid=db;monkeypatch.setattr(repair,'_reports',lambda:_reports(pid,'b'))
 with e.begin() as c:c.execute(PublishedSlip.__table__.update().where(PublishedSlip.id==pid).values(status='lost'))
 with pytest.raises(repair.RepairPreconditionError):repair.run(apply=True,confirmation=repair.CONFIRM_TOKEN,backup_dir=tmp_path)
 with e.connect() as c:assert c.execute(select(builder_runs.builder_predictions.c.final_status)).scalar_one()=='void'
def test_builder_failure_rolls_back_prior_published_update(monkeypatch,db,tmp_path):
 e,pid=db;monkeypatch.setattr(repair,'_reports',lambda:_reports(pid,'b'));monkeypatch.setattr(repair,'_builder_values',lambda *a: (_ for _ in ()).throw(RuntimeError('fail')))
 with pytest.raises(RuntimeError,match='fail'):repair.run(apply=True,confirmation=repair.CONFIRM_TOKEN,backup_dir=tmp_path)
 with e.connect() as c:
  assert c.execute(select(PublishedSlip.status)).scalar_one()=='void'
  assert c.execute(select(builder_runs.builder_predictions.c.final_status)).scalar_one()=='void'
