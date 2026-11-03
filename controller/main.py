"""NCC controller. Run only on private VPN; never expose directly to public Internet."""
import os, json, uuid, socket, sqlite3, ssl, hmac, ipaddress, threading, time, urllib.request, urllib.error
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from cryptography.fernet import Fernet

try:
    from pyVmomi import vim as _vmomi_vim
except Exception:
    _vmomi_vim = None

DB = Path(os.environ.get('NCC_DB', 'ncc.sqlite3'))
KEY = os.environ.get('NCC_API_KEY', '')
FERNET_KEY = os.environ.get('NCC_ENCRYPTION_KEY', '')
if len(KEY) < 32 or not FERNET_KEY:
    raise RuntimeError('Set NCC_API_KEY (32+ chars) and NCC_ENCRYPTION_KEY (Fernet key)')
crypt = Fernet(FERNET_KEY.encode())
app = FastAPI(title='Network Control Center', docs_url=None, redoc_url=None)

VERSION = '2.0.0'

_VM_COMMAND_LOCKS = {}
_VM_COMMAND_LOCKS_GUARD = threading.Lock()

def _vm_command_lock(device_id, vm_id):
    key = f'{device_id}/{vm_id}'
    with _VM_COMMAND_LOCKS_GUARD:
        lock = _VM_COMMAND_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _VM_COMMAND_LOCKS[key] = lock
        return lock

def _wait_for_task(si, task, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = getattr(task, 'info', None)
        state = str(getattr(info, 'state', '') or '')
        if state == 'success':
            return True
        if state == 'error':
            err = getattr(info, 'error', None)
            msg = getattr(err, 'msg', 'VMware task failed') if err is not None else 'VMware task failed'
            return str(msg)
        time.sleep(1)
    return None

def now():
    return datetime.now(timezone.utc).isoformat()

def init_db():
    with sqlite3.connect(DB) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, host TEXT NOT NULL,
            port INTEGER NOT NULL, username BLOB, password BLOB, ca_file TEXT,
            cert_fingerprint TEXT, enabled INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT)''')
        cols = [r[1] for r in con.execute('PRAGMA table_info(devices)')]
        for col, ddl in [('cert_fingerprint','TEXT'),('enabled','INTEGER DEFAULT 1'),
                         ('created_at','TEXT'),('updated_at','TEXT'),('api_token','BLOB')]:
            if col not in cols:
                con.execute(f'ALTER TABLE devices ADD COLUMN {col} {ddl}')
        con.execute('''CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT DEFAULT CURRENT_TIMESTAMP,
            action TEXT, target TEXT, result TEXT, details TEXT, actor TEXT)''')
        audit_cols = [r[1] for r in con.execute('PRAGMA table_info(audit)')]
        for col, ddl in [('details','TEXT'),('actor','TEXT')]:
            if col not in audit_cols:
                con.execute(f'ALTER TABLE audit ADD COLUMN {col} {ddl}')

init_db()

class NewDevice(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=443, ge=1, le=65535)
    username: str = Field(default='', max_length=128)
    password: str = Field(default='', max_length=512)
    api_token: str = Field(default='', max_length=512)
    ca_file: str = ''
    cert_fingerprint: str = ''

class Command(BaseModel):
    action: str
    confirm: bool = False

def auth(x_api_key: str | None):
    if not x_api_key or not hmac.compare_digest(x_api_key, KEY):
        raise HTTPException(401, 'Authentication failed')

def validate_host(host: str):
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Allow DNS hostnames for flexible registration; backend connects only through configured management path.
        if not host or len(host) > 255 or ' ' in host:
            raise HTTPException(400, 'Invalid hostname')
        return
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        raise HTTPException(400, 'Loopback, link-local, multicast, or reserved addresses are not permitted')
    # IPv4/IPv6 must be private or, for IPv6, unique-local/global managed ranges are accepted only if private.
    if isinstance(ip, ipaddress.IPv4Address) and not ip.is_private:
        raise HTTPException(400, 'Only private VPN addresses are permitted')
    if isinstance(ip, ipaddress.IPv6Address) and not ip.is_private:
        raise HTTPException(400, 'Only private VPN addresses are permitted')

def enc(s): return crypt.encrypt(s.encode()) if s else b''
def dec(b): return crypt.decrypt(b).decode() if b else ''

def records():
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        return [dict(x) for x in db.execute('SELECT * FROM devices ORDER BY name')]

def get_device(device_id):
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('SELECT * FROM devices WHERE id=?', (device_id,)).fetchone()
    return dict(row) if row else None

def public(d):
    return {k: d[k] for k in ['id', 'name', 'kind', 'host', 'port', 'ca_file', 'cert_fingerprint', 'enabled']}

def reach(host, port):
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False

def ssl_context(ca_file=''):
    if ca_file and Path(ca_file).is_file():
        return ssl.create_default_context(cafile=ca_file)
    return ssl.create_default_context()

@contextmanager
def esxi(d):
    if d.get('kind') and d['kind'] != 'esxi':
        raise RuntimeError('Device is not an ESXi host')

    import hashlib
    from pyVim.connect import SmartConnect, Disconnect
    from pyVmomi import vim

    host = str(d['host']).strip().lower().rstrip('.')
    port = int(d['port'])

    pinned_hosts = {
        '172.16.1.230': (
            r'F:\NCC\certs\esxi01-current-pinned.crt',
            'e2839d7f980e3cf48770a32f24e685a'
            '4275636ab10098f40e43164c4de880ee3'
        ),
        'esxi01.almanarschool.net': (
            r'F:\NCC\certs\esxi01-current-pinned.crt',
            'e2839d7f980e3cf48770a32f24e685a'
            '4275636ab10098f40e43164c4de880ee3'
        ),
        '172.16.1.220': (
            r'F:\NCC\certs\esxi02-current-pinned.crt',
            '46bd0d1f56238d39231573e450e89da9'
            '8d2f5f8643da921645f266fcf7f862e8'
        )
    }

    extra = {}

    if host in pinned_hosts and port == 443:
        cert_path, expected_hash = pinned_hosts[host]
        cert_file = Path(cert_path)

        if not cert_file.is_file():
            raise RuntimeError('Pinned ESXi certificate missing')

        pem = cert_file.read_text(encoding='ascii')
        der = ssl.PEM_cert_to_DER_cert(pem)

        actual_hash = hashlib.sha256(der).hexdigest()

        if actual_hash != expected_hash:
            raise RuntimeError('ESXi certificate pin mismatch')

        ctx = ssl.create_default_context(cafile=str(cert_file))
        ctx.check_hostname = False
        ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN

        extra['serverPemCert'] = pem

    else:
        cafile = d.get('ca_file') or ''

        if not cafile or not Path(cafile).is_file():
            raise RuntimeError(
                'ESXi CA certificate file is not configured'
            )

        ctx = ssl.create_default_context(cafile=cafile)

    si = SmartConnect(
        host=host,
        user=dec(d['username']),
        pwd=dec(d['password']),
        port=port,
        sslContext=ctx,
        connectionPoolTimeout=5,
        **extra
    )

    try:
        yield si, vim
    finally:
        try:
            Disconnect(si)
        except Exception:
            pass

def vm_list(d):
    with esxi(d) as (si, vim):
        content = si.RetrieveContent()
        view = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
        try:
            out = []
            for vm in view.view:
                if vm.config is None:
                    continue
                power = str(vm.runtime.powerState)
                tools = 'unknown'
                if vm.guest is not None:
                    tools = str(vm.guest.toolsRunningStatus)
                out.append({
                    'id': vm._moId,
                    'name': vm.name,
                    'state': 'on' if power == 'poweredOn' else 'off' if power == 'poweredOff' else 'suspended' if power == 'suspended' else 'unknown',
                    'guest': vm.config.guestFullName or '',
                    'tools': tools,
                })
            return sorted(out, key=lambda x: x['name'].lower())
        finally:
            view.Destroy()

def fortigate_context(d):
    return ssl_context(d.get('ca_file') or '')

def fortigate_secret(d):
    blob = d.get('api_token') if 'api_token' in d else None
    if blob not in (None, b''):
        try:
            return dec(blob)
        except Exception:
            pass
    pw = d.get('password', b'')
    if isinstance(pw, (bytes, bytearray)):
        try:
            return dec(pw)
        except Exception:
            return ''
    return pw or ''

def fortigate_status(d):
    secret = fortigate_secret(d)
    if not secret:
        raise RuntimeError('FortiGate API token is not configured')
    ctx = fortigate_context(d)
    url = f"https://{d['host']}:{d['port']}/api/v2/monitor/system/status"
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {secret}'})
    with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
        data = json.loads(resp.read().decode())
    results = data.get('results') if isinstance(data, dict) else data
    if results is None:
        results = data
    version = ''
    serial = ''
    if isinstance(results, dict):
        version = results.get('version') or results.get('fortios_version') or ''
        serial = results.get('serial') or ''
    detail = 'FortiGate API verified'
    if version:
        detail += f' (FortiOS {version})'
    if serial:
        detail += f' serial {serial}'
    return {'state': 'healthy', 'detail': detail, 'version': version, 'serial': serial}

def fortigate_reboot(d):
    secret = fortigate_secret(d)
    if not secret:
        raise RuntimeError('FortiGate API token is not configured')
    ctx = fortigate_context(d)
    url = f"https://{d['host']}:{d['port']}/api/v2/monitor/system/reboot"
    body = json.dumps({'reboot': 'reboot'}).encode()
    req = urllib.request.Request(url, data=body, headers={
        'Authorization': f'Bearer {secret}', 'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
        return resp.status

def test_connection_for_device(d):
    kind = d['kind'] if isinstance(d, dict) else d.kind
    # support both dict-like and model
    if not isinstance(d, dict):
        d = device_from_new(d) if False else d
    if kind == 'esxi':
        try:
            vms = vm_list(d)
            return {'ok': True, 'state': 'online', 'detail': f'ESXi authenticated; {len(vms)} VMs discovered', 'vms': vms}
        except Exception as e:
            return {'ok': False, 'state': 'unknown', 'detail': str(e)[:240], 'vms': []}
    if kind == 'fortigate':
        if not reach(d['host'], d['port']):
            return {'ok': False, 'state': 'unknown', 'detail': 'Management port unreachable', 'vms': []}
        try:
            info = fortigate_status(d)
            return {'ok': True, 'state': info['state'], 'detail': info['detail'], 'vms': []}
        except Exception as e:
            return {'ok': False, 'state': 'reachable', 'detail': f'Port reachable but API verification failed: {str(e)[:180]}', 'vms': []}
    if reach(d['host'], d['port']):
        return {'ok': True, 'state': 'reachable', 'detail': 'TCP port reachable; OS health not verified', 'vms': []}
    return {'ok': False, 'state': 'unknown', 'detail': 'Management endpoint unreachable', 'vms': []}

def audit(action, target, result, details='', actor='api-key'):
    try:
        with sqlite3.connect(DB) as db:
            db.execute('INSERT INTO audit(action,target,result,details,actor) VALUES (?,?,?,?,?)',
                       (action, target, result, details, actor))
    except Exception:
        pass

def device_from_new(d: NewDevice):
    secret = d.api_token if (d.kind == 'fortigate' and d.api_token) else d.password
    return {
        'name': d.name, 'kind': d.kind, 'host': d.host, 'port': d.port,
        'username': d.username, 'password': secret, 'ca_file': d.ca_file,
        'cert_fingerprint': d.cert_fingerprint,
    }

def validate_device(d: NewDevice):
    if d.kind not in ('esxi', 'fortigate', 'ubuntu'):
        raise HTTPException(400, 'Unsupported device type')
    validate_host(d.host)
    if d.kind == 'esxi' and (not d.username or not d.password):
        raise HTTPException(400, 'ESXi username and password are required')
    if d.kind == 'fortigate' and not (d.api_token or d.password):
        raise HTTPException(400, 'FortiGate API token is required')

def to_record_dict(row):
    r = dict(row)
    for k in ('username', 'password'):
        if k in r and r[k] is None:
            r[k] = b''
    if 'api_token' in r and r.get('api_token') is None:
        r['api_token'] = b''
    return r

@app.get('/health')
def health(x_api_key: str | None = Header(default=None)):
    auth(x_api_key)
    return {'ok': True, 'version': VERSION, 'time': now()}

@app.get('/devices')
def devices(x_api_key: str | None = Header(default=None)):
    auth(x_api_key)
    output = []
    for row in records():
        d = to_record_dict(row)
        item = public(d)
        item['vms'] = []
        item['state'] = 'unknown'
        item['detail'] = ''
        if d['kind'] == 'esxi':
            try:
                vms = vm_list(d)
                item['vms'] = vms
                item['state'] = 'online'
                item['detail'] = f'Authenticated ESXi API; {len(vms)} VMs'
            except Exception as e:
                item['state'] = 'unknown'
                item['vms'] = []
                item['detail'] = str(e)[:200]
        elif d['kind'] == 'fortigate':
            if reach(d['host'], d['port']):
                try:
                    info = fortigate_status(d)
                    item['state'] = info['state']
                    item['detail'] = info['detail']
                except Exception as e:
                    item['state'] = 'reachable'
                    item['detail'] = f'Port reachable but API verification failed: {str(e)[:180]}'
            else:
                item['state'] = 'unknown'
                item['detail'] = 'Management port unreachable'
        else:
            item['state'] = 'reachable' if reach(d['host'], d['port']) else 'unknown'
            item['detail'] = 'TCP port reachable; OS health not verified' if item['state'] == 'reachable' else 'Management endpoint unreachable'
        output.append(item)
    return {'devices': output}

@app.post('/devices/test-connection')
def test_connection_unsaved(d: NewDevice, x_api_key: str | None = Header(default=None)):
    auth(x_api_key)
    validate_device(d)
    rd = device_from_new(d)
    rd_db = {
        'id': '', 'name': rd['name'], 'kind': rd['kind'], 'host': rd['host'], 'port': rd['port'],
        'username': enc(rd['username']), 'password': enc(rd['password']), 'ca_file': rd['ca_file'],
        'cert_fingerprint': rd['cert_fingerprint'],
    }
    return test_connection_for_device(rd_db)

@app.post('/devices/{device_id}/test')
def test_connection_saved(device_id: str, x_api_key: str | None = Header(default=None)):
    auth(x_api_key)
    d = get_device(device_id)
    if d is None:
        raise HTTPException(404, 'Device not found')
    return test_connection_for_device(d)

@app.post('/devices', status_code=201)
def add(d: NewDevice, x_api_key: str | None = Header(default=None)):
    auth(x_api_key)
    validate_device(d)
    rd = device_from_new(d)
    ident = str(uuid.uuid4())
    with sqlite3.connect(DB) as db:
        db.execute('''INSERT INTO devices (id,name,kind,host,port,username,password,ca_file,cert_fingerprint,enabled,created_at,updated_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (ident, rd['name'], rd['kind'], rd['host'], rd['port'], enc(rd['username']),
                    enc(rd['password']), rd['ca_file'], rd['cert_fingerprint'], 1, now(), now()))
    audit('device_add', ident, 'ok', rd['name'])
    return {'id': ident, 'name': rd['name']}

@app.put('/devices/{device_id}')
def update(device_id: str, d: NewDevice, x_api_key: str | None = Header(default=None)):
    auth(x_api_key)
    existing = get_device(device_id)
    if existing is None:
        raise HTTPException(404, 'Device not found')
    validate_device(d)
    rd = device_from_new(d)
    if d.kind == 'esxi' and not d.password:
        rd['password'] = dec(existing['password']) if existing['password'] else ''
    if d.kind == 'fortigate' and not (d.api_token or d.password):
        rd['password'] = dec(existing['password']) if existing['password'] else ''
    with sqlite3.connect(DB) as db:
        db.execute('''UPDATE devices SET name=?,kind=?,host=?,port=?,username=?,password=?,ca_file=?,cert_fingerprint=?,updated_at=? WHERE id=?''',
                   (rd['name'], rd['kind'], rd['host'], rd['port'], enc(rd['username']), enc(rd['password']),
                    rd['ca_file'], rd['cert_fingerprint'], now(), device_id))
    audit('device_update', device_id, 'ok', rd['name'])
    return {'id': device_id, 'name': rd['name']}

@app.delete('/devices/{device_id}')
def delete(device_id: str, x_api_key: str | None = Header(default=None)):
    auth(x_api_key)
    existing = get_device(device_id)
    if existing is None:
        raise HTTPException(404, 'Device not found')
    with sqlite3.connect(DB) as db:
        db.execute('DELETE FROM devices WHERE id=?', (device_id,))
    audit('device_delete', device_id, 'ok', existing['name'])
    return {'ok': True}

@app.post('/devices/{device_id}/vms/{vm_id}/command')
def vm_command(device_id: str, vm_id: str, cmd: Command, x_api_key: str | None = Header(default=None)):
    auth(x_api_key)
    if not cmd.confirm:
        raise HTTPException(400, 'Explicit confirmation required')
    if cmd.action not in ('power_on', 'reboot_guest', 'shutdown_guest'):
        raise HTTPException(400, 'Unsupported VM action')
    d = get_device(device_id)
    if d is None or d['kind'] != 'esxi':
        raise HTTPException(404, 'ESXi host not found')
    lock = _vm_command_lock(device_id, vm_id)
    if not lock.acquire(blocking=False):
        audit(cmd.action, f'{device_id}/{vm_id}', 'conflict', 'command already in progress')
        raise HTTPException(409, 'A command for this VM is already in progress')
    try:
        with esxi(d) as (si, vim):
            content = si.RetrieveContent()
            view = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
            try:
                vm = None
                for v in view.view:
                    if v._moId == vm_id:
                        vm = v
                        break
            finally:
                view.Destroy()
            if vm is None:
                raise HTTPException(404, 'VM is not in host inventory')
            state = str(vm.runtime.powerState)
            tools = str(vm.guest.toolsRunningStatus) if vm.guest else 'unknown'
            if cmd.action == 'power_on':
                if state != 'poweredOff':
                    raise HTTPException(409, 'VM is not powered off')
                try:
                    task = vm.PowerOnVM_Task()
                except Exception as e:
                    if _vmomi_vim is not None and isinstance(e, _vmomi_vim.fault.VimFault):
                        detail = getattr(e, 'msg', 'VMware fault')
                        audit(cmd.action, f'{device_id}/{vm_id}', 'failed', str(detail)[:180])
                        raise HTTPException(502, f'Power on failed: {detail[:180]}')
                    raise
                outcome = _wait_for_task(si, task)
                if outcome is True:
                    result = f'Powered on (task {str(getattr(task, "_moId", ""))})'
                elif outcome is None:
                    audit(cmd.action, f'{device_id}/{vm_id}', 'timeout', f'task {str(getattr(task, "_moId", ""))}')
                    raise HTTPException(504, 'Power on task did not complete in time')
                else:
                    audit(cmd.action, f'{device_id}/{vm_id}', 'failed', str(outcome)[:180])
                    raise HTTPException(502, f'Power on failed: {str(outcome)[:180]}')
            elif cmd.action == 'reboot_guest':
                if state != 'poweredOn':
                    raise HTTPException(409, 'VM is not powered on')
                if tools != 'guestToolsRunning':
                    raise HTTPException(409, 'VMware Tools is not running; graceful guest restart is unavailable')
                vm.RebootGuest()
                result = 'Graceful guest reboot requested'
            elif cmd.action == 'shutdown_guest':
                if state != 'poweredOn':
                    raise HTTPException(409, 'VM is not powered on')
                if tools != 'guestToolsRunning':
                    raise HTTPException(409, 'VMware Tools is not running; graceful guest shutdown is unavailable')
                vm.ShutdownGuest()
                result = 'Graceful guest shutdown requested'
            else:
                raise HTTPException(400, 'Unsupported action')
    except HTTPException:
        raise
    except Exception as e:
        if _vmomi_vim is not None and isinstance(e, _vmomi_vim.fault.VimFault):
            detail = getattr(e, 'msg', 'VMware fault')
            audit(cmd.action, f'{device_id}/{vm_id}', 'failed', str(detail)[:180])
            raise HTTPException(502, f'ESXi operation failed: {str(detail)[:180]}')
        audit(cmd.action, f'{device_id}/{vm_id}', 'failed', str(e)[:180])
        raise HTTPException(502, f'ESXi operation failed: {str(e)[:180]}')
    finally:
        lock.release()
    audit(cmd.action, f'{device_id}/{vm_id}', 'ok', result[:200])
    return {'ok': True, 'message': result}

@app.post('/devices/{device_id}/restart')
def device_restart(device_id: str, cmd: Command, x_api_key: str | None = Header(default=None)):
    auth(x_api_key)
    if not cmd.confirm:
        raise HTTPException(400, 'Explicit confirmation required')
    d = get_device(device_id)
    if d is None:
        raise HTTPException(404, 'Device not found')
    if d['kind'] != 'fortigate':
        raise HTTPException(400, 'Restart is only implemented for verified FortiGate devices')
    if os.environ.get('NCC_ENABLE_FORTIGATE_REBOOT', '').lower() not in ('1', 'true', 'yes'):
        audit('fortigate_restart', device_id, 'disabled', 'Reboot disabled until verified')
        raise HTTPException(501, 'FortiGate reboot is disabled until firmware and permissions are verified; enable NCC_ENABLE_FORTIGATE_REBOOT only after validation')
    try:
        fortigate_reboot(d)
        result = 'Reboot command accepted; controller will monitor reconnection'
    except Exception as e:
        audit('fortigate_restart', device_id, 'failed', str(e)[:180])
        raise HTTPException(502, f'FortiGate reboot failed: {str(e)[:180]}')
    audit('fortigate_restart', device_id, 'ok', result)
    return {'ok': True, 'message': result}

@app.get('/audit')
def audit_log(limit: int = 100, x_api_key: str | None = Header(default=None)):
    auth(x_api_key)
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT ?', (min(max(limit, 1), 500),)).fetchall()
    return {'entries': [dict(r) for r in rows]}

@app.get('/devices/{device_id}/diagnostics')
def diagnostics(device_id: str, x_api_key: str | None = Header(default=None)):
    auth(x_api_key)
    d = get_device(device_id)
    if d is None:
        raise HTTPException(404, 'Device not found')
    res = test_connection_for_device(d)
    return {
        'device_id': device_id,
        'kind': d['kind'],
        'state': res['state'],
        'detail': res['detail'],
        'ok': res['ok'],
        'checked_at': now(),
    }
