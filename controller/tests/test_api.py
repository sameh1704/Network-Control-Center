import os, sys, tempfile
from pathlib import Path
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
            return type('T', (), {'_moId': 'task-1'})()

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
    assert 'Power on' in r.json()['message']

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
