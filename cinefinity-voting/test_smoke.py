import json
from app import app

def run_tests():
    c = app.test_client()

    # 1. Root page
    r = c.get('/')
    print('GET / status:', r.status_code)
    assert r.status_code == 200, 'Root page failed'
    html = r.data.decode()
    assert 'conn-banner' in html, 'conn-banner missing'
    assert 'voter-status-bar' in html, 'voter-status-bar missing'
    assert 'proj-cats' in html, 'proj-cats missing'
    print('HTML structure: OK')

    # 2. Results API now has photo_url + leader
    r2 = c.get('/api/results')
    print('GET /api/results status:', r2.status_code)
    assert r2.status_code == 200
    d = json.loads(r2.data)
    print('  ballots:', d['ballots'])
    for cat in d['categories']:
        for item in cat['items']:
            assert 'photo_url' in item, f'photo_url missing in {item}'
        print(f"  cat={cat['key']}, items={len(cat['items'])}, leader={cat['leader']}")
    print('Results API: OK')

    # 3. Legacy redirects still work
    assert c.get('/vote').status_code == 302
    assert c.get('/admin').status_code == 302
    assert c.get('/results').status_code == 302
    assert c.get('/confirmation').status_code == 302
    print('Redirects: OK')

    # 4. Bad admin login returns 401
    r3 = c.post('/api/admin/login', json={'password': 'wrong'})
    print('Bad login status:', r3.status_code)
    assert r3.status_code == 401

    print('\nALL CHECKS PASSED!')

if __name__ == '__main__':
    run_tests()
