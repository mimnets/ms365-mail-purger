"""Certificate generation and encryption utilities for M365 Mail Purger."""

import os
import base64
import tempfile
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from cryptography.fernet import Fernet
import datetime


def generate_certificate(org_name: str) -> dict:
    """
    Generate a self-signed X.509 certificate for Azure AD app registration.
    Returns dict with:
      - pfx_bytes:  encrypted PKCS12 bytes
      - cer_bytes:  public cert (to upload to Azure)
      - password:   the random password used to protect the PFX
      - thumbprint: SHA-1 thumbprint
    """
    # Generate RSA key pair
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    # Create self-signed cert
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

    # Generate a random password for the PFX
    password = base64.b64encode(os.urandom(24)).decode()

    # Export PFX (private key + cert, encrypted)
    pfx_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode())
    )
    # For Connect-IPPSSession, we actually need the PFX format (PKCS12)
    # Let's create a PKCS12 blob
    from cryptography.hazmat.primitives.serialization import pkcs12
    pfx_bytes = pkcs12.serialize_key_and_certificates(
        name=f"M365 Mail Purger - {org_name}".encode(),
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode())
    )

    # Export .cer (public cert only, DER format for Azure upload)
    cer_bytes = cert.public_bytes(serialization.Encoding.DER)

    # Get thumbprint
    thumbprint = cert.fingerprint(hashes.SHA1()).hex()

    return {
        "pfx_bytes": pfx_bytes,
        "cer_bytes": cer_bytes,
        "password": password,
        "thumbprint": thumbprint,
    }


def get_fernet(key: str = None) -> Fernet:
    """Get a Fernet instance. If no key, use ENCRYPTION_KEY from env."""
    if not key:
        key = os.getenv("ENCRYPTION_KEY")
        if not key:
            raise ValueError("ENCRYPTION_KEY not set and no key provided")
    # Fernet keys must be 32 base64-encoded bytes
    if len(key) < 32:
        # Derive a proper key
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"m365-mail-purger-salt",
            iterations=100000,
        )
        key_bytes = base64.urlsafe_b64encode(kdf.derive(key.encode()))
    else:
        # Use as-is if long enough
        key_bytes = key.encode() if isinstance(key, str) else key
        if len(key_bytes) < 44:
            # Pad to valid base64
            key_bytes = base64.urlsafe_b64encode(
                hashlib.sha256(key_bytes).digest()
            )

    return Fernet(key_bytes)


def encrypt_value(plain_text: str, fernet: Fernet = None) -> str:
    """Encrypt a string to a base64 blob."""
    if fernet is None:
        fernet = get_fernet()
    return fernet.encrypt(plain_text.encode()).decode()


def decrypt_value(encrypted: str, fernet: Fernet = None) -> str:
    """Decrypt a base64 blob back to string."""
    if fernet is None:
        fernet = get_fernet()
    return fernet.decrypt(encrypted.encode()).decode()


import hashlib
