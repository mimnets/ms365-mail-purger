"""Certificate generation and encryption utilities for M365 Mail Purger."""

import os
import base64
import hashlib
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from cryptography.fernet import Fernet


def _derive_fernet_key(raw: str) -> bytes:
    """
    Derive a valid 32-byte URL-safe base64 Fernet key from an arbitrary string.
    Uses SHA256 to get 32 bytes, then base64-encodes them.
    """
    raw_bytes = raw.encode("utf-8")
    digest = hashlib.sha256(raw_bytes).digest()  # 32 bytes
    return base64.urlsafe_b64encode(digest)       # 44 base64 chars


def get_fernet(key: str = None) -> Fernet:
    """Get a Fernet instance. If no key, use ENCRYPTION_KEY from env."""
    if not key:
        key = os.getenv("ENCRYPTION_KEY")
        if not key:
            raise ValueError("ENCRYPTION_KEY not set and no key provided")
    return Fernet(_derive_fernet_key(key))


def encrypt_value(plain_text: str, fernet: Fernet = None) -> str:
    """Encrypt a string returning a base64 blob."""
    if fernet is None:
        fernet = get_fernet()
    return fernet.encrypt(plain_text.encode()).decode()


def decrypt_value(encrypted: str, fernet: Fernet = None) -> str:
    """Decrypt a base64 blob back to a string."""
    if fernet is None:
        fernet = get_fernet()
    return fernet.decrypt(encrypted.encode()).decode()


def generate_certificate(org_name: str) -> dict:
    """
    Generate a self-signed X.509 certificate for Azure AD app registration.
    Returns dict with:
      - pfx_bytes:  encrypted PKCS12 bytes
      - cer_bytes:  public cert (to upload to Azure)
      - password:   the random password used to protect the PFX
      - thumbprint: SHA-1 thumbprint
    """
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"M365 Mail Purger - {org_name}"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, org_name),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365 * 3))
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .sign(key, hashes.SHA256(), backend=default_backend())
    )

    # Random password for the PFX
    password = base64.b64encode(os.urandom(24)).decode()

    # PKCS12 / PFX — the format Connect-IPPSSession needs on Linux
    from cryptography.hazmat.primitives.serialization import pkcs12
    pfx_bytes = pkcs12.serialize_key_and_certificates(
        name=f"M365 Mail Purger - {org_name}".encode(),
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode())
    )

    # Public cert in DER format (for Azure upload)
    cer_bytes = cert.public_bytes(serialization.Encoding.DER)

    # SHA-1 thumbprint
    thumbprint = cert.fingerprint(hashes.SHA1()).hex()

    return {
        "pfx_bytes": pfx_bytes,
        "cer_bytes": cer_bytes,
        "password": password,
        "thumbprint": thumbprint,
    }
