import json
import os
from app import app
from utils.firebase import get_db

def run_integration_tests():
    c = app.test_client()
    db = get_db()
    
    admin_pw = os.environ.get("ADMIN_PASSWORD", "Admin@Cinefinity2026")
    print("Testing with admin credentials...")

    # 1. Admin Login
    res = c.post('/api/admin/login', json={'password': admin_pw})
    assert res.status_code == 200, f"Admin login failed: {res.data}"
    print("[OK] Admin login successful")

    # 2. Ensure each category has at least one active contestant
    res = c.get('/api/admin/data')
    assert res.status_code == 200
    data = json.loads(res.data)
    groups = data['groups']
    
    selections = {}
    for g in groups:
        cat_key = g['key']
        items = g['items']
        if not items:
            res = c.post('/api/admin/contestant/new', json={'category': cat_key})
            assert res.status_code == 200, f"Failed to add contestant for {cat_key}: {res.data}"
            cid = json.loads(res.data)['id']
            c.post(f'/api/admin/contestant/{cid}', data={
                'name': f'Candidate {cat_key}',
                'category': cat_key,
                'display_order': 1,
                'active': 'on'
            })
            selections[cat_key] = cid
        else:
            # Enable the first one if inactive
            cid = items[0]['id']
            c.post(f'/api/admin/contestant/{cid}', data={
                'name': items[0].get('name') or f'Candidate {cat_key}',
                'category': cat_key,
                'display_order': 1,
                'active': 'on'
            })
            selections[cat_key] = cid

    print(f"[OK] Valid ballot selections prepared for categories: {list(selections.keys())}")

    # 3. Test Starting Voting
    res = c.post('/api/admin/voting', json={'action': 'start'})
    assert res.status_code == 200
    assert json.loads(res.data)['status'] == 'active'
    print("[OK] Voting started (status='active' in Firebase)")

    # 4. Verify public client sees active status
    c_public = app.test_client()
    res = c_public.get('/api/results')
    assert res.status_code == 200
    assert json.loads(res.data)['status'] == 'active'
    print("[OK] Public clients immediately observe active voting")

    # 5. Admin votes as a voter using public ballot endpoint /vote/submit
    c.get('/') # sets voter_token cookie
    res = c.post('/vote/submit', json={'selections': selections})
    assert res.status_code == 200, f"Admin vote failed: {res.data}"
    assert json.loads(res.data)['ok'] is True
    print("[OK] Admin successfully submitted ballot as a normal voter")

    # 6. Verify duplicate vote protection for the admin
    res = c.post('/vote/submit', json={'selections': selections})
    assert res.status_code == 409
    print("[OK] Admin duplicate ballot correctly rejected (409 Already recorded)")

    # 7. Verify admin privileges were not altered by voting
    res = c.get('/api/admin/data')
    assert res.status_code == 200
    admin_data = json.loads(res.data)
    assert admin_data['ballots'] >= 1
    print(f"[OK] Admin access preserved; Ballots count = {admin_data['ballots']}")

    # 8. Another voter votes on their independent client
    c_public.get('/')
    res = c_public.post('/vote/submit', json={'selections': selections})
    assert res.status_code == 200
    print("[OK] Independent voter phone successfully submitted ballot")

    # 9. Stop voting
    res = c.post('/api/admin/voting', json={'action': 'stop'})
    assert res.status_code == 200
    assert json.loads(res.data)['status'] == 'closed'
    print("[OK] Voting stopped (status='closed')")

    # 10. Reset votes
    res = c.post('/api/admin/reset')
    assert res.status_code == 200
    res = c.get('/api/admin/data')
    assert json.loads(res.data)['ballots'] == 0
    print("[OK] All votes reset to 0 ballots")

    # 11. Admin Logout
    res = c.post('/api/admin/logout')
    assert res.status_code == 200
    res = c.get('/api/admin/data')
    assert res.status_code == 401
    print("[OK] Admin logout successful")

    print("\nALL ADMIN VOTING & INTEGRATION CHECKS PASSED! [SUCCESS]")

if __name__ == '__main__':
    run_integration_tests()
