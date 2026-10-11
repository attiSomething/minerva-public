"""API keys live in the operating system's credential store (Windows
Credential Manager on Windows, via the keyring package), never in config
files, the library, or the repo."""

SERVICE = "Minerva"


def _keyring():
    import keyring
    return keyring


def get_key(provider):
    try:
        return _keyring().get_password(SERVICE, provider)
    except Exception:
        return None


def has_key(provider):
    return bool(get_key(provider))


def set_key(provider, key):
    _keyring().set_password(SERVICE, provider, key)


def delete_key(provider):
    try:
        _keyring().delete_password(SERVICE, provider)
    except Exception:
        pass
