from pathlib import Path

Import("env")


PROJECT_DIR = Path(env.subst("$PROJECT_DIR"))
MARKER = "/* CrossPoint wolfSSL compatibility overrides */"
OVERRIDES = f"""

{MARKER}
#undef NO_DH
#ifndef HAVE_FFDHE_2048
#define HAVE_FFDHE_2048
#endif
#undef FP_MAX_BITS
#define FP_MAX_BITS 8192

/* The X4 Pro RSS Figaro client validates a DigiCert G3 ECC/SHA-384 chain.
 * Arduino-wolfSSL 5.7.2 does not enable SHA-384 in its compact settings.
 * SHA-384 shares the SHA-512 core in wolfSSL, so both feature macros are
 * required. Keep the unused SHA-512/224 and SHA-512/256 variants disabled. */
#ifndef WOLFSSL_SHA512
#define WOLFSSL_SHA512
#endif
#ifndef WOLFSSL_SHA384
#define WOLFSSL_SHA384
#endif
#ifndef WOLFSSL_NOSHA512_224
#define WOLFSSL_NOSHA512_224
#endif
#ifndef WOLFSSL_NOSHA512_256
#define WOLFSSL_NOSHA512_256
#endif
"""


def patch_user_settings(path: Path) -> None:
    original_text = path.read_text()
    text = original_text
    if MARKER in text:
        text = text.split(MARKER, 1)[0].rstrip()
    patched_text = text + OVERRIDES + "\n"
    if original_text == patched_text:
        return
    path.write_text(patched_text)
    print(f"Patched wolfSSL settings: {path.relative_to(PROJECT_DIR)}")


for settings in PROJECT_DIR.glob(".pio/libdeps/*/Arduino-wolfSSL/src/user_settings.h"):
    patch_user_settings(settings)
