"""HTTP save regression for server-owned local-verification metadata."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_solidworks_push_api import api, OWNER, ready_review
from ai_design_review.diameter_linkage import apply_diameter_linkage
from ai_design_review.review_loading import VERSION
from ai_design_review.review_persistence import ReviewPersistence
from fastapi.testclient import TestClient


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store = ReviewPersistence(f"sqlite+pysqlite:///{root / 'reviews.db'}")
        store.create_schema_for_testing()
        try:
            with patch.object(api, 'REVIEW_PERSISTENCE', store), patch.object(api, 'API_RUN_ROOT', root), \
                    patch.object(api, 'verify_review_roughness', return_value=False), \
                    TestClient(api.app, raise_server_exceptions=False) as client:
                for kind in ('single', 'variant', 'page', 'legacy'):
                    original = ready_review()
                    if kind != 'legacy':
                        original['local_verification'] = {'version': VERSION, 'completed_at': '2026-11-05T00:00:00Z'}
                    if kind in ('variant', 'page'):
                        original['record_kind'] = 'variant'
                        key = 'multi_spec_origin' if kind == 'variant' else 'page_origin'
                        original[key] = {'source_review_id': 'source', 'variant_id': 'v1', 'original_page': 4, 'local_page': 1}
                    store.create_review(kind, original, owner=OWNER, artifact_dir=str(root / kind))
                    edited = deepcopy(original)
                    for field, value in (('wire_diameter', 32), ('inner_diameter', 111)):
                        edited['spring_parameters'].setdefault(field, {'unit':'mm', 'need_human_review':True})['value'] = value
                    apply_diameter_linkage(edited, 'inner_diameter')
                    edited['local_verification'] = {'version': 'client-must-not-replace-this'}
                    edited['loading_metadata'] = {'review_revision': 9999}
                    edited['preview_pages'] = [{'width': 9999}]
                    response = client.patch(f'/api/reviews/{kind}', json={
                        'review': edited, 'expected_revision': 1,
                        'events': [{'event_type': 'parameter_value_updated', 'target_field': 'inner_diameter'}],
                    })
                    assert response.status_code == 200, (kind, response.status_code, response.text)
                    saved = store.get_review(kind, owner_user_id=OWNER['user_id'])
                    assert saved['revision'] == 2
                    current = saved['review']
                    assert current.get('local_verification') == original.get('local_verification')
                    assert 'loading_metadata' not in current and 'preview_pages' not in current
                    assert [current['spring_parameters'][f]['value'] for f in
                            ('wire_diameter', 'outer_diameter', 'inner_diameter', 'mean_diameter')] == [32, 175, 111, 143]
                    assert all(current['spring_parameters'][f]['need_human_review'] for f in
                               ('outer_diameter', 'inner_diameter', 'mean_diameter'))
                    # A failed stale save cannot overwrite the successfully saved values.
                    stale = client.patch(f'/api/reviews/{kind}', json={'review': edited, 'expected_revision': 1})
                    assert stale.status_code == 409, stale.text
                    assert store.get_review(kind, owner_user_id=OWNER['user_id'])['revision'] == 2
                    # The retained client draft can retry with the current revision.
                    retry = client.patch(f'/api/reviews/{kind}', json={'review': edited, 'expected_revision': 2})
                    assert retry.status_code == 200, retry.text
        finally:
            store.dispose()
    print('PASS HTTP autosave/retry for verified, legacy, variant and PDF-page reviews; diameter group, server metadata and revision conflict protection')


if __name__ == '__main__':
    main()
