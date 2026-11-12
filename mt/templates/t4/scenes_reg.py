"""mt.templates.t4.scenes_reg - Template 4 'scenes': the widget registry (no drawing, no scene logic).
A widget is a function  fn(spec, box, ctx) -> RGBA sprite | None  where
    spec  the widget's dict from the scene (type, slot, box, + the widget's own keys)
    box   (x, y, w, h) in canvas px = the slot (already scaled: slots are authored at short side 1080)
    ctx   {'W', 'H', 's' (short side / 1080), 'aspect' 'portrait'|'landscape', 'preset', 'cfg'}
The sprite must carry sprite.info['origin'] = (ox, oy): where the BOX's top-left sits inside the sprite (glow margin = origin > 0).
The engine (scenes.py) puts that point on the box's top-left, keeps the visible ink inside the 48 px safe area and builds the Item.
Public: WIDGETS, WIDGET_ASK, WIDGET_SLOT, register_widget(name, fn, ask=None, slot=None), get_widget(name).
  ask  = optional question function () -> dict of widget keys (used by t4_ask_scenes); slot = the widget's default slot name."""
from mt.templates.t4.warn import t4_warn

WIDGETS = {}        # name -> fn
WIDGET_ASK = {}     # name -> ask()
WIDGET_SLOT = {}    # name -> default slot name


def register_widget(name, fn, ask=None, slot=None):
    """Add (or replace) a widget type. -> True, or False (one t4_warn) for an empty name / non-callable. Never raises."""
    key = name.strip().lower() if isinstance(name, str) else ""
    if not key or not callable(fn):
        t4_warn("scenes: register_widget(%r) needs a name and a callable - ignored." % (name,))
        return False
    WIDGETS[key] = fn
    for table, v in ((WIDGET_ASK, ask if callable(ask) else None), (WIDGET_SLOT, slot.strip().lower() if isinstance(slot, str) and slot.strip() else None)):
        if v is None:
            table.pop(key, None)
        else:
            table[key] = v
    return True


def get_widget(name):
    """-> the widget function, or None (unknown type / not a string)."""
    return WIDGETS.get(name.strip().lower()) if isinstance(name, str) else None