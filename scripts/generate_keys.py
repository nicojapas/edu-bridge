#!/usr/bin/env python3
"""
Generate RSA key pair for LTI 1.3 client assertion signing.

Usage:
    python scripts/generate_keys.py

This will:
1. Generate a 2048-bit RSA key pair
2. Save private.pem and public.pem to the scripts/ directory
3. Print the private key formatted for .env file
4. Print the public key for registering in Moodle
"""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
import os

# Generate key pair
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend()
)

# Serialize private key
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption()
)

# Serialize public key
public_pem = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
)

# Get script directory
script_dir = os.path.dirname(os.path.abspath(__file__))

# Save to files
private_path = os.path.join(script_dir, "private.pem")
public_path = os.path.join(script_dir, "public.pem")

with open(private_path, "wb") as f:
    f.write(private_pem)

with open(public_path, "wb") as f:
    f.write(public_pem)

print("=" * 60)
print("RSA Key Pair Generated")
print("=" * 60)
print(f"\nPrivate key saved to: {private_path}")
print(f"Public key saved to: {public_path}")

# Format for .env
private_str = private_pem.decode("utf-8")
env_formatted = private_str.replace("\n", "\\n")

print("\n" + "=" * 60)
print("FOR .env FILE (copy this entire line):")
print("=" * 60)
print(f'\nLTI_PRIVATE_KEY="{env_formatted}"')

print("\n" + "=" * 60)
print("PUBLIC KEY FOR MOODLE (paste in tool configuration):")
print("=" * 60)
print(f"\n{public_pem.decode('utf-8')}")
