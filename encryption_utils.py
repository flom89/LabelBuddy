import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

# Lädt die MASTER_KEY Variable aus deiner .env Datei
load_dotenv()

# Den Key aus der Umgebung laden
SECRET_KEY = os.getenv("MASTER_KEY")

if not SECRET_KEY:
    # Falls du noch keinen Key hast, generieren wir hier eine Fehlermeldung
    # Du musst MASTER_KEY in deiner .env Datei setzen!
    raise ValueError("MASTER_KEY nicht in .env Datei gefunden!")

cipher_suite = Fernet(SECRET_KEY.encode())

def encrypt_key(plain_text: str) -> str:
    """Verschlüsselt einen String (z.B. API-Token)."""
    if not plain_text:
        return ""
    encrypted_text = cipher_suite.encrypt(plain_text.encode())
    return encrypted_text.decode()

def decrypt_key(encrypted_text: str) -> str:
    """Entschlüsselt einen verschlüsselten String."""
    if not encrypted_text:
        return ""
    decrypted_text = cipher_suite.decrypt(encrypted_text.encode())
    return decrypted_text.decode()