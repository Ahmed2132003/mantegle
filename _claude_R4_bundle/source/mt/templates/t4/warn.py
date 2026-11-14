"""mt.templates.t4.warn - Template 4: one-line [!] messages, printed once per render (items are rebuilt per frame / segment)."""
_MSGS = set()


def t4_warn_reset():
    _MSGS.clear()


def t4_warn(msg):
    """Print '   [!] msg' once per render; never raises."""
    msg = "   [!] " + str(msg).strip()
    if msg not in _MSGS:
        _MSGS.add(msg)
        print(msg)
