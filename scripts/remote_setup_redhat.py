#!/usr/bin/env python3
import paramiko
import sys
import base64
import time

if len(sys.argv) < 6:
    print("usage: remote_setup_redhat.py HOST USER PASSWORD PUBKEY_PATH PRIVKEY_PATH")
    sys.exit(2)

HOST=sys.argv[1]
USER=sys.argv[2]
PASSWORD=sys.argv[3]
PUB=sys.argv[4]
PRIV=sys.argv[5]

with open(PUB, 'r') as f:
    pubkey = f.read().strip()

b64 = base64.b64encode(pubkey.encode()).decode()

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print('connecting to', HOST)
ssh.connect(HOST, username=USER, password=PASSWORD, timeout=20)
print('connected')

# create .ssh and append key if missing
remote_cmd = (
    f'BASE64="{b64}"; mkdir -p ~/.ssh; chmod 700 ~/.ssh; '
    "if [ ! -f ~/.ssh/authorized_keys ] || ! grep -q \"$(echo $BASE64 | base64 -d)\" ~/.ssh/authorized_keys; then "
    "echo \"$BASE64\" | base64 -d >> ~/.ssh/authorized_keys; fi; chmod 600 ~/.ssh/authorized_keys"
)
print('running remote setup cmd')
stdin, stdout, stderr = ssh.exec_command(remote_cmd)
exit_status = stdout.channel.recv_exit_status()
print('remote setup exit', exit_status)
print(stdout.read().decode(), stderr.read().decode())

# test key auth by attempting new connection with private key
print('testing key auth')
try:
    pkey = paramiko.RSAKey.from_private_key_file(PRIV)
    test = paramiko.SSHClient()
    test.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    test.connect(HOST, username=USER, pkey=pkey, timeout=10)
    print('KEY_OK')
    test.close()
except Exception as e:
    print('KEY_TEST_FAILED', repr(e))
    ssh.close()
    sys.exit(3)

# disable password auth (use echo password | sudo -S ...)
print('disabling password auth and restarting sshd')
disable_cmd = (
    f"echo {PASSWORD} | sudo -S -p '' bash -lc 'sed -i -e \"s/^#\\?PasswordAuthentication.*/PasswordAuthentication no/\" -e \"s/^#\\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/\" /etc/ssh/sshd_config && systemctl restart sshd'"
)
stdin, stdout, stderr = ssh.exec_command(disable_cmd)
# consume
out = stdout.read().decode()
err = stderr.read().decode()
print('disable output:', out, err)

# determine package manager
stdin, stdout, stderr = ssh.exec_command('which dnf || which yum || echo none')
pm = stdout.read().decode().strip()
print('pkg manager:', npm)
if npm == 'none':
    print('no package manager found (dnf/yum)')
else:
    # start update in background and log to /tmp/redhat_update.log
    update_cmd = f"echo {PASSWORD} | sudo -S -p '' {npm} -y update > /tmp/redhat_update.log 2>&1 &"
    stdin, stdout, stderr = ssh.exec_command(update_cmd)
    print('update started')

ssh.close()
print('done')
