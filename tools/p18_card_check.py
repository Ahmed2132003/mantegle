import os, sys
sys.path.insert(0, os.getcwd())
from PIL import Image
from mt.templates.t4.scenes import SLOTS, _put
from mt.templates.t4.scenes_reg import get_widget
CASES = {
  "en": {"icon": "globe", "title": "Web Technology", "subtitle": "Build \u2022 Develop \u2022 Deploy"},
  "ar": {"icon": "globe", "title": "تقنيات الويب", "subtitle": "تصميم • تطوير • نشر"},
  "long": {"icon": "globe", "title": "Full Stack Web Development And Cloud Deployment Services For Growing Businesses", "subtitle": "Build \u2022 Develop \u2022 Deploy"},
  "nosub": {"icon": "globe", "title": "Web Technology", "subtitle": ""},
}
os.makedirs("out/t4", exist_ok=True)
for tag, spec in CASES.items():
    for name, (W, H) in {"reels": (1080, 1920), "youtube": (1920, 1080)}.items():
        s, asp = min(W, H) / 1080.0, ("portrait" if H > W else "landscape")
        ctx = {"W": W, "H": H, "s": s, "aspect": asp, "preset": "web_dev", "cfg": {}}
        bg = Image.new("RGBA", (W, H), (12, 22, 48, 255))
        for t, slot, ws in (("title_block", "title", {}), ("code_window", "code", {}), ("ring", "ring", {"icon": "globe"}), ("bullet_list", "bullets", {}), ("info_card", "card", spec)):
            box = tuple(v * s for v in SLOTS["web_dev"][asp][slot])
            sp = get_widget(t)(dict(ws, type=t), box, ctx)
            pl = _put(sp, box, W, H, s)
            x, y = int(round(pl[0] - sp.width / 2.0)), int(round(pl[1] - sp.height / 2.0))
            bg.alpha_composite(sp, (x, y))
            for ls, lx, ly in sp.info.get("lines") or []:
                bg.alpha_composite(ls, (x + lx, y + ly))
            print(tag, name, t, "ink", [round(v) for v in pl[2]], "moved", pl[3])
        bg.convert("RGB").save("out/t4/p18_card_%s_%s.png" % (tag, name))
