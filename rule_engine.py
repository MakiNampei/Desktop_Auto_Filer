from pathlib import Path
import json, re, os
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class Proposal:
    dest_path: Path
    why: str
    confidence: float

class RuleEngine:
    def __init__(self, rules_json_path: Path):
        cfg = json.loads(Path(rules_json_path).read_text(encoding="utf-8"))
        self.base: Dict[str, Path] = {k: Path(os.path.expanduser(v)) for k, v in cfg["base_dirs"].items()}
        self.rules = cfg["rules"]
        self.fallback = cfg.get("fallback_dir", "docs")

    def propose(self, file_path: Path) -> Proposal:
        name, ext = file_path.name, file_path.suffix.lower().lstrip(".")
        votes: Dict[str, int] = {}
        reasons: List[str] = []

        for r in self.rules:
            if "if_ext_in" in r and ext in r["if_ext_in"]:
                k = r["to"]; votes[k] = votes.get(k, 0) + 2; reasons.append(f"扩展名 {ext} → {k}")

        for r in self.rules:
            if "if_name_has_any" in r:
                hit = next((kw for kw in r["if_name_has_any"] if kw.lower() in name.lower()), None)
                if hit: k = r["to"]; votes[k] = votes.get(k, 0) + 2; reasons.append(f"含“{hit}” → {k}")

        for r in self.rules:
            if "if_name_matches_any_regex" in r:
                pat = next((p for p in r["if_name_matches_any_regex"] if re.match(p, name)), None)
                if pat: k = r["to"]; votes[k] = votes.get(k, 0) + 2; reasons.append(f"正则 {pat} → {k}")

        if not votes:
            votes[self.fallback] = 1; reasons.append(f"无命中 → {self.fallback}")

        key = max(votes, key=votes.get); total = sum(votes.values()) or 1
        return Proposal(self.base.get(key, self.base[self.fallback]), "；".join(reasons), votes[key]/total)