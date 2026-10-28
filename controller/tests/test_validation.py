"""Lightweight non-network tests for security checks and model validation."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.fernet import Fernet
os.environ.setdefault('NCC_API_KEY', 'test-only-very-long-key-never-use-in-production-012345')
os.environ.setdefault('NCC_ENCRYPTION_KEY', Fernet.generate_key().decode())
os.environ.setdefault('NCC_DB', ':memory:')
import pytest
from fastapi import HTTPException
from main import NewDevice, validate_host, enc, dec

def test_encryption_roundtrip():
    assert dec(enc('secret123')) == 'secret123'
    assert enc('secret123') != b'secret123'

def test_private_ip_allowed():
    validate_host('192.168.10.10')
    validate_host('10.30.10.1')

@pytest.mark.parametrize('host', ['8.8.8.8','127.0.0.1','169.254.4.4','not-a-host'])
def test_reject_untrusted_target(host):
    with pytest.raises(HTTPException): validate_host(host)

def test_device_validation():
    x=NewDevice(name='Host',kind='esxi',host='192.168.1.10',port=443,username='operator',password='sample')
    assert x.kind=='esxi'
