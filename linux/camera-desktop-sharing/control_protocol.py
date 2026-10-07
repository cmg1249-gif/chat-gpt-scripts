"""Authenticated discovery and ephemeral TLS for the control center."""
import base64
import datetime
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import ssl
import threading
import time
import urllib.request
from pathlib import Path

APP = 'roomcam-control-v3'
PORT = 2220


def new_code():
    return base64.b32encode(secrets.token_bytes(16)).decode().rstrip('=')


def normalize_code(code):
    code = re.sub(r'[\s-]', '', str(code)).upper()
    if not re.fullmatch(r'[A-Z2-7]{26}', code):
        raise ValueError('Enter the 26-character code shown on the sharing computer.')
    return code


def topic_for(code):
    return 'roomcam-v3-' + hashlib.sha256(('discovery:' + code).encode()).hexdigest()[:40]


def sign(data, code):
    body = {k: v for k, v in data.items() if k != 'signature'}
    body['signature'] = hmac.new(code.encode(), json.dumps(body, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
    return body


def verified(data, code, nonce=None):
    if not isinstance(data, dict) or data.get('app') != APP:
        return False
    if not isinstance(data.get('created'), (int, float)) or abs(time.time() - data['created']) > 120:
        return False
    if nonce is not None and data.get('nonce') != nonce:
        return False
    signature = data.get('signature')
    return isinstance(signature, str) and hmac.compare_digest(sign(data, code)['signature'], signature)


def tunnel_url(url):
    return isinstance(url, str) and bool(re.fullmatch(r'https://(?!api\.|www\.)[a-z0-9]+(?:-[a-z0-9]+)+\.trycloudflare\.com', url))


def relay_url(url):
    return isinstance(url, str) and bool(re.fullmatch(
        r'https://[a-z0-9][a-z0-9-]{5,80}\.(?:run\.pinggy-free\.link|free\.pinggy\.net|a\.free\.pinggy\.link)', url))


def internet_candidate(data, code):
    if not verified(data, code):
        raise ValueError('Connection details are expired or do not match this host code.')
    url = data.get('url')
    if tunnel_url(url):
        from tls import HTTPS_CONTEXT
        return url, HTTPS_CONTEXT, 'Cloudflare'
    if relay_url(url) and isinstance(data.get('certificate'), str):
        return url, pinned_context(data['certificate']), 'Pinggy encrypted relay'
    raise ValueError('Unrecognized relay address or missing host certificate.')


def connection_details(code, advertisements):
    body = json.dumps(dict(code=code, advertisements=advertisements), separators=(',', ':')).encode()
    return 'roomcam:' + base64.urlsafe_b64encode(body).decode()


def parse_connection_details(value):
    if not isinstance(value, str) or len(value) > 16000:
        raise ValueError('Invalid connection details.')
    if not value.startswith('roomcam:'):
        return normalize_code(value), []
    try:
        data = json.loads(base64.b64decode(value[8:], altchars=b'-_', validate=True))
        code = normalize_code(data['code'])
        adverts = data['advertisements']
        if not isinstance(adverts, list) or not 1 <= len(adverts) <= 4:
            raise ValueError('No active internet route in these connection details.')
        return code, [internet_candidate(item, code) for item in adverts]
    except (KeyError, TypeError, UnicodeError) as exc:
        raise ValueError('Invalid connection details.') from exc


def make_certificate(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'RoomCam session')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=7))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256()))
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    certpath, keypath = Path(directory) / 'session.crt', Path(directory) / 'session.key'
    certpath.write_text(pem, encoding='ascii')
    keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certpath, keypath)
    return context, pem


def pinned_context(pem):
    # The pairing-code signature authenticates this exact ephemeral certificate.
    # No public roots are trusted here; the pin supplies identity, not a DNS name.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cadata=pem)
    return context


class Discovery:
    def __init__(self, code, identity, port=PORT, topic=None):
        self.code, self.identity, self.port = code, identity, port
        self.topic = topic or topic_for(code)
        self.stop = threading.Event()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('0.0.0.0', port))
        self.socket.settimeout(.5)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                packet, address = self.socket.recvfrom(4096)
                data = json.loads(packet)
                nonce = data.get('nonce', '')
                if data.get('topic') != self.topic or not re.fullmatch('[a-f0-9]{32}', nonce):
                    continue
                self.socket.sendto(json.dumps(self.identity(nonce)).encode(), address)
            except (OSError, ValueError, AttributeError, TypeError):
                continue

    def close(self):
        self.stop.set()
        self.socket.close()
        self.thread.join(timeout=2)


def owner_advert(data, owner, nonce=None):
    # Owner discovery supplies candidates, not authentication. Only the signed,
    # encrypted login grants access. Never send the private credential here.
    return (isinstance(data, dict) and data.get('app') == APP and data.get('owner') == owner
            and isinstance(data.get('created'), (int, float)) and abs(time.time() - data['created']) <= 120
            and (nonce is None or data.get('nonce') == nonce))


def owner_internet_candidate(data, owner):
    if not owner_advert(data, owner):
        raise ValueError('Expired or unrelated owner discovery.')
    url = data.get('url')
    if tunnel_url(url):
        from tls import HTTPS_CONTEXT
        return url, HTTPS_CONTEXT, 'Cloudflare'
    if relay_url(url) and isinstance(data.get('certificate'), str):
        return url, pinned_context(data['certificate']), 'Pinggy encrypted relay'
    raise ValueError('Unrecognized relay address or missing certificate.')


def find_lan(code, timeout=1.5, owner=None):
    from control_owner import owner_topic
    nonce = secrets.token_hex(16)
    request = json.dumps(dict(topic=owner_topic(owner) if owner else topic_for(code), nonce=nonce)).encode()
    candidates = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(.25)
        for destination in ('255.255.255.255', '127.0.0.1'):
            try:
                sock.sendto(request, (destination, PORT))
            except OSError:
                pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw, source = sock.recvfrom(8192)
                data = json.loads(raw)
                if owner_advert(data, owner, nonce) if owner else verified(data, code, nonce):
                    if not isinstance(data.get('port'), int) or not 1 <= data['port'] <= 65535:
                        continue
                    candidates.append((f'https://{source[0]}:{data["port"]}', pinned_context(data['certificate']), 'Local network'))
                    break
            except (OSError, ValueError, KeyError, TypeError):
                continue
    return candidates


def direct_candidate(address, code, owner=None):
    # Explicit listener-supplied IPv4 address; no redirects or arbitrary URL paths.
    ip = str(ipaddress.IPv4Address(address))
    nonce = secrets.token_hex(16)
    url = f'https://{ip}:{PORT}'
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    # Bootstrap retrieves PUBLIC identity only. No pairing code/password is sent.
    with urllib.request.urlopen(url + '/control/identity?nonce=' + nonce, context=context, timeout=4) as response:
        data = json.loads(response.read(8192))
    if not (owner_advert(data, owner, nonce) if owner else verified(data, code, nonce)):
        raise ValueError('That computer did not prove it owns this pairing code.')
    return url, pinned_context(data['certificate']), 'Local network'
