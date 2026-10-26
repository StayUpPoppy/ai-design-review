"""Isolated PostgreSQL database: full legacy/new migration and row-lock semantics.

Run in the API image with scripts mounted read-only. Never alters the service DB.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_multi_spec import fixture, OWNER
from ai_design_review.multi_spec import parse_multi_spec, source_review
from ai_design_review.multi_spec_store import create_children, describe
from ai_design_review.review_persistence import ReviewPersistence


def main():
    original = os.environ['DATABASE_URL']; url = make_url(original)
    assert url.drivername.startswith('postgresql'), 'PostgreSQL test only'
    name = 'multi_spec_qa_'+uuid.uuid4().hex[:12]
    admin = create_engine(url.set(database='postgres'),isolation_level='AUTOCOMMIT')
    repo = None
    with admin.connect() as conn: conn.execute(text(f'CREATE DATABASE {name}'))
    try:
        os.environ['DATABASE_URL'] = url.set(database=name).render_as_string(hide_password=False)
        cfg = Config('/app/alembic.ini'); cfg.set_main_option('script_location','/app/migrations')
        command.upgrade(cfg,'20260911_01')
        engine = create_engine(os.environ['DATABASE_URL'])
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO drawing_reviews (job_id,revision,review_snapshot,event_sequence,created_at,updated_at) VALUES ('legacy',1,'{}',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        command.upgrade(cfg,'head')
        with engine.connect() as conn:
            assert tuple(conn.execute(text("SELECT record_kind,parent_review_id,variant_id FROM drawing_reviews WHERE job_id='legacy'")).one()) == ('single',None,None)
        engine.dispose()
        repo=ReviewPersistence(os.environ['DATABASE_URL'])
        payload=fixture(); root=source_review(payload,parse_multi_spec(payload)); repo.create_review('source',root,owner=OWNER)
        ids=[v['variant_id'] for v in root['multi_spec']['variants']]
        body={'variant_ids':ids[:2],'expected_source_revision':1,'idempotency_key':'parallel'}
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(4) as pool:
            values=list(pool.map(lambda _:create_children(repo,'source',OWNER['user_id'],body,OWNER,Path(folder)),range(4)))
            assert all(v['reviews'][0]['job_id']==values[0]['reviews'][0]['job_id'] for v in values)
            assert describe(repo,'source',OWNER['user_id'])['created_count']==2
            # A failure halfway through the next batch rolls all inserts back.
            from unittest.mock import patch
            from ai_design_review import multi_spec_store
            real=multi_spec_store.child_review
            def fail(*a): raise RuntimeError('offline rollback injection')
            before=describe(repo,'source',OWNER['user_id'])
            with patch.object(multi_spec_store,'child_review',side_effect=fail):
                try: create_children(repo,'source',OWNER['user_id'],{'variant_ids':[ids[2]],'expected_source_revision':before['source_revision'],'idempotency_key':'rollback'},OWNER,Path(folder))
                except RuntimeError: pass
                else: raise AssertionError('Expected rollback')
            assert describe(repo,'source',OWNER['user_id'])==before
        repo._engine.dispose();repo=None
        command.downgrade(cfg,'20260911_01')
        print('PASS isolated PostgreSQL full migration, old record preservation, row locks, concurrent receipts, transaction rollback and downgrade')
    finally:
        if repo: repo._engine.dispose()
        os.environ['DATABASE_URL']=original
        assert name.startswith('multi_spec_qa_') and len(name)==26
        with admin.connect() as conn: conn.execute(text(f'DROP DATABASE {name} WITH (FORCE)'))
        admin.dispose()


if __name__=='__main__': main()
