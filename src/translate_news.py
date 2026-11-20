"""English headlines for the Regional News section.

After the headlines are fetched (site/news.json), every story of the section named in external_config/translation.json gets a
"title_en" - its headline translated into English by an open-source model (IndicTrans2, free, runs on the GitHub runner).
A headline is translated once: translations are carried over from the previous news.json (same link, same title).
Stories that cannot be translated (not in an Indian script, or the time budget ran out) keep no title_en and show their own
headline; the next refresh continues with them.

    python3 src/translate_news.py plan   - carry over known translations, print how many are still to do (pending=N)
    python3 src/translate_news.py run    - translate the pending ones (needs torch, transformers, IndicTransToolkit)
"""
import json
import os
import sys
import time
import unicodedata
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parent.parent
NEWS = ROOT / "site" / "news.json"

# Unicode script -> the model's language code (a newspaper_language entry in translation.json overrides it, e.g. Marathi, Assamese)
SCRIPTS = {"DEVANAGARI": "hin_Deva", "BENGALI": "ben_Beng", "GUJARATI": "guj_Gujr", "GURMUKHI": "pan_Guru", "ORIYA": "ory_Orya",
           "TAMIL": "tam_Taml", "TELUGU": "tel_Telu", "KANNADA": "kan_Knda", "MALAYALAM": "mal_Mlym", "ARABIC": "urd_Arab"}


def settings():
    path = Path(config.config_dir()) / "translation.json"
    d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"section": d.get("section", "regional"), "model": d.get("model", "ai4bharat/indictrans2-indic-en-dist-200M"),
            "budget_minutes": float(d.get("budget_minutes", 30)), "max_new_per_run": int(d.get("max_new_per_run", 3000)),
            "newspaper_language": d.get("newspaper_language") or {}}


def script_of(text):
    """The Indian script most letters of the text are written in (None for Latin or mixed-in-English headlines)."""
    count = {}
    for ch in text:
        if ch.isalpha():
            name = unicodedata.name(ch, "").split(" ")[0]
            count[name] = count.get(name, 0) + 1
    if not count:
        return None
    top = max(count, key=count.get)
    return top if top in SCRIPTS and count[top] >= 0.4 * sum(count.values()) else None


def language_of(item, newspaper_language):
    """The model's source-language code for a story, or None when it should not be translated."""
    script = script_of(item.get("title", ""))
    if not script:
        return None
    forced = newspaper_language.get(item.get("newspaper") or item.get("source"))
    if forced and SCRIPTS[script] in ("hin_Deva", "ben_Beng") and forced[-4:] == SCRIPTS[script][-4:]:
        return forced                                           # Marathi uses Devanagari, Assamese the Bengali script
    return SCRIPTS[script]


def members(news, cfg):
    return [i for i in news.get("items", []) if cfg["section"] in i.get("sections", ())]


def carry_over(news, previous, cfg):
    """Copies title_en from the previous news.json for stories whose link and headline are unchanged. Returns the pending stories."""
    known = {}
    for i in (previous or {}).get("items", []):
        if i.get("title_en") and i.get("link"):
            known[i["link"]] = (i.get("title", ""), i["title_en"])
    pending = []
    for i in members(news, cfg):
        got = known.get(i.get("link"))
        if got and got[0] == i.get("title"):
            i["title_en"] = got[1]
        elif language_of(i, cfg["newspaper_language"]):
            pending.append(i)
    pending.sort(key=lambda i: i.get("published", ""), reverse=True)            # newest first
    return pending


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(news):
    tmp = NEWS.with_suffix(".tmp")
    tmp.write_text(json.dumps(news, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(NEWS)


class Translator:
    """IndicTrans2 (Indic -> English), loaded once. Heavy imports stay here so the planning step needs nothing installed."""

    def __init__(self, model_name):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        from IndicTransToolkit.processor import IndicProcessor
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name, trust_remote_code=True).eval()
        self.proc = IndicProcessor(inference=True)
        torch.set_num_threads(os.cpu_count() or 2)

    def translate(self, sentences, src):
        batch = self.proc.preprocess_batch(sentences, src_lang=src, tgt_lang="eng_Latn")
        enc = self.tok(batch, truncation=True, padding="longest", max_length=128, return_tensors="pt", return_attention_mask=True)
        with self.torch.no_grad():
            out = self.model.generate(**enc, use_cache=True, min_length=0, max_length=128, num_beams=3, num_return_sequences=1)
        text = self.tok.batch_decode(out, skip_special_tokens=True, clean_up_tokenization_spaces=True)
        return self.proc.postprocess_batch(text, lang="eng_Latn")


def run(news, pending, cfg, translator=None, batch_size=16, clock=time.monotonic):
    """Translates pending stories (newest first, grouped by language) until done, the budget or the per-run limit. Returns the count."""
    started, done = clock(), 0
    pending = pending[:cfg["max_new_per_run"]]
    by_lang = {}
    for i in pending:
        by_lang.setdefault(language_of(i, cfg["newspaper_language"]), []).append(i)
    translator = translator or Translator(cfg["model"])
    rounds = max(len(v) for v in by_lang.values()) if by_lang else 0
    for r in range(0, rounds, batch_size):                      # round-robin over languages so every language gets its newest stories first
        for lang, stories in by_lang.items():
            chunk = stories[r:r + batch_size]
            if not chunk:
                continue
            if clock() - started > cfg["budget_minutes"] * 60:
                return done
            try:
                out = translator.translate([i["title"] for i in chunk], lang)
            except Exception as e:                              # one bad batch must not lose the others
                print(f"Translation batch skipped ({lang}): {type(e).__name__}: {e}")
                continue
            for i, en in zip(chunk, out):
                en = (en or "").strip()
                if en and en != i["title"]:
                    i["title_en"] = en
                    done += 1
        save(news)
    return done


def main(argv):
    mode = argv[1] if len(argv) > 1 else "plan"
    cfg = settings()
    news = load(NEWS)
    if not news:
        print("No site/news.json: nothing to translate.")
        return 0
    pending = carry_over(news, load(os.environ.get("PREVIOUS_NEWS_FILE", "")) if os.environ.get("PREVIOUS_NEWS_FILE") else None, cfg)
    have = sum(1 for i in members(news, cfg) if i.get("title_en"))
    if mode == "plan":
        save(news)
        print(f"English headlines: {have} carried over, {len(pending)} to translate")
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as f:
                f.write(f"pending={len(pending)}\n")
        return 0
    started = time.monotonic()
    done = run(news, pending, cfg)
    save(news)
    print(f"Translated {done} of {len(pending)} pending headlines in {time.monotonic() - started:.0f}s; {have + done} stories now have English.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
