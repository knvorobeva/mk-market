import json
import urllib.request
import urllib.error

BASE = 'http://127.0.0.1:8000'


def req(path, method='GET', data=None, token=None):
    body = json.dumps(data).encode() if data is not None else None
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode() or '{}'
            return response.getcode(), json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode() or '{}'
        return exc.code, json.loads(raw)


master_email = 'master_seed@mkmarket.local'
user_email = 'user_seed@mkmarket.local'
for email, role, name in [
    (master_email, 'master', 'Мастер Сид'),
    (user_email, 'user', 'Клиент Сид'),
]:
    code, _ = req('/api/auth/register', 'POST', {
        'email': email,
        'password': '123456',
        'password_repeat': '123456',
        'role': role,
        'name': name,
    })
    print('register', email, code)

code, login_master = req('/api/auth/login', 'POST', {'email': master_email, 'password': '123456'})
print('login_master', code)
mtoken = login_master.get('token')

code, workshops = req('/api/admin/workshops', 'GET', None, mtoken)
if not isinstance(workshops, list):
    print('admin_workshops_error', code, workshops)
    raise SystemExit(1)

if workshops:
    wid = workshops[0]['id']
    print('workshop_exists', wid)
else:
    code, created = req('/api/admin/workshops', 'POST', {
        'title': 'Бенто-торт для начинающих',
        'description': 'Практика декора и сборки бенто-торта',
        'location': 'Москва, Тверская 10',
        'price': 3500,
        'duration_min': 120,
        'capacity': 6,
    }, mtoken)
    wid = created.get('id')
    print('create_workshop', code, wid)

code, slots = req(f'/api/admin/workshops/{wid}/slots', 'GET', None, mtoken)
if not isinstance(slots, list):
    print('admin_slots_error', code, slots)
    raise SystemExit(1)

if slots:
    print('slot_exists', slots[0]['id'])
else:
    code, created_slot = req(f'/api/admin/workshops/{wid}/slots', 'POST', {
        'start_at': '2026-03-20T16:00:00+03:00',
        'end_at': '2026-03-20T18:00:00+03:00',
        'total_seats': 6,
    }, mtoken)
    print('create_slot', code, created_slot.get('id'))

print('seed_done')
