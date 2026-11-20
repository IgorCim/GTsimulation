"""Fetch pinned audit references using a fully verified Let's Encrypt chain."""
import hashlib
import json
from pathlib import Path
import ssl
from urllib.request import urlopen

root=Path(__file__).resolve().parent/'ta15-audit'
certs={'int-yr1.pem':'d5efc243446ef865c0e165eb1958a2f068c9514aa17238701bd6f7ad90253ce7',
       'root-yr-by-x1.pem':'b3858d7a4d598b4ab6ed2892a1b8c0ee035154876dd40a082a3b05387eea11a4'}
chain=[]
for name,expected in certs.items():
    body=urlopen('https://letsencrypt.org/certs/gen-y/'+name,timeout=60).read()
    assert hashlib.sha256(body).hexdigest()==expected,'CA reference changed: '+name
    chain.append(body.decode('ascii'))
context=ssl.create_default_context()
context.load_verify_locations(cadata='\n'.join(chain))
context.verify_flags &= ~getattr(ssl,'VERIFY_X509_PARTIAL_CHAIN',0)
for name,meta in json.loads((root/'sources.json').read_text()).items():
    with urlopen(meta['url'],context=context,timeout=60) as response:body=response.read()
    assert hashlib.sha256(body).hexdigest()==meta['sha256'],name+' changed upstream; audit halted'
    (root/name).write_bytes(body)
print('Official audit references downloaded with verified TLS and matching SHA256.')
