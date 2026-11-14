import json
import re

LANGS = ("fr", "en", "es")
LANG = "en"
_DICTS = {}
_W = "A-Za-zÀ-ÿŒœ0-9"


def set_lang(lang):
    global LANG
    LANG = lang if lang in LANGS else "en"


def _load(lang):
    if lang in _DICTS:
        return _DICTS[lang]
    d = {"exact": {}, "frag": {}, "rules": {}}
    try:
        from paths import res
        with open(res("data", f"i18n_{lang}.js"), encoding="utf-8") as f:
            txt = f.read()
        d = json.loads(txt[txt.index("{"):txt.rindex("}") + 1])
    except (OSError, ValueError) as e:
        print(f"[i18n] dictionnaire {lang} illisible :", e)
    parts = []
    for k in sorted(d["frag"], key=len, reverse=True):
        p = re.escape(k)
        if re.match("[" + _W + "]", k):
            p = "(?<![" + _W + "])" + p
        if re.search("[" + _W + "]$", k):
            p += "(?![" + _W + "])"
        parts.append(p)
    d["_re"] = re.compile("|".join(parts)) if parts else None
    _DICTS[lang] = d
    return d


def _punct(s, lang):
    s = re.sub(r" ([:;!?])(?=\s|$|\)|\"|»)", r"\1", s)
    if lang == "en":
        s = re.sub(r" ?»", '"', re.sub(r"« ?", '"', s))
        return re.sub(r"(\d) %", r"\1%", s)
    return re.sub(r" »", "»", re.sub(r"« ", "«", s))


def tr(s, lang=None):
    lang = lang or LANG
    if lang == "fr" or not s:
        return s
    d = _load(lang)
    m = re.match(r"^(\s*)(.*?)(\s*)$", s, re.S)
    core = m.group(2)
    if not re.search(r"[A-Za-zÀ-ÿ]", core):
        return s
    t = d["exact"].get(core)
    if t is None:
        rules = d.get("rules") or {}
        t = d["_re"].sub(lambda x: d["frag"][x.group(0)], core) if d["_re"] else core
        t = re.sub(r"\bC([TS])(\d\d)\b",
                   lambda x: rules.get("tm" if x.group(1) == "T" else "hm", "C" + x.group(1)) + x.group(2), t)
        t = re.sub(r"\bNv(?=\d)", rules.get("lv", "Nv"), t)
        if t != core:
            t = _punct(t, lang)
    return m.group(1) + t + m.group(3)


def tr_lines(text):
    if LANG == "fr":
        return text
    return "\n".join(tr(line) for line in text.split("\n"))
