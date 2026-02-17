"""
Credential encryption utilities
"""
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64


class CredentialEncryptor:
    """Encrypt/decrypt broker credentials"""
    
    def __init__(self, secret_key: str = None):
        """
        Initialize with a secret key from environment or provided
        """
        if secret_key is None:
            secret_key = os.getenv('SECRET_KEY', 'default-secret-key-change-me')
        
        # Derive a 32-byte key from the secret
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'finlan-salt-2026',  # Static salt (in production, use per-user salts)
            iterations=100000
        )
        
        key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
        self.cipher = Fernet(key)
    
    def encrypt(self, plaintext: str) -> str:
        """Encrypt a password or sensitive string"""
        if not plaintext:
            return ""
        encrypted_bytes = self.cipher.encrypt(plaintext.encode())
        return base64.urlsafe_b64encode(encrypted_bytes).decode()
    
    def decrypt(self, encrypted: str) -> str:
        """Decrypt an encrypted password"""
        if not encrypted:
            return ""
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted.encode())
            decrypted_bytes = self.cipher.decrypt(encrypted_bytes)
            return decrypted_bytes.decode()
        except Exception:
            return ""
