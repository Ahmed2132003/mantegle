"""mt.templates.t4.base - Template 4: the BASE video's backdrop (what shows around a 'fit' video): solid colour, image, or a blurred
copy of the video itself. Fill mode needs no backdrop (the video covers the canvas), so image / blur are only built for fit."""
import os

from PIL import Image, ImageFilter

from mt.templates.t4.warn import t4_warn

BLUR_DIV = 8                       # the blur is made at 1/8 size (fast, smooth) and scaled back up
_BLACK = {"type": "color", "value": "#000000"}


def t4_blur_params(strength, W, H):
    """strength 1..10 -> {W, H, sw, sh, lr}: lr = box-blur radius at the 1/8 size (clamped so ffmpeg's chroma limit is never hit)."""
    sw, sh = max(4, int(round(W / float(BLUR_DIV)))), max(4, int(round(H / float(BLUR_DIV))))
    try:
        s = max(1, min(10, int(strength)))
    except (TypeError, ValueError):
        s = 5
    return {"W": int(W), "H": int(H), "sw": sw, "sh": sh, "lr": max(1, min(int(round(s * 1.2)), min(sw, sh) // 4 - 1))}


def t4_blur_filter(p):
    """ffmpeg filter chain turning the source copy [rb] into the blurred backdrop: cover-scale+crop at 1/8 size, boxblur, scale up."""
    return (f"scale={p['sw']}:{p['sh']}:force_original_aspect_ratio=increase,crop={p['sw']}:{p['sh']},"
            f"boxblur={p['lr']}:2,scale={p['W']}:{p['H']}:flags=bicubic,setsar=1,format=yuv420p")


def t4_blur_still(frame, W, H, p):
    """PIL twin of t4_blur_filter for --still: blurred cover copy of `frame` (RGB) at W x H, RGBA."""
    s = max(W / float(frame.width), H / float(frame.height))
    fr = frame.convert("RGB").resize((max(W, int(round(frame.width * s))), max(H, int(round(frame.height * s)))), Image.BILINEAR)
    l, t = (fr.width - W) // 2, (fr.height - H) // 2
    small = fr.crop((l, t, l + W, t + H)).resize((p["sw"], p["sh"]), Image.LANCZOS)
    small = small.filter(ImageFilter.BoxBlur(p["lr"])).filter(ImageFilter.BoxBlur(p["lr"]))
    return small.resize((W, H), Image.BICUBIC).convert("RGBA")


def _image_ok(path):
    try:
        if path and os.path.isfile(str(path)):
            with Image.open(str(path)) as im:
                im.verify()
            return True
    except Exception:
        pass
    return False


def t4_apply_backdrop(cfg, t4):
    """Set cfg['background'] (+ cfg['_t4_blur'] for the blur type) from the normalised t4 dict. Never raises: a missing / broken
    image falls back to the solid colour with one t4_warn line."""
    bd, W, H = t4["backdrop"], cfg["canvas"][0], cfg["canvas"][1]
    cfg.pop("_t4_blur", None)
    cfg["background"] = {"type": "color", "value": bd["value"]}
    if t4["fit"] != "fit":
        return
    if bd["type"] == "image":
        if _image_ok(bd["path"]):
            cfg["background"] = {"type": "image", "path": str(bd["path"])}
        else:
            t4_warn(f"backdrop image '{os.path.basename(str(bd['path'])) or '(none)'}' not found or unreadable - using the solid colour")
    elif bd["type"] == "blur":
        cfg["_t4_blur"] = t4_blur_params(bd["strength"], W, H)
