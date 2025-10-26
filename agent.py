import os
import re
import time
import json
import logging
from typing import Dict, Any, Optional, List
from collections import defaultdict

from uagents import Agent, Context, Model

# ========= Logging =========
LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", "."), "DeskPilot")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# ========= Files / constants =========
HERE = os.path.dirname(__file__)
DEFAULT_FALLBACK = os.path.join(os.environ["USERPROFILE"], "Desktop", "_Unsorted")
RULES_FILE = os.path.join(HERE, "rules.json")
WHITELIST_FILE = os.path.join(HERE, "whitelist.json")
PID_FILE = os.path.join(HERE, "agent.pid")

try:
    with open(PID_FILE, "w", encoding="utf-8") as _pf:
        _pf.write(str(os.getpid()))
except Exception:
    pass

# ========= Models =========
class FileEvent(Model):
    path: str
    name: str
    ext: str

class Suggestion(Model):
    suggestion_id: str
    folder: str
    confidence: float
    rationale: str
    needs_whitelist: bool = False

class Feedback(Model):
    suggestion_id: str
    accepted: bool
    chosen_folder: Optional[str] = None
    reason: Optional[str] = None

class Ack(Model):
    status: str
    new_confidence: Optional[float] = None

class Health(Model):
    status: str

class Status(Model):
    learned: Dict[str, Any]
    whitelist_count: int
    embeddings: bool

class WhitelistEntry(Model):
    path: str
    description: str

class RemoveEntry(Model):
    path: str

class WhitelistList(Model):
    items: List[Dict[str, str]]
    count: int

# ========= Text helpers =========
_STOP = {"the", "a", "an", "of", "to", "and", "for", "in", "on", "by", "img", "screen", "shot"}

def tokenize(name: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9]+", name.lower())
    return [t for t in tokens if t not in _STOP]

def expand_env(path: str) -> str:
    return os.path.abspath(os.path.expandvars(os.path.expanduser(path)))

# ========= Rules bootstrap (cold start) =========
def load_seed_rules() -> Dict[str, Any]:
    rules_map = {"ext": {}, "token": {}, "recent": {}}
    if not os.path.exists(RULES_FILE):
        return rules_map
    try:
        with open(RULES_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        base_dirs = {k.lower(): expand_env(v) for k, v in cfg.get("base_dirs", {}).items()}
        for d in base_dirs.values():
            os.makedirs(d, exist_ok=True)
        for r in cfg.get("rules", []):
            dest_key = (r.get("to") or "").lower()
            if dest_key not in base_dirs:
                continue
            dest = base_dirs[dest_key]
            if "if_ext_in" in r:
                for ext in r["if_ext_in"]:
                    e = ext.lower().lstrip(".")
                    rules_map["ext"].setdefault(e, {})
                    rules_map["ext"][e][dest] = rules_map["ext"][e].get(dest, 0.0) + 0.5
            if "if_name_has_any" in r:
                for tok in r["if_name_has_any"]:
                    t = tok.lower()
                    rules_map["token"].setdefault(t, {})
                    rules_map["token"][t][dest] = rules_map["token"][t].get(dest, 0.0) + 0.5
        logging.info("Seed rules loaded from rules.json")
    except Exception as e:
        logging.warning(f"Failed to load seed rules: {e}")
    return rules_map

# ===== Content peek config =====
CONTENT_PEEK_EXTS = {".txt", ".docx"}
MAX_PEEK_BYTES = 64 * 1024      # txt: read up to 64 KB max
MAX_PEEK_CHARS = 2000           # cap text added to query
MAX_PEEK_PARAS = 10             # docx: first N paragraphs
MAX_PEEK_SECONDS = 1.0          # bail if slow

def _decode_best_effort(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(enc, errors="ignore")
        except Exception:
            continue
    return ""

def _peek_file_text(path: str, ext: str) -> Optional[str]:
    import time as _t
    start = _t.perf_counter()
    try:
        if ext == ".txt":
            with open(path, "rb") as f:
                blob = f.read(MAX_PEEK_BYTES)
            text = _decode_best_effort(blob)
            return (text[:MAX_PEEK_CHARS] if len(text) > MAX_PEEK_CHARS else text)
        elif ext == ".docx":
            try:
                from docx import Document  # python-docx
            except Exception:
                # No dependency installed—quietly skip peeking
                return None
            doc = Document(path)
            paras = []
            for p in doc.paragraphs[:MAX_PEEK_PARAS]:
                paras.append(p.text)
                if _t.perf_counter() - start > MAX_PEEK_SECONDS:
                    break
            text = "\n".join(paras)
            return (text[:MAX_PEEK_CHARS] if len(text) > MAX_PEEK_CHARS else text)
    except Exception:
        return None
    finally:
        # hard stop if taking too long
        if (time.perf_counter() - start) > MAX_PEEK_SECONDS:
            return None


# ========= Whitelist storage (JSON only; keep ctx.storage simple) =========
def load_whitelist(ctx: Context) -> List[Dict[str, str]]:
    wl = ctx.storage.get("whitelist")
    if wl is None:
        if os.path.exists(WHITELIST_FILE):
            try:
                with open(WHITELIST_FILE, "r", encoding="utf-8") as f:
                    wl = json.load(f)
            except Exception:
                wl = []
        else:
            wl = []
        ctx.storage.set("whitelist", wl)
    return wl

def save_whitelist(ctx: Context, wl: List[Dict[str, str]]):
    ctx.storage.set("whitelist", wl)
    try:
        with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
            json.dump(wl, f, indent=2)
    except Exception as e:
        logging.warning(f"Failed to write whitelist.json: {e}")
    ctx.storage.set("wl_dirty", True)

# ========= Embeddings (module-level only; NEVER in ctx.storage) =========
EMBEDDER = None            # SentenceTransformer instance
EMB_AVAILABLE = None       # bool | None (cache)
WL_INDEX = None            # {"paths": [...], "texts": [...], "vecs": [...], "sig": tuple}

def _load_embedder() -> bool:
    global EMBEDDER, EMB_AVAILABLE
    if EMB_AVAILABLE is not None:
        return EMB_AVAILABLE
    try:
        from sentence_transformers import SentenceTransformer
        EMBEDDER = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        EMB_AVAILABLE = True
        logging.info("Embeddings enabled (all-MiniLM-L6-v2).")
    except Exception as e:
        EMBEDDER = None
        EMB_AVAILABLE = False
        logging.warning(f"Embeddings unavailable: {e}")
    return EMB_AVAILABLE

def _ensure_wl_index(ctx: Context) -> bool:
    global WL_INDEX
    if not _load_embedder():
        return False
    wl = load_whitelist(ctx)
    sig = tuple((expand_env(it["path"]), (it.get("description") or "")) for it in wl)
    if WL_INDEX and WL_INDEX.get("sig") == sig:
        return True
    if not wl:
        WL_INDEX = None
        return False
    paths, texts = [], []
    for it in wl:
        p = expand_env(it["path"])
        if not os.path.isdir(p):
            continue
        desc = (it.get("description") or "").strip()
        folder_name = os.path.basename(p)
        texts.append(f"{folder_name}. {desc}")
        paths.append(p)
    if not paths:
        WL_INDEX = None
        return False
    try:
        vecs = EMBEDDER.encode(texts, normalize_embeddings=True).tolist()
        WL_INDEX = {"paths": paths, "texts": texts, "vecs": vecs, "sig": sig}
        ctx.storage.set("wl_dirty", False)
        logging.info(f"Built whitelist embedding index ({len(paths)} folders).")
        return True
    except Exception as e:
        logging.warning(f"Failed to encode whitelist: {e}")
        WL_INDEX = None
        return False

def _embed_query(file_name: str, ext: str, tokens: List[str], content: Optional[str] = None) -> Optional[List[float]]:
    if not _load_embedder() or EMBEDDER is None:
        return None
    # Build a compact, informative prompt for the semantic encoder
    parts = [
        f"File: {file_name}",
        f"Type: {ext}",
        "Keywords: " + " ".join(tokens[:12]) if tokens else ""
    ]
    if content:
        # Include a small slice of content to boost semantics
        snippet = content.replace("\n", " ")[:MAX_PEEK_CHARS]
        parts.append(f"Content: {snippet}")
    query = ". ".join([p for p in parts if p])
    try:
        return EMBEDDER.encode([query], normalize_embeddings=True)[0].tolist()
    except Exception:
        return None

# ========= Memory purge helpers =========
def _purge_paths_from_rules(rules: Dict[str, Any], rm_paths_lower: List[str]):
    # ext
    for ext, dests in list(rules.get("ext", {}).items()):
        for p in rm_paths_lower:
            dests.pop(p, None)
        if not dests:
            rules["ext"].pop(ext, None)
    # token
    for tok, dests in list(rules.get("token", {}).items()):
        for p in rm_paths_lower:
            dests.pop(p, None)
        if not dests:
            rules["token"].pop(tok, None)
    # recent
    for sig, (folder, _w) in list(rules.get("recent", {}).items()):
        if folder.lower() in rm_paths_lower:
            rules["recent"].pop(sig, None)

# ========= Agent =========
agent = Agent(
    name="deskpilot",
    seed="deskpilot windows seed",
    port=8000,
    endpoint=["http://127.0.0.1:8000/submit"],
)

# ========= REST =========
@agent.on_rest_get("/health", Health)
async def health(ctx: Context) -> Dict[str, Any]:
    # Return immediately; embeddings/whitelist index will be built lazily on /suggest
    return {"status": "up"}


@agent.on_rest_get("/status", Status)
async def status(ctx: Context) -> Dict[str, Any]:
    rules = ctx.storage.get("rules") or {"ext": {}, "token": {}, "recent": {}}
    wl = load_whitelist(ctx)

    def topk(d, k=3):
        out = {}
        for key, sub in d.items():
            out[key] = sorted(((v, f) for f, v in sub.items()), reverse=True)[:k]
        return out

    return {
        "learned": {"ext": topk(rules["ext"]), "token": topk(rules["token"])},
        "whitelist_count": len(wl),
        "embeddings": bool(EMB_AVAILABLE),
    }

@agent.on_rest_get("/whitelist", WhitelistList)
async def get_wl(ctx: Context) -> Dict[str, Any]:
    wl = load_whitelist(ctx)
    return {"items": wl, "count": len(wl)}

@agent.on_rest_post("/whitelist/add", WhitelistEntry, Ack)
async def add_wl(ctx: Context, item: WhitelistEntry) -> Ack:
    wl = load_whitelist(ctx)
    p = expand_env(item.path)
    if not os.path.isdir(p):
        return Ack(status="not_a_folder")
    wl = [x for x in wl if expand_env(x["path"]).lower() != p.lower()]
    wl.append({"path": p, "description": item.description})
    save_whitelist(ctx, wl)
    logging.info(f"Whitelist add: {p} ({item.description[:80]})")
    return Ack(status="ok")

@agent.on_rest_post("/whitelist/remove", RemoveEntry, Ack)
async def remove_wl(ctx: Context, rem: RemoveEntry) -> Ack:
    wl = load_whitelist(ctx)
    p = expand_env(rem.path).lower()
    new = [x for x in wl if expand_env(x["path"]).lower() != p]
    if len(new) == len(wl):
        return Ack(status="not_found")
    save_whitelist(ctx, new)
    # purge learned memory for that folder
    rules = ctx.storage.get("rules") or {"ext": {}, "token": {}, "recent": {}}
    _purge_paths_from_rules(rules, [p])
    ctx.storage.set("rules", rules)
    # drop index
    global WL_INDEX
    WL_INDEX = None
    logging.info(f"Whitelist remove + memory purge: {rem.path}")
    return Ack(status="ok")

@agent.on_rest_post("/whitelist/clear", Model, Ack)
async def clear_wl(ctx: Context, _payload: Model) -> Ack:
    """Clear all whitelist entries and purge ALL related memory."""
    wl = load_whitelist(ctx)
    rm_paths = [expand_env(i["path"]).lower() for i in wl]
    save_whitelist(ctx, [])  # clear
    rules = ctx.storage.get("rules") or {"ext": {}, "token": {}, "recent": {}}
    _purge_paths_from_rules(rules, rm_paths)
    ctx.storage.set("rules", rules)
    global WL_INDEX
    WL_INDEX = None
    logging.info("Whitelist cleared; related memory purged.")
    return Ack(status="ok")

@agent.on_rest_post("/whitelist/reindex", Model, Ack)
async def reindex_wl(ctx: Context, _payload: Model) -> Ack:
    """Rebuild embeddings index for current whitelist."""
    global WL_INDEX
    WL_INDEX = None
    ok = _ensure_wl_index(ctx)
    return Ack(status="ok" if ok else "no_index")

# ========= Suggestion core =========
def _suggest_impl(ctx: Context, req: FileEvent) -> Suggestion:
    # --- bootstrap rules once ---
    rules = ctx.storage.get("rules")
    if rules is None:
        rules = load_seed_rules()
        ctx.storage.set("rules", rules)

    # --- whitelist & allowed destinations ---
    wl = load_whitelist(ctx)
    allowed = [expand_env(i["path"]) for i in wl if os.path.isdir(expand_env(i["path"]))]

    # --- rule-based scoring from filename ---
    folder_scores: Dict[str, float] = defaultdict(float)
    ext = req.ext.lower().lstrip(".")
    if ext in rules["ext"]:
        for f, w in rules["ext"][ext].items():
            folder_scores[f] += 0.35 * w

    toks = tokenize(req.name)
    for t in toks:
        if t in rules["token"]:
            for f, w in rules["token"][t].items():
                folder_scores[f] += 0.45 * w

    sig = f"{ext}:{'|'.join(toks[:3])}"
    if sig in (rules.get("recent") or {}):
        f_recent, w_recent = rules["recent"][sig]
        folder_scores[f_recent] += 0.20 * w_recent

    # --- filename too weak? conditionally peek into .txt/.docx content ---
    initial_best = max(folder_scores.values()) if folder_scores else 0.0
    should_consider_peek = (
        ((("." + ext) in CONTENT_PEEK_EXTS) or (ext in {"txt", "docx"}))
        and (initial_best < 0.35)
    )

    peek_text: Optional[str] = None
    if should_consider_peek and os.path.isfile(req.path):
        peek_text = _peek_file_text(req.path, "." + ext if not ext.startswith(".") else ext)
        if peek_text:
            # blend some content tokens into rule signals (lower weight than filename tokens)
            content_tokens = tokenize(peek_text)
            for t in content_tokens[:20]:
                if t in rules["token"]:
                    for f, w in rules["token"][t].items():
                        folder_scores[f] += 0.20 * w  # gentle nudge from content

    # --- semantic scoring over whitelist (if embeddings available) ---
    emb_used = False
    if allowed and _ensure_wl_index(ctx):
        qv = _embed_query(req.name, ext, toks, content=peek_text)
        idx = WL_INDEX
        if qv is not None and idx and idx.get("vecs"):
            emb_used = True
            for vec, path in zip(idx["vecs"], idx["paths"]):
                if path not in allowed:
                    continue
                # cosine similarity
                num = sum(x * y for x, y in zip(qv, vec))
                da = (sum(x * x for x in qv)) ** 0.5
                db = (sum(x * x for x in vec)) ** 0.5
                sim = num / (da * db + 1e-9)
                folder_scores[path] += 0.60 * max(0.0, float(sim))

    # --- whitelist handling & fallback ---
    needs_wl = False
    if allowed:
        # keep only whitelist folders
        folder_scores = {f: s for f, s in folder_scores.items() if f in allowed}
        if not folder_scores:
            # no signal at all → pick first allowed as safe fallback
            fallback = allowed[0]
            sug_id = f"sg_{int(time.time() * 1000)}"
            last = ctx.storage.get("last") or {}
            last[sug_id] = {"sig": sig, "top": fallback, "tokens": toks, "ext": ext}
            ctx.storage.set("last", last)
            return Suggestion(
                suggestion_id=sug_id,
                folder=fallback,
                confidence=0.55,
                rationale="whitelist fallback (no rule/semantic signal)",
                needs_whitelist=False,
            )
    else:
        needs_wl = True
        folder_scores = {DEFAULT_FALLBACK: 0.1}

    # --- choose winner & build rationale ---
    top_folder = max(folder_scores, key=folder_scores.get)
    scores_sorted = sorted(folder_scores.values(), reverse=True)
    gap = scores_sorted[0] - (scores_sorted[1] if len(scores_sorted) > 1 else 0.0)
    conf = max(0.50, min(0.99, 0.58 + gap / 5.0))

    parts: List[str] = []
    if peek_text:
        parts.append("content peek used")
    if emb_used and WL_INDEX and top_folder in WL_INDEX["paths"]:
        i = WL_INDEX["paths"].index(top_folder)
        text = WL_INDEX["texts"][i]
        trimmed = (text[:220] + "…") if len(text) > 220 else text
        parts.append(f"semantic match to whitelist: “{trimmed}”")
    if ext in rules["ext"]:
        parts.append(f"extension .{ext} seen before")
    matched_toks = [t for t in toks if t in rules["token"]]
    if matched_toks:
        parts.append("keywords matched: " + ", ".join(matched_toks[:4]))
    if sig in (rules.get("recent") or {}):
        parts.append("recent similar files")
    if needs_wl:
        parts.append("NO_WHITELIST_CONFIGURED")
    rationale = " | ".join(parts) if parts else "fallback"

    # --- stash for feedback & return ---
    sug_id = f"sg_{int(time.time() * 1000)}"
    last = ctx.storage.get("last") or {}
    last[sug_id] = {"sig": sig, "top": top_folder, "tokens": toks, "ext": ext}
    ctx.storage.set("last", last)

    logging.info(
        f"/suggest {req.name} -> {top_folder} conf={conf:.2f} emb={'on' if emb_used else 'off'} peek={'yes' if peek_text else 'no'}"
    )
    return Suggestion(
        suggestion_id=sug_id,
        folder=top_folder,
        confidence=conf,
        rationale=rationale,
        needs_whitelist=needs_wl,
    )


@agent.on_rest_post("/suggest", FileEvent, Suggestion)
async def suggest(ctx: Context, req: FileEvent) -> Suggestion:
    # Safety net: never 500. Return a fallback and log the error.
    try:
        return _suggest_impl(ctx, req)
    except Exception as e:
        logging.exception("Suggest failed; returning safe fallback")
        wl = load_whitelist(ctx)
        allowed = [expand_env(i["path"]) for i in wl if os.path.isdir(expand_env(i["path"]))]
        fallback = allowed[0] if allowed else DEFAULT_FALLBACK
        sug_id = f"sg_{int(time.time()*1000)}"
        last = ctx.storage.get("last") or {}
        last[sug_id] = {"sig": "", "top": fallback, "tokens": [], "ext": ""}
        ctx.storage.set("last", last)
        return Suggestion(
            suggestion_id=sug_id,
            folder=fallback,
            confidence=0.51,
            rationale=f"fallback after internal error: {type(e).__name__}",
            needs_whitelist=not bool(allowed),
        )

@agent.on_rest_post("/feedback", Feedback, Ack)
async def feedback(ctx: Context, fb: Feedback) -> Ack:
    rules = ctx.storage.get("rules") or {"ext": {}, "token": {}, "recent": {}}
    last = ctx.storage.get("last") or {}
    info = last.get(fb.suggestion_id)
    if info is None:
        return Ack(status="unknown_suggestion")

    top = info["top"]; ext = info["ext"]; toks = info["tokens"]; sig = info["sig"]

    def bump(mapping, key, folder, delta):
        bucket = mapping.setdefault(key, {})
        bucket[folder] = max(0.0, bucket.get(folder, 0.0) + delta)

    if fb.accepted:
        bump(rules["ext"], ext, top, 0.35)
        for t in toks[:3]:
            bump(rules["token"], t, top, 0.35)
        rules["recent"][sig] = (top, min(1.0, (rules["recent"].get(sig, (top, 0.0))[1] + 0.3)))
        new_conf = 0.95
        logging.info(f"/feedback accepted {fb.suggestion_id} -> {top}")
    else:
        correct = fb.chosen_folder or top
        bump(rules["ext"], ext, top, -0.25)
        bump(rules["ext"], ext, correct, 0.35)
        for t in toks[:3]:
            bump(rules["token"], t, correct, 0.35)
        rules["recent"][sig] = (correct, min(1.0, (rules["recent"].get(sig, (correct, 0.0))[1] + 0.3)))
        new_conf = 0.91
        logging.info(f"/feedback corrected {fb.suggestion_id} -> {correct}")

    ctx.storage.set("rules", rules)
    return Ack(status="ok", new_confidence=new_conf)

if __name__ == "__main__":
    agent.run()
