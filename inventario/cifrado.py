"""Cifrado de los datos del panel con una contraseña.

El sitio es público: los datos reales del panel se publican cifrados y solo se leen en el navegador de quien
sabe la contraseña (panel/panel.js los descifra con Web Crypto).

    clave = PBKDF2-SHA256(contraseña, sal, ITERACIONES) → 256 bits
    datos = AES-256-GCM(clave, iv aleatorio, JSON)

La sal es fija por sitio para que «Recordar en este dispositivo» pueda guardar la clave derivada (no la
contraseña) y siga sirviendo al día siguiente. Cambiar la contraseña invalida lo recordado.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os

ITERACIONES = 600_000
SAL = hashlib.sha256(b"ciudad-nueva-chile/panel-inventario").digest()[:16]


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def derivar(contrasena: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", contrasena.encode("utf-8"), SAL, ITERACIONES, dklen=32)


def cifrar(datos: dict, contrasena: str) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    iv = os.urandom(12)
    texto = json.dumps(datos, ensure_ascii=False, default=str).encode("utf-8")
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iteraciones": ITERACIONES, "sal": _b64(SAL), "iv": _b64(iv),
            "datos": _b64(AESGCM(derivar(contrasena)).encrypt(iv, texto, None))}


def descifrar(paquete: dict, contrasena: str) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    clave = hashlib.pbkdf2_hmac("sha256", contrasena.encode("utf-8"), base64.b64decode(paquete["sal"]),
                                paquete["iteraciones"], dklen=32)
    texto = AESGCM(clave).decrypt(base64.b64decode(paquete["iv"]), base64.b64decode(paquete["datos"]), None)
    return json.loads(texto)
