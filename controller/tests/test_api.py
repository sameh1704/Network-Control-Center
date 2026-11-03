import os, sys, tempfile
from pathlib import Path
import ssl
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.fernet import Fernet
os.environ.setdefault('NCC_API_KEY', 'test-only-very-long-key-never-use-in-production-012345')
os.environ.setdefault('NCC_ENCRYPTION_KEY', Fernet.generate_key().decode())
_db = tempfile.NamedTemporaryFile(delete=False)
_db.close()
os.environ['NCC_DB'] = _db.name
import pytest
from fastapi.testclient import TestClient
from main import app, vm_list, esxi, fortigate_status, fortigate_reboot
from pyVmomi import vim

KEY = os.environ['NCC_API_KEY']
HEADERS = {'X-API-Key': KEY}
client = TestClient(app)

def test_health_auth():
    assert client.get('/health').status_code == 401
    r = client.get('/health', headers=HEADERS)
    assert r.status_code == 200
    assert r.json()['ok'] is True

def test_add_and_list_device():
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'ESXi Lab', 'kind': 'esxi', 'host': '192.168.1.10', 'port': 443,
        'username': 'root', 'password': 'secret', 'ca_file': ''})
    assert r.status_code == 201
    did = r.json()['id']
    r = client.get('/devices', headers=HEADERS)
    assert r.status_code == 200
    devs = r.json()['devices']
    assert any(d['id'] == did and d['name'] == 'ESXi Lab' for d in devs)
    dev = next(d for d in devs if d['id'] == did)
    assert 'password' not in dev
    assert 'username' not in dev

def test_reject_public_host():
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'Bad', 'kind': 'esxi', 'host': '8.8.8.8', 'port': 443,
        'username': 'root', 'password': 'secret'})
    assert r.status_code == 400

def test_fortigate_requires_token():
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'FG', 'kind': 'fortigate', 'host': '192.168.1.1', 'port': 443})
    assert r.status_code == 400

def test_vm_discovery_monkeypatch(monkeypatch):
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'ESXi', 'kind': 'esxi', 'host': '192.168.1.20', 'port': 443,
        'username': 'root', 'password': 'secret'})
    did = r.json()['id']
    monkeypatch.setattr('main.vm_list', lambda d: [
        {'id': 'vm-1', 'name': 'ubuntu-01', 'state': 'on', 'guest': 'Ubuntu', 'tools': 'guestToolsRunning'},
        {'id': 'vm-2', 'name': 'ubuntu-02', 'state': 'off', 'guest': 'Ubuntu', 'tools': 'guestToolsNotRunning'}])
    r = client.get('/devices', headers=HEADERS)
    dev = next(d for d in r.json()['devices'] if d['id'] == did)
    assert dev['state'] == 'online'
    assert len(dev['vms']) == 2

def test_vm_command_power_on(monkeypatch):
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'ESXi2', 'kind': 'esxi', 'host': '192.168.1.21', 'port': 443,
        'username': 'root', 'password': 'secret'})
    did = r.json()['id']

    class FakeVM:
        def __init__(self):
            self._moId = 'vm-1'
            self.name = 'vm1'
            self.runtime = type('R', (), {'powerState': 'poweredOff'})()
            self.config = type('C', (), {'guestFullName': 'Ubuntu'})()
            self.guest = type('G', (), {'toolsRunningStatus': 'guestToolsNotRunning'})()
            self.powered = False
        def PowerOnVM_Task(self):
            self.powered = True
            return type('T', (), {'_moId': 'task-1', 'info': type('I', (), {'state': 'success'})()})()

    fake_vm = FakeVM()

    class FakeContent:
        def viewManager(self): return None

    class FakeSI:
        def RetrieveContent(self):
            view = type('V', (), {'Destroy': lambda self: None})()
            view.view = [fake_vm]
            cm = type('CM', (), {})()
            cm.CreateContainerView = lambda *a, **k: view
            content = type('C', (), {})()
            content.viewManager = cm
            content.rootFolder = None
            return content
        _stub = None

    import contextlib
    @contextlib.contextmanager
    def fake_esxi(d):
        yield FakeSI(), __import__('pyVmomi').vim

    monkeypatch.setattr('main.esxi', fake_esxi)
    # ensure vm id exists in view handled by fake
    r = client.post(f'/devices/{did}/vms/vm-1/command', headers=HEADERS, json={'action': 'power_on', 'confirm': True})
    assert r.status_code == 200
    assert 'Powered on' in r.json()['message']
    ar = client.get('/audit', headers=HEADERS)
    assert any(e['action'] == 'power_on' and e['result'] == 'ok' for e in ar.json()['entries'])
    assert 'secret' not in str(ar.json())

def test_reboot_guest_requires_tools(monkeypatch):
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'ESXi3', 'kind': 'esxi', 'host': '192.168.1.22', 'port': 443,
        'username': 'root', 'password': 'secret'})
    did = r.json()['id']

    class FakeVM:
        def __init__(self):
            self._moId = 'vm-1'
            self.name = 'vm1'
            self.runtime = type('R', (), {'powerState': 'poweredOn'})()
            self.config = type('C', (), {'guestFullName': 'Ubuntu'})()
            self.guest = type('G', (), {'toolsRunningStatus': 'guestToolsNotRunning'})()
        def RebootGuest(self):
            raise AssertionError('should not be called')

    fake_vm = FakeVM()

    class FakeSI:
        def RetrieveContent(self):
            view = type('V', (), {'Destroy': lambda self: None})()
            view.view = [fake_vm]
            cm = type('CM', (), {})()
            cm.CreateContainerView = lambda *a, **k: view
            content = type('C', (), {})()
            content.viewManager = cm
            content.rootFolder = None
            return content
        _stub = None

    import contextlib
    @contextlib.contextmanager
    def fake_esxi(d):
        yield FakeSI(), __import__('pyVmomi').vim

    monkeypatch.setattr('main.esxi', fake_esxi)
    r = client.post(f'/devices/{did}/vms/vm-1/command', headers=HEADERS, json={'action': 'reboot_guest', 'confirm': True})
    assert r.status_code == 409

def test_fortigate_restart_disabled():
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'FG', 'kind': 'fortigate', 'host': '192.168.1.50', 'port': 443,
        'api_token': 'tokensecret'})
    did = r.json()['id']
    r = client.post(f'/devices/{did}/restart', headers=HEADERS, json={'action': 'restart', 'confirm': True})
    assert r.status_code == 501

def test_audit_log():
    r = client.get('/audit', headers=HEADERS)
    assert r.status_code == 200
    assert 'entries' in r.json()

def test_diagnostics():
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'Dev', 'kind': 'ubuntu', 'host': '192.168.1.60', 'port': 22})
    did = r.json()['id']
    r = client.get(f'/devices/{did}/diagnostics', headers=HEADERS)
    assert r.status_code == 200
    assert 'state' in r.json()

def test_edit_device():
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'EditMe', 'kind': 'ubuntu', 'host': '192.168.1.70', 'port': 22})
    did = r.json()['id']
    r = client.put(f'/devices/{did}', headers=HEADERS, json={
        'name': 'Edited', 'kind': 'ubuntu', 'host': '192.168.1.70', 'port': 22})
    assert r.status_code == 200
    r = client.get('/devices', headers=HEADERS)
    dev = next(d for d in r.json()['devices'] if d['id'] == did)
    assert dev['name'] == 'Edited'

def test_delete_device():
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'DelMe', 'kind': 'ubuntu', 'host': '192.168.1.80', 'port': 22})
    did = r.json()['id']
    r = client.delete(f'/devices/{did}', headers=HEADERS)
    assert r.status_code == 200
    r = client.get('/devices', headers=HEADERS)
    assert not any(d['id'] == did for d in r.json()['devices'])

def test_test_connection_endpoint():
    r = client.post('/devices/test-connection', headers=HEADERS, json={
        'name': 'TC', 'kind': 'ubuntu', 'host': '192.168.1.90', 'port': 22})
    assert r.status_code == 200
    assert 'state' in r.json()

def _fake_esxi_with_vm(monkeypatch, power_state, task_state='success', fault=None, tools='guestToolsNotRunning'):
    import contextlib

    class FakeVM:
        def __init__(self):
            self._moId = 'vm-1'
            self.name = 'vm1'
            self.runtime = type('R', (), {'powerState': power_state})()
            self.config = type('C', (), {'guestFullName': 'Ubuntu'})()
            self.guest = type('G', (), {'toolsRunningStatus': tools})()
            self.actions = []

        def PowerOnVM_Task(self):
            if fault is not None:
                raise fault
            return type('T', (), {'_moId': 'task-1', 'info': type('I', (), {'state': task_state})()})()

        def RebootGuest(self):
            self.actions.append('reboot_guest')

        def ShutdownGuest(self):
            self.actions.append('shutdown_guest')

    fake_vm = FakeVM()

    class FakeSI:
        def RetrieveContent(self):
            view = type('V', (), {'Destroy': lambda self: None})()
            view.view = [fake_vm]
            cm = type('CM', (), {})()
            cm.CreateContainerView = lambda *a, **k: view
            content = type('C', (), {})()
            content.viewManager = cm
            content.rootFolder = None
            return content
        _stub = None

    @contextlib.contextmanager
    def fake_esxi(d):
        yield FakeSI(), vim

    monkeypatch.setattr('main.esxi', fake_esxi)
    return fake_vm

def test_vm_command_power_on_running_rejected(monkeypatch):
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'ESXiRun', 'kind': 'esxi', 'host': '192.168.1.31', 'port': 443,
        'username': 'root', 'password': 'secret'})
    did = r.json()['id']
    _fake_esxi_with_vm(monkeypatch, 'poweredOn')
    r = client.post(f'/devices/{did}/vms/vm-1/command', headers=HEADERS, json={'action': 'power_on', 'confirm': True})
    assert r.status_code == 409

def test_vm_command_power_on_duplicate_rejected(monkeypatch):
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'ESXiDup', 'kind': 'esxi', 'host': '192.168.1.32', 'port': 443,
        'username': 'root', 'password': 'secret'})
    did = r.json()['id']
    import main
    lock = main._vm_command_lock(did, 'vm-1')
    assert lock.acquire(blocking=False)
    try:
        r = client.post(f'/devices/{did}/vms/vm-1/command', headers=HEADERS, json={'action': 'power_on', 'confirm': True})
        assert r.status_code == 409
        ar = client.get('/audit', headers=HEADERS)
        assert any(e['action'] == 'power_on' and e['result'] == 'conflict' for e in ar.json()['entries'])
    finally:
        lock.release()

def test_vm_command_power_on_timeout(monkeypatch):
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'ESXiTmo', 'kind': 'esxi', 'host': '192.168.1.33', 'port': 443,
        'username': 'root', 'password': 'secret'})
    did = r.json()['id']
    _fake_esxi_with_vm(monkeypatch, 'poweredOff')
    monkeypatch.setattr('main._wait_for_task', lambda si, task, timeout=60: None)
    r = client.post(f'/devices/{did}/vms/vm-1/command', headers=HEADERS, json={'action': 'power_on', 'confirm': True})
    assert r.status_code == 504
    ar = client.get('/audit', headers=HEADERS)
    assert any(e['action'] == 'power_on' and e['result'] == 'timeout' for e in ar.json()['entries'])

def test_vm_command_power_on_task_error(monkeypatch):
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'ESXiTaskError', 'kind': 'esxi', 'host': '192.168.1.36', 'port': 443,
        'username': 'root', 'password': 'secret'})
    did = r.json()['id']
    _fake_esxi_with_vm(monkeypatch, 'poweredOff', task_state='error')
    r = client.post(f'/devices/{did}/vms/vm-1/command', headers=HEADERS, json={'action': 'power_on', 'confirm': True})
    assert r.status_code == 502
    assert 'VMware task failed' in r.json()['detail']
    ar = client.get('/audit', headers=HEADERS)
    assert any(e['action'] == 'power_on' and e['result'] == 'failed' for e in ar.json()['entries'])

def test_vm_command_power_on_vmware_fault(monkeypatch):
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'ESXiFault', 'kind': 'esxi', 'host': '192.168.1.34', 'port': 443,
        'username': 'root', 'password': 'secret'})
    did = r.json()['id']
    _fake_esxi_with_vm(monkeypatch, 'poweredOff', fault=vim.fault.VimFault(msg='hostd communication failure'))
    r = client.post(f'/devices/{did}/vms/vm-1/command', headers=HEADERS, json={'action': 'power_on', 'confirm': True})
    assert r.status_code == 502
    assert 'hostd communication failure' in r.json()['detail']
    ar = client.get('/audit', headers=HEADERS)
    assert any(e['action'] == 'power_on' and e['result'] == 'failed' for e in ar.json()['entries'])

def test_vm_discovery_suspended_state(monkeypatch):
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'ESXiSus', 'kind': 'esxi', 'host': '192.168.1.35', 'port': 443,
        'username': 'root', 'password': 'secret'})
    did = r.json()['id']
    _fake_esxi_with_vm(monkeypatch, 'suspended')
    r = client.get('/devices', headers=HEADERS)
    dev = next(d for d in r.json()['devices'] if d['id'] == did)
    assert dev['state'] == 'online'
    assert len(dev['vms']) == 1
    assert dev['vms'][0]['state'] == 'suspended'

@pytest.mark.parametrize(('action', 'expected'), [
    ('reboot_guest', 'reboot_guest'),
    ('shutdown_guest', 'shutdown_guest'),
])
def test_vm_command_graceful_guest_actions(monkeypatch, action, expected):
    r = client.post('/devices', headers=HEADERS, json={
        'name': 'ESXiGuestAction', 'kind': 'esxi', 'host': '192.168.1.37', 'port': 443,
        'username': 'root', 'password': 'secret'})
    did = r.json()['id']
    fake_vm = _fake_esxi_with_vm(monkeypatch, 'poweredOn', tools='guestToolsRunning')
    r = client.post(f'/devices/{did}/vms/vm-1/command', headers=HEADERS, json={'action': action, 'confirm': True})
    assert r.status_code == 200
    assert fake_vm.actions == [expected]

@pytest.mark.parametrize(('host', 'expected_hash'), [
    ('172.16.1.230', 'e2839d7f980e3cf48770a32f24e685a4275636ab10098f40e43164c4de880ee3'),
    ('172.16.1.220', '46bd0d1f56238d39231573e450e89da98d2f5f8643da921645f266fcf7f862e8'),
])
def test_esxi_pinned_hosts_use_verified_tls(monkeypatch, host, expected_hash):
    import hashlib
    import pyVim.connect

    pem = 'mock certificate'
    captured = {}
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    monkeypatch.setattr(Path, 'is_file', lambda self: True)
    monkeypatch.setattr(Path, 'read_text', lambda self, encoding=None: pem)
    monkeypatch.setattr(ssl, 'PEM_cert_to_DER_cert', lambda value: b'mock der')
    monkeypatch.setattr(hashlib, 'sha256', lambda value: type('Hash', (), {'hexdigest': lambda self: expected_hash})())
    monkeypatch.setattr(ssl, 'create_default_context', lambda cafile=None: context)

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(pyVim.connect, 'SmartConnect', fake_connect)
    monkeypatch.setattr(pyVim.connect, 'Disconnect', lambda si: None)
    device = {
        'kind': 'esxi', 'host': host, 'port': 443,
        'username': __import__('main').enc('operator'),
        'password': __import__('main').enc('test-only-password'),
    }

    with esxi(device) as (si, _):
        assert si is not None

    assert captured['serverPemCert'] == pem
    assert captured['sslContext'] is context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert ssl.VERIFY_X509_PARTIAL_CHAIN & context.verify_flags

def test_esxi_pinned_host_rejects_certificate_mismatch(monkeypatch):
    import hashlib
    import pyVim.connect

    monkeypatch.setattr(Path, 'is_file', lambda self: True)
    monkeypatch.setattr(Path, 'read_text', lambda self, encoding=None: 'mock certificate')
    monkeypatch.setattr(ssl, 'PEM_cert_to_DER_cert', lambda value: b'mock der')
    monkeypatch.setattr(hashlib, 'sha256', lambda value: type('Hash', (), {'hexdigest': lambda self: '0' * 64})())
    monkeypatch.setattr(pyVim.connect, 'SmartConnect', lambda **kwargs: pytest.fail('must reject pin mismatch before connecting'))
    device = {
        'kind': 'esxi', 'host': '172.16.1.230', 'port': 443,
        'username': __import__('main').enc('operator'),
        'password': __import__('main').enc('test-only-password'),
    }

    with pytest.raises(RuntimeError, match='ESXi certificate pin mismatch'):
        with esxi(device):
            pass
