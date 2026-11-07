#!/usr/bin/env python3
"""Set the private site's password without putting it in shell history or logs."""
import getpass
import json
import os
from pathlib import Path
import subprocess

AUTH_FILE = Path('/opt/1panel/www/sites/www.mzrc.online/robot/private/htpasswd')
CREDENTIAL_FILE = Path('/etc/robot-rag-access.json')
USERNAME = 'robot-admin'


def set_password(password):
    if os.geteuid() != 0:
        raise PermissionError('Run with sudo')
    if len(password) < 16 or any(char in password for char in '\r\n\0'):
        raise ValueError('Use a password of at least 16 characters, without line breaks')
    os.umask(0o077)
    hashed = subprocess.check_output(
        ['docker', 'exec', '-i', '1Panel-openresty-J3hj', 'openssl', 'passwd', '-6', '-stdin'],
        input=(password + '\n').encode(),
    ).decode().strip()
    AUTH_FILE.parent.mkdir(mode=0o700, exist_ok=True)
    AUTH_FILE.parent.chmod(0o700)
    temporary = AUTH_FILE.with_name('htpasswd.new')
    temporary.write_text(f'{USERNAME}:{hashed}\n')
    temporary.chmod(0o600)
    temporary.replace(AUTH_FILE)
    temporary = CREDENTIAL_FILE.with_name('robot-rag-access.json.new')
    temporary.write_text(json.dumps({'username': USERNAME, 'password': password}) + '\n')
    temporary.chmod(0o600)
    temporary.replace(CREDENTIAL_FILE)


if __name__ == '__main__':
    password = getpass.getpass('New website password (at least 16 characters): ')
    if password != getpass.getpass('Confirm website password: '):
        raise SystemExit('Passwords did not match; nothing changed')
    set_password(password)
    print('Website password updated. Username: ' + USERNAME)
