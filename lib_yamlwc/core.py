"""Pure wildcard logic without WebUI dependency (testable on its own)."""
import fnmatch
import os
import re
import time

try:
    import yaml
except Exception:  # no PyYAML -> .txt only
    yaml = None

WILDCARD_RE = re.compile(r"__([^\s{}|$]+?)__")
VARIANT_RE = re.compile(r"(?<!\$)\{([^{}]*)\}")
VARUSE_RE = re.compile(r"\$\{([A-Za-z0-9_\-]+)\}")
VARDEF_RE = re.compile(r"\$\{([A-Za-z0-9_\-]+)=")
WEIGHT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)::(.*)$", re.S)
MULTI_RE = re.compile(r"^\s*(\d+)(?:-(\d+))?\$\$(?:(.*?)\$\$)?(.*)$", re.S)
EXTS = (".txt", ".yaml", ".yml")
MAX_DEPTH = 50


def parse_option(s):
    m = WEIGHT_RE.match(s)
    if m:
        return float(m.group(1)), m.group(2).strip()
    return 1.0, s.strip()


# ---------------- choice strategies ----------------
class RandomChooser:
    def __init__(self, rng):
        self.rng = rng

    def choose(self, weights, key=None):
        total = sum(w for w in weights if w > 0)
        if total <= 0:
            return self.rng.randrange(len(weights))
        r = self.rng.random() * total
        acc = 0.0
        for i, w in enumerate(weights):
            if w > 0:
                acc += w
                if r < acc:
                    return i
        return len(weights) - 1


class BagChooser(RandomChooser):
    """Draws without replacement until every option has come up once (across a whole run)."""

    def __init__(self, rng):
        super().__init__(rng)
        self.bags = {}

    def choose(self, weights, key=None):
        if key is None:
            return super().choose(weights)
        k = (key, len(weights))
        bag = self.bags.get(k)
        if not bag:
            bag = [i for i, w in enumerate(weights) if w > 0] or list(range(len(weights)))
            self.rng.shuffle(bag)
            self.bags[k] = bag
        return bag.pop()


class EnumChooser:
    """Follows a fixed path of decisions (for combinatorial mode)."""

    def __init__(self, path):
        self.path, self.taken, self.arities = path, [], []

    def choose(self, weights, key=None):
        i, n = len(self.taken), len(weights)
        idx = min(self.path[i] if i < len(self.path) else 0, n - 1)
        self.taken.append(idx)
        self.arities.append(n)
        return idx


class Track:
    def __init__(self):
        self.used, self.missing = set(), set()


# ---------------- store ----------------
class WildcardStore:
    def __init__(self, directory, interval=3.0):
        self.directory = directory
        self.interval = interval
        self._files = {}  # abs path -> (mtime, {key: [(w, text)]}, error)
        self.entries, self.key_files, self._suffix = {}, {}, {}
        self.errors = []
        self._last = 0.0

    def rel(self, path):
        return os.path.relpath(path, self.directory).replace(os.sep, "/")

    def abspath(self, rel):
        return os.path.normpath(os.path.join(self.directory, rel))

    # ---- loading ----
    def refresh(self, force=False):
        now = time.monotonic()
        if not force and self._last and now - self._last < self.interval:
            return False
        self._last = now
        if not os.path.isdir(self.directory):
            changed = bool(self._files)
            self._files = {}
            self._rebuild()
            return changed
        seen = {}
        for root, dirs, files in os.walk(self.directory):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if name.lower().endswith(EXTS):
                    path = os.path.join(root, name)
                    try:
                        seen[path] = os.path.getmtime(path)
                    except OSError:
                        pass
        changed = False
        for path, mtime in seen.items():
            old = self._files.get(path)
            if force or old is None or old[0] != mtime:
                self._files[path] = (mtime,) + self._parse(path)
                changed = True
        for path in [p for p in self._files if p not in seen]:
            del self._files[path]
            changed = True
        if changed:
            self._rebuild()
        return changed

    def _parse(self, path):
        rel = self.rel(path)
        stem, ext = os.path.splitext(rel)
        keys = {}
        try:
            with open(path, encoding="utf8", errors="replace") as f:
                raw = f.read()
            if ext.lower() == ".txt":
                lines = [l.strip() for l in raw.splitlines()]
                keys[stem.lower()] = [parse_option(l) for l in lines if l and not l.startswith("#")]
            elif yaml is None:
                return keys, "PyYAML not available"
            else:
                reldir = os.path.dirname(stem)
                self._walk_yaml(yaml.safe_load(raw), [reldir] if reldir else [], keys)
            return keys, None
        except Exception as e:
            mark = getattr(e, "problem_mark", None)
            problem = getattr(e, "problem", None)
            if mark is not None:
                return keys, f"line {mark.line + 1}, column {mark.column + 1}: {problem or str(e).splitlines()[0]}"
            return keys, str(e).splitlines()[0]

    def _walk_yaml(self, node, path, keys):
        if isinstance(node, dict):
            for k, v in node.items():
                self._walk_yaml(v, path + [str(k)], keys)
        elif isinstance(node, list):
            if path:
                keys["/".join(path).lower()] = [parse_option(str(x)) for x in node if str(x).strip()]
        elif node is not None and path:
            keys["/".join(path).lower()] = [parse_option(str(node))]

    def _rebuild(self):
        entries, key_files, suffix, errors = {}, {}, {}, []
        for path in sorted(self._files):
            _, keys, err = self._files[path]
            if err:
                errors.append(f"{self.rel(path)}: {err}")
            for k, opts in keys.items():
                entries.setdefault(k, []).extend(opts)
                key_files.setdefault(k, []).append(path)
        for k in entries:
            suffix.setdefault(k.rsplit("/", 1)[-1], []).append(k)
        self.entries, self.key_files, self._suffix, self.errors = entries, key_files, suffix, errors

    # ---- queries ----
    def lookup(self, name):
        return [(w, t, k) for k in self.keys_for(name) for (w, t) in self.entries[k]]

    def keys_for(self, name):
        name = name.lower().strip("/")
        if "*" in name:
            keys = [k for k in sorted(self.entries)
                    if fnmatch.fnmatchcase(k, name) or fnmatch.fnmatchcase(k, "*/" + name)]
        elif name in self.entries:
            keys = [name]
        else:
            last = name.rsplit("/", 1)[-1]
            keys = sorted(k for k in self._suffix.get(last, []) if k.endswith("/" + name))
        return keys

    def prompt_keys(self):
        """All non-empty wildcards whose own name starts with "prompt" (collection prompts)."""
        return sorted(k for k, opts in self.entries.items()
                      if opts and k.rsplit("/", 1)[-1].startswith("prompt"))

    def search_keys(self, query, limit=200):
        """Wildcards whose name or file contains all words of the query (case-insensitive)."""
        words = [w for w in (query or "").lower().split() if w]
        if not words:
            return []
        out = []
        for k in sorted(self.entries):
            if not self.entries[k]:
                continue
            hay = k + " " + self.rel(self.key_files[k][0]).lower()
            if all(w in hay for w in words):
                out.append(k)
                if len(out) >= limit:
                    break
        return out

    def file_count(self):
        return len(self._files)

    def files(self):
        return sorted(self.rel(p) for p in self._files)

    def folders(self):
        return sorted({os.path.dirname(r) or "." for r in self.files()})

    def keys_of_file(self, rel):
        data = self._files.get(self.abspath(rel))
        return sorted(data[1]) if data else []

    def search(self, query, in_content=False, limit=500):
        q = query.lower().strip()
        out = []
        for path in sorted(self._files):
            rel = self.rel(path)
            hit = q in rel.lower()
            if not hit and in_content:
                keys = self._files[path][1]
                hit = any(q in t.lower() for opts in keys.values() for _, t in opts)
            if hit:
                out.append(rel)
                if len(out) >= limit:
                    break
        return out

    # ---- resolving ----
    def resolve(self, text, chooser, track=None, variables=None):
        variables = {} if variables is None else variables
        for _ in range(MAX_DEPTH):
            before = text
            text = self._defs(text, chooser, track, variables)
            text = VARUSE_RE.sub(lambda m: self._var(m, variables, track), text)
            text = WILDCARD_RE.sub(lambda m: self._wc(m, chooser, track), text)
            text = VARIANT_RE.sub(lambda m: self._variant(m.group(1), chooser), text)
            if text == before:
                break
        return text

    def _defs(self, text, chooser, track, variables):
        pos = 0
        while True:
            m = VARDEF_RE.search(text, pos)
            if not m:
                return text
            i, depth = m.end(), 1
            while i < len(text) and depth:
                depth += {"{": 1, "}": -1}.get(text[i], 0)
                i += 1
            if depth:
                return text
            value = text[m.end():i - 1]
            variables[m.group(1).lower()] = self.resolve(value, chooser, track, variables)
            text = text[:m.start()] + text[i:]
            pos = m.start()

    def _var(self, m, variables, track):
        name = m.group(1).lower()
        if name in variables:
            return variables[name]
        if track is not None:
            track.missing.add("${" + m.group(1) + "}")
        return m.group(0)

    def _wc(self, m, chooser, track):
        opts = self.lookup(m.group(1))
        if not opts:
            if track is not None:
                track.missing.add(f"__{m.group(1)}__")
            return m.group(0)
        idx = chooser.choose([o[0] for o in opts], key="wc:" + m.group(1).lower())
        if track is not None:
            track.used.add(opts[idx][2])
        return opts[idx][1]

    def _variant(self, body, chooser):
        mm = MULTI_RE.match(body)
        if mm:
            lo = int(mm.group(1))
            hi = int(mm.group(2)) if mm.group(2) else lo
            sep = mm.group(3) if mm.group(3) is not None else ", "
            rest = mm.group(4)
        else:
            lo = hi = 1
            sep, rest = ", ", body
        opts = [parse_option(o) for o in rest.split("|")]
        if not mm:
            return opts[chooser.choose([w for w, _ in opts], key="v:" + body)][1]
        hi = min(max(hi, lo), len(opts))
        lo = min(lo, hi)
        count = lo + chooser.choose([1.0] * (hi - lo + 1))
        remaining, picked = list(range(len(opts))), []
        for _ in range(count):
            j = chooser.choose([opts[r][0] for r in remaining])
            picked.append(remaining.pop(j))
        return sep.join(opts[r][1] for r in picked)

    def enumerate(self, text, max_count=50, track=None):
        results, seen, path = [], set(), []
        for _ in range(max(1, max_count) * 50):
            ch = EnumChooser(path)
            out = self.resolve(text, ch, track)
            if out not in seen:
                seen.add(out)
                results.append(out)
                if len(results) >= max_count:
                    break
            t, a = ch.taken, ch.arities
            i = len(t) - 1
            while i >= 0 and t[i] + 1 >= a[i]:
                i -= 1
            if i < 0:
                break
            path = t[:i] + [t[i] + 1]
        return results

    # ---- check ----
    def diagnose(self):
        """Returns {category: [(label, search_term)]}; search_term targets the file search."""
        out = {"errors": [], "missing": [], "empty_refs": [], "empty": [], "dup_keys": [], "dup_names": []}
        for path in sorted(self._files):
            err = self._files[path][2]
            if err:
                rel = self.rel(path)
                out["errors"].append((f"{rel}: {err}", rel))
        missing, empty_refs = set(), set()
        for k, opts in self.entries.items():
            src = self.rel(self.key_files[k][0])
            for _, t in opts:
                for m in WILDCARD_RE.finditer(t):
                    name = m.group(1)
                    keys = self.keys_for(name)
                    if not keys:
                        missing.add((f"__{name}__  ←  {src}", src))
                    elif not any(self.entries[x] for x in keys):
                        empty_refs.add((f"__{name}__  ←  {src}  (target is empty)", src))
        out["missing"] = sorted(missing)
        out["empty_refs"] = sorted(empty_refs)
        out["empty"] = sorted((f"{k}  ({self.rel(self.key_files[k][0])})", self.rel(self.key_files[k][0]))
                              for k, opts in self.entries.items() if not opts)
        out["dup_keys"] = sorted((f"{k}: " + ", ".join(self.rel(f) for f in fs), self.rel(fs[0]))
                                 for k, fs in self.key_files.items() if len(fs) > 1)
        by_name = {}
        for path in self._files:
            if path.lower().endswith(".txt"):
                by_name.setdefault(os.path.basename(path).lower(), []).append(self.rel(path))
        out["dup_names"] = sorted((f"{n}: " + ", ".join(sorted(r)), n)
                                  for n, r in by_name.items() if len(r) > 1)
        return out
