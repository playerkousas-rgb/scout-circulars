#!/usr/bin/env python3
"""Generate a VAPID key pair for the anonymous Web Push setup.

Run after ``pip install -r requirements.txt``. The private PEM printed here is
secret: put it in the GitHub Actions secret VAPID_PRIVATE_KEY only, never in a
browser, Vercel public environment variable, commit, or issue/comment.
"""

import base64

try:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from py_vapid import Vapid
except ImportError as exc:
    raise SystemExit("Install dependencies first: pip install -r requirements.txt") from exc

vapid = Vapid()
vapid.generate_keys()
public_bytes = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
public_key = base64.urlsafe_b64encode(public_bytes).decode("ascii").rstrip("=")
private_pem = vapid.private_pem().decode("ascii").strip()

print("VAPID_PUBLIC_KEY=" + public_key)
print("\nVAPID_PRIVATE_KEY (store as one GitHub Actions secret, including all PEM lines):")
print(private_pem)
