import os

# daleel_worker.main reads Settings at import time; the tests build their own dependencies.
for name in ("DATABASE_URL", "OIDC_ISSUER", "OIDC_JWKS_URL"):
    os.environ.setdefault(name, "unused-in-tests")
