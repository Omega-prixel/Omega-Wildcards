import math
import os
import random
import sys

import gradio as gr

from modules import scripts, script_callbacks, shared

EXT_DIR = scripts.basedir()
if EXT_DIR not in sys.path:
    sys.path.insert(0, EXT_DIR)

from lib_yamlwc.core import WildcardStore, RandomChooser, BagChooser, Track  # noqa: E402
from lib_yamlwc.osutil import open_file, show_in_explorer  # noqa: E402

VERSION = "2.0.0"
NAME = "\u03a9\u0302mega Wildcards"
MAX_LAYERS = 12
LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="{size}" height="{size}" '
    'fill="none" stroke="currentColor" style="vertical-align:middle">'
    '<circle cx="100" cy="100" r="88" stroke-width="12"/>'
    '<polyline points="77,55 100,33 123,55" stroke-width="12" stroke-linejoin="miter"/>'
    '<path d="M54 157 H81 V147.6 A44 44 0 1 1 119 147.6 V157 H146" stroke-width="14" stroke-linejoin="miter"/>'
    '</svg>')
CREDIT_HTML = (
    '<div style="display:flex;align-items:center;gap:.5em;opacity:.8;font-size:.9em">'
    + LOGO_SVG.format(size=22)
    + f'<b>{NAME}</b>'
    + '<span>Built with Claude (Anthropic) · \u03a9\u0302 marks AI-assisted work: from the space of possible '
      'outcomes to a reasoned estimate.</span></div>')
TAG = "[Omega Wildcards]"
_store = None
_last_seed = {"value": -1}
_last_used = []
_last_run = {}
_warned = set()

MODE_HELP = """
The wildcards follow Forge's own image seed: the same image seed always gives the same prompt.
**Keep prompt** – locks the wildcards of the last run or preview. All following images use exactly this prompt while the image seed keeps changing. Untick to roll again.
**Same image seed for all images** – every image of a batch gets the first image seed, only the wildcards vary. To keep the image seed across runs as well, fix it in Forge's seed field (♻️ there).
**Even distribution** – within one run, options are drawn without replacement: every option comes up once before any repeats (weights are ignored; no effect while the prompt is kept).
**Combinatorial** – instead of random picks, all combinations are generated in order, up to "Max combinations". The image count follows from that; batch count is overridden, batch size is kept.
"""

SYNTAX_HELP = """
| Syntax | Effect |
|---|---|
| `__name__` | random entry; case-insensitive, subfolders may be omitted (`__colors__` finds `art/deep/colors.txt`) |
| `__grimm/*/setting__` | `*` pools several wildcards together |
| `{a\\|b\\|c}` | inline variant, nestable |
| `{3::a\\|1::b}` | weighting: a appears three times as often as b |
| `3::text` | weighting of a .txt line or a YAML entry |
| `{2$$a\\|b\\|c}` | two different options, joined with `, ` |
| `{1-3$$a\\|b\\|c}` | one to three different options |
| `{2$$ and $$a\\|b\\|c}` | custom separator between options |
| `${zeit={amber dusk\\|grey morning}}` | variable: rolled once, produces no text itself |
| `${zeit}` | inserts the same value everywhere |
| `# comment` | line in .txt is ignored |
"""


# ---------------- Hilfen ----------------
def _opt(name, default):
    return getattr(shared.opts, name, default)


def _directory():
    custom = (_opt("yamlwc_dir", "") or "").strip()
    if custom:
        return custom
    return getattr(shared.cmd_opts, "wildcards_dir", None) or os.path.join(EXT_DIR, "wildcards")


def _get_store(force=False):
    global _store
    directory = _directory()
    default = os.path.join(EXT_DIR, "wildcards")
    if directory == default and not os.path.isdir(default):
        try:
            os.makedirs(default, exist_ok=True)
        except OSError:
            pass
    interval = float(_opt("yamlwc_interval", 3) or 0)
    if _store is None or _store.directory != directory:
        _store = WildcardStore(directory, interval)
        force = True
    _store.interval = interval
    _store.refresh(force)
    for err in _store.errors:
        if err not in _warned:
            print(f"{TAG} {err}", file=sys.stderr)
            _warned.add(err)
    return _store


def _status_text(force=False):
    try:
        store = _get_store(force)
    except Exception as e:
        return f"**Loading error:** {e}"
    lines = [f"**Folder:** `{store.directory}`",
             f"**Files:** {store.file_count()} · **Wildcards:** {len(store.entries)}"]
    if not os.path.isdir(store.directory):
        lines.append("**Folder does not exist.**")
    if store.errors:
        lines.append(f"**Loading errors:** {len(store.errors)} (details in the Ω̂mega Wildcards tab → Check)")
    return "  \n".join(lines)


def _upd(**kw):
    """gr.update in Gradio 3/4, otherwise a plain update dict."""
    if hasattr(gr, "update"):
        return gr.update(**kw)
    return {"__type__": "update", **kw}


def _log(name, fn):
    """Logs every click in the console and prints full tracebacks."""
    import traceback

    def wrapper(*a):
        print(f"{TAG} {name}")
        try:
            return fn(*a)
        except Exception as e:
            traceback.print_exc()
            return f"Error: {e}"
    return wrapper


def _prompt_js(elem_id):
    """Reads the prompt straight from the page at click time (covers JS-driven prompt editors)."""
    return ("(...args) => {"
            " const root = (typeof gradioApp === 'function') ? gradioApp() : document;"
            f" const box = root.querySelector('#{elem_id}');"
            " let v = null;"
            " if (box) {"
            "  const ta = box.matches('textarea') ? box : box.querySelector('textarea');"
            "  if (ta) v = ta.value;"
            "  if (!v) { const ce = box.querySelector('[contenteditable]'); if (ce) v = ce.innerText; }"
            " }"
            " if (v) args[0] = v;"
            " return args; }")


def _click(button, fn, inputs, outputs, js=None):
    """Event with optional JS preprocessing, for Gradio 3 (_js) and 4+ (js)."""
    if js:
        try:
            return button.click(fn, inputs=inputs, outputs=outputs, js=js)
        except TypeError:
            try:
                return button.click(fn, inputs=inputs, outputs=outputs, _js=js)
            except TypeError:
                pass
    return button.click(fn, inputs=inputs, outputs=outputs)


def _safe(fn):
    return _log(getattr(fn, "__name__", "action"), fn)


def _open(rel, explorer=False):
    if not rel:
        return "No file selected."
    store = _get_store()
    path = store.abspath(rel.split("  ·  ")[-1])
    if not os.path.exists(path):
        return f"File not found: {path}"
    (show_in_explorer if explorer else lambda p: open_file(p, _opt("yamlwc_editor", "")))(path)
    return f"Opened: `{path}`"


def _catalog(store):
    """Collection prompts labelled with their file, so file names are searchable too."""
    return [_label(store, k) for k in store.prompt_keys()]


def _layer_count():
    """Layers visible at start; more can be added in the UI up to MAX_LAYERS."""
    try:
        return max(1, min(MAX_LAYERS, int(_opt("yamlwc_layers", 1))))
    except (TypeError, ValueError):
        return 1


def _key_of(label):
    return (label or "").split("  ·  ")[0].strip()


def _call(labels):
    """One or several picks -> one call; several = one of them per image."""
    if isinstance(labels, str):
        labels = [labels]
    calls = [f"__{_key_of(l)}__" for l in (labels or []) if l]
    if not calls:
        return ""
    return calls[0] if len(calls) == 1 else "{" + "|".join(calls) + "}"


def _weighted(token, weight):
    try:
        w = float(weight)
    except (TypeError, ValueError):
        w = 1.0
    if not token or abs(w - 1.0) < 1e-6:
        return token
    return f"({token}:{w:g})"


def _label(store, key):
    return f"{key}  ·  {store.rel(store.key_files[key][0])}"


# ---------------- Script ----------------
class YamlWildcardsScript(scripts.Script):
    def __init__(self):
        super().__init__()
        self._boxes = {}

    def title(self):
        return NAME

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def after_component(self, component, **kwargs):
        eid = kwargs.get("elem_id")
        if eid in ("txt2img_prompt", "img2img_prompt"):
            self._boxes[eid] = component

    def _find_prompt_box(self, is_img2img):
        eid = "img2img_prompt" if is_img2img else "txt2img_prompt"
        box = self._boxes.get(eid)
        if box is not None:
            return box, "captured"
        try:
            from gradio.context import Context
            root = getattr(Context, "root_block", None)
            for block in (getattr(root, "blocks", {}) or {}).values():
                if getattr(block, "elem_id", None) == eid:
                    return block, "found in layout"
        except Exception as e:
            print(f"{TAG} prompt search failed: {e}", file=sys.stderr)
        return None, "not found, using own field"

    def ui(self, is_img2img):
        prompt_box, source = self._find_prompt_box(is_img2img)
        print(f"{TAG} preview prompt ({'img2img' if is_img2img else 'txt2img'}): {source}")
        with gr.Accordion(f"{NAME} v{VERSION}", open=False):
            gr.HTML(CREDIT_HTML)
            status = gr.Markdown(_status_text())
            with gr.Row():
                enabled = gr.Checkbox(label="Enabled", value=_opt("yamlwc_default_enabled", True))
                wc_seed = gr.Checkbox(label="Keep prompt", value=False)
                mode = gr.Checkbox(label="Same image seed for all images",
                                   value=bool(_opt("yamlwc_default_fixed_image_seed", False)))
                even = gr.Checkbox(label="Even distribution", value=_opt("yamlwc_default_even", False))
                combi = gr.Checkbox(label="Combinatorial", value=False)
            combi_max = gr.Slider(1, 500, step=1, value=_opt("yamlwc_combi_max", 50), label="Max combinations")
            with gr.Row():
                collection = gr.Dropdown(label="Collection prompt (type to search, several = one per image)",
                                         choices=_catalog(_get_store()), value=[], multiselect=True)
                position = gr.Radio(["after prompt", "before prompt"], value="after prompt", label="Insert")
            layer_inputs, rows, removers = [], [], []
            start = _layer_count()
            with gr.Accordion("Wildcard layers", open=True):
                for i in range(MAX_LAYERS):
                    with gr.Row(variant="compact", visible=i < start) as row:
                        l_on = gr.Checkbox(label=f"{i + 1}", value=True, min_width=50, scale=0)
                        l_search = gr.Textbox(label="Search name or file", placeholder="e.g. hair long", scale=2)
                        l_pick = gr.Dropdown(label="Wildcard (several = one per image)", choices=[], value=[],
                                             multiselect=True, scale=4)
                        l_pos = gr.Radio(["after", "before"], value="after", label="Insert", scale=1)
                        l_weight = gr.Slider(0.0, 2.0, step=0.05, value=1.0, label="Weight", scale=1)
                        l_remove = gr.Button("✕", min_width=40, scale=0)

                    def layer_search(q, current):
                        store_ = _get_store()
                        current = current or []
                        if isinstance(current, str):
                            current = [current]
                        hits = [_label(store_, k) for k in store_.search_keys(q)]
                        choices = list(dict.fromkeys(list(current) + hits))
                        return _upd(choices=choices, value=current)

                    l_search.change(layer_search, inputs=[l_search, l_pick], outputs=[l_pick])
                    layer_inputs += [l_on, l_pick, l_pos, l_weight]
                    rows.append(row)
                    removers.append((l_remove, l_search, l_pick, l_on, l_weight))
                visible = gr.State([i < start for i in range(MAX_LAYERS)])
                add_btn = gr.Button("+ Add layer")

            def add_layer(vis):
                vis = list(vis)
                for i, v in enumerate(vis):
                    if not v:
                        vis[i] = True
                        break
                return [vis] + [_upd(visible=v) for v in vis]

            add_btn.click(_log("add layer", add_layer), inputs=[visible], outputs=[visible] + rows)
            for i, (btn, l_search, l_pick, l_on, l_weight) in enumerate(removers):
                def remove_layer(vis, i=i):
                    vis = list(vis)
                    vis[i] = False
                    if not any(vis):
                        vis[0] = True
                    return ([vis] + [_upd(visible=v) for v in vis]
                            + [_upd(value=""), _upd(choices=[], value=[]), _upd(value=True), _upd(value=1.0)])

                btn.click(_log(f"remove layer {i + 1}", remove_layer), inputs=[visible],
                          outputs=[visible] + rows + [l_search, l_pick, l_on, l_weight])
            with gr.Accordion("What the switches do", open=False):
                gr.Markdown(MODE_HELP)
            with gr.Accordion("Preview", open=False):
                local = None
                if prompt_box is None:
                    local = gr.Textbox(label="Prompt to preview", lines=2)
                preview_btn = gr.Button("Resolve prompt")
                preview_out = gr.Textbox(label="Resolved prompt", lines=4, interactive=False)
                preview_info = gr.Markdown()
                used = gr.Dropdown(label="Wildcards used", choices=[], value=None)
                with gr.Row():
                    open_btn = gr.Button("Open in editor")
                    expl_btn = gr.Button("Show in Explorer")
                open_info = gr.Markdown()
            with gr.Accordion("Syntax help", open=False):
                gr.Markdown(SYNTAX_HELP)
            refresh = gr.Button("Reload")

        def do_preview(prompt, mode_v, keep_v, even_v):
            try:
                print(f"{TAG} preview: prompt received ({len(prompt or '')} characters)")
                if not (prompt or "").strip():
                    if not _last_run:
                        return "", "The prompt box is empty and nothing has been generated yet.", _upd(choices=[], value=None)
                    labels = list(_last_run["used"])
                    _last_used[:] = labels
                    info = (f"Prompt box is empty – showing the **last generation** (styles included), "
                            f"wildcard seed {_last_run['seed']}.")
                    if _last_run["missing"]:
                        info += "  \n**Not found:** " + ", ".join(f"`{m}`" for m in _last_run["missing"])
                    return _last_run["resolved"], info, _upd(choices=labels, value=labels[0] if labels else None)
                store = _get_store()
                if keep_v and _last_seed["value"] >= 0:
                    seed = _last_seed["value"]
                else:
                    seed = random.randrange(2 ** 31)
                    _last_seed["value"] = seed
                rng = random.Random(seed)
                chooser = BagChooser(rng) if even_v else RandomChooser(rng)
                track = Track()
                out = store.resolve(prompt or "", chooser, track)
                labels = sorted(_label(store, k) for k in track.used)
                _last_used[:] = labels
                print(f"{TAG} preview: {len(labels)} wildcard files used")
                info = (f"Wildcard seed {seed} – this prompt is kept." if keep_v
                        else f"Wildcard seed {seed} – tick \"Keep prompt\" to generate with exactly this prompt.")
                if track.missing:
                    info += "  \n**Not found:** " + ", ".join(f"`{m}`" for m in sorted(track.missing))
                return out, info, _upd(choices=labels, value=labels[0] if labels else None)
            except Exception as e:
                return "", f"Error: {e}", _upd(choices=[], value=None)

        _click(preview_btn, _log("preview", do_preview),
               inputs=[prompt_box if prompt_box is not None else local, mode, wc_seed, even],
               outputs=[preview_out, preview_info, used],
               js=_prompt_js("img2img_prompt" if is_img2img else "txt2img_prompt") if prompt_box is not None else None)
        def preview_pick(r):
            if r:
                return r
            if _last_used:
                return _last_used[0]
            return None

        def preview_open(r, explorer=False):
            pick = preview_pick(r)
            if pick is None:
                return "The last preview used no wildcard files (or no preview has been run yet)."
            return _open(pick, explorer)

        open_btn.click(_log("open (preview)", lambda r: preview_open(r)), inputs=[used], outputs=[open_info])
        expl_btn.click(_log("explorer (preview)", lambda r: preview_open(r, True)), inputs=[used], outputs=[open_info])
        def do_reload():
            text = _status_text(force=True)
            return text, _upd(choices=_catalog(_get_store()))

        refresh.click(_log("reload", do_reload), outputs=[status, collection])
        return [enabled, mode, wc_seed, even, combi, combi_max, collection, position] + layer_inputs

    # ---------------- Verarbeitung ----------------
    def process(self, p, *args):
        args = list(args)
        enabled, mode, keep, even, combi, combi_max, collection, position = (
            args + [True, False, False, False, False, 50, [], "after prompt"])[:8]
        layer_args = args[8:]
        before, after, layer_info = [], [], []
        if collection:
            (before if position == "before prompt" else after).append(_call(collection))
        for i in range(0, len(layer_args) - 3, 4):
            on, pick, pos, weight = layer_args[i:i + 4]
            token = _weighted(_call(pick), weight)
            if on and token:
                (before if pos == "before" else after).append(token)
                layer_info.append(f"{i // 4 + 1}:{pos}:{token}")
        if not enabled:
            return
        try:
            store = _get_store()
        except Exception as e:
            print(f"{TAG} loading failed: {e}", file=sys.stderr)
            return
        prompts = getattr(p, "all_prompts", None)
        if not prompts:
            return
        if before or after:
            def insert(text):
                text = (text or "").strip().strip(",").strip()
                return ", ".join(x for x in before + [text] + after if x)

            old = list(p.all_prompts)
            p.all_prompts = [insert(t) for t in old]
            hr = getattr(p, "all_hr_prompts", None)
            if hr:
                p.all_hr_prompts = [insert(t) for t in hr]
            prompts = p.all_prompts
        original_prompt = prompts[0]
        original_neg = (getattr(p, "all_negative_prompts", None) or [""])[0]
        fixed = _last_seed["value"] if keep is True and _last_seed["value"] >= 0 else None
        try:
            if combi:
                used_seed = self._combinatorial(p, store, mode, fixed, int(combi_max or 50))
            else:
                used_seed = self._random(p, store, mode, fixed, even)
        except Exception as e:
            print(f"{TAG} error, prompts left unchanged: {e}", file=sys.stderr)
            return
        if _opt("yamlwc_write_infotext", True):
            params = getattr(p, "extra_generation_params", None)
            if params is not None:
                if p.all_prompts[0] != original_prompt:
                    params["Wildcard prompt"] = original_prompt
                if p.all_negative_prompts and p.all_negative_prompts[0] != original_neg:
                    params["Wildcard negative prompt"] = original_neg
                params["Wildcard seed"] = used_seed
                if layer_info:
                    params["Wildcard layers"] = "; ".join(layer_info)
                modes = [m for m, on in [("combinatorial", combi), ("kept prompt", fixed is not None and not combi),
                                         ("same image seed", mode)] if on]
                if modes:
                    params["Wildcard mode"] = ", ".join(modes)
        _last_seed["value"] = used_seed

    def _report(self, track, store=None, p=None, seed=None, original=None):
        if store is not None and p is not None:
            try:
                labels = sorted(_label(store, k) for k in track.used)
                _last_run.update(original=original, resolved=p.all_prompts[0], used=labels,
                                 missing=sorted(track.missing), seed=seed)
                _last_used[:] = labels
            except Exception as e:
                print(f"{TAG} could not store last run: {e}", file=sys.stderr)
        for name in track.missing - _warned:
            print(f"{TAG} not found: {name}", file=sys.stderr)
            _warned.add(name)

    def _random(self, p, store, mode, fixed, even):
        n = len(p.all_prompts)
        seeds = list(p.all_seeds)
        if fixed is not None:
            wseeds = [fixed] * n
            if mode:
                p.all_seeds = [seeds[0]] * len(seeds)
        elif mode:
            p.all_seeds = [seeds[0]] * len(seeds)
            if getattr(p, "all_subseeds", None):
                p.all_subseeds = [p.all_subseeds[0]] * len(p.all_subseeds)
            wseeds = [seeds[0] + i for i in range(n)]
        else:
            wseeds = [seeds[min(i, len(seeds) - 1)] for i in range(n)]

        track = Track()
        bag = BagChooser(random.Random(wseeds[0])) if even and fixed is None else None

        def chooser(i):
            return bag if bag else RandomChooser(random.Random(wseeds[i]))

        orig = list(p.all_prompts)
        p.all_prompts = [store.resolve(t, chooser(i), track) for i, t in enumerate(orig)]
        if getattr(p, "all_negative_prompts", None):
            p.all_negative_prompts = [store.resolve(t, RandomChooser(random.Random(wseeds[min(i, n - 1)])), track)
                                      for i, t in enumerate(p.all_negative_prompts)]
        self._hr(p, orig, store, wseeds, track)
        self._report(track, store, p, wseeds[0], orig[0])
        return wseeds[0]

    def _hr(self, p, orig, store, wseeds, track):
        hr = getattr(p, "all_hr_prompts", None)
        if hr:
            p.all_hr_prompts = list(p.all_prompts) if list(hr) == orig else [
                store.resolve(t, RandomChooser(random.Random(wseeds[min(i, len(wseeds) - 1)])), track)
                for i, t in enumerate(hr)]
        hrn = getattr(p, "all_hr_negative_prompts", None)
        if hrn:
            p.all_hr_negative_prompts = [
                store.resolve(t, RandomChooser(random.Random(wseeds[min(i, len(wseeds) - 1)])), track)
                for i, t in enumerate(hrn)]

    def _combinatorial(self, p, store, mode, fixed, max_count):
        prompt = p.all_prompts[0]
        track = Track()
        combos = store.enumerate(prompt, max(1, max_count), track)
        batch = max(1, int(getattr(p, "batch_size", 1)))
        n_iter = math.ceil(len(combos) / batch)
        total = n_iter * batch
        combos = [combos[i % len(combos)] for i in range(total)]
        seed0 = p.all_seeds[0]
        sub0 = p.all_subseeds[0] if getattr(p, "all_subseeds", None) else 0
        same = bool(mode)
        p.n_iter = n_iter
        p.all_seeds = [seed0 if same else seed0 + i for i in range(total)]
        p.all_subseeds = [sub0 if same else sub0 + i for i in range(total)]
        base = fixed if fixed is not None else seed0
        neg0 = (getattr(p, "all_negative_prompts", None) or [""])[0]
        neg = store.resolve(neg0, RandomChooser(random.Random(base)), track)
        orig = [prompt] * total
        hr_orig = getattr(p, "all_hr_prompts", None)
        p.all_prompts = combos
        p.all_negative_prompts = [neg] * total
        if hr_orig:
            p.all_hr_prompts = list(combos) if hr_orig[0] == prompt else \
                [store.resolve(hr_orig[0], RandomChooser(random.Random(base)), track)] * total
        if getattr(p, "all_hr_negative_prompts", None):
            p.all_hr_negative_prompts = [store.resolve(p.all_hr_negative_prompts[0],
                                                       RandomChooser(random.Random(base)), track)] * total
        try:
            shared.state.job_count = n_iter
        except Exception:
            pass
        self._report(track, store, p, base, prompt)
        print(f"{TAG} combinatorial: {len(set(combos))} combinations, {total} images")
        return base


# ---------------- Wildcards tab ----------------
CHECK_CATEGORIES = [
    ("errors", "Loading errors"),
    ("missing", "References to nothing"),
    ("empty_refs", "References to empty wildcards"),
    ("empty", "Empty wildcards"),
    ("dup_keys", "Same wildcard name in several files"),
    ("dup_names", "Same file name in several folders (pooled for short calls)"),
]
CHECK_LIMIT = 300
_check_map = {}


def _run_check():
    store = _get_store(force=True)
    r = store.diagnose()
    _check_map.clear()
    summary = [f"**{store.file_count()} files, {len(store.entries)} wildcards** – click an entry to find its file."]
    updates = []
    for key, title in CHECK_CATEGORIES:
        items = r[key]
        summary.append(f"{title}: {len(items)}")
        shown = items[:CHECK_LIMIT]
        for label, term in shown:
            _check_map[label] = term
        lab = f"{len(items)} entries" + (f" (first {CHECK_LIMIT} shown)" if len(items) > CHECK_LIMIT else "")
        updates.append(_upd(choices=[l for l, _ in shown], value=None, label=lab))
    return ["  \n".join(summary)] + updates


def _file_view(rel):
    if not rel:
        return "", ""
    store = _get_store()
    path = store.abspath(rel)
    try:
        with open(path, encoding="utf8", errors="replace") as f:
            content = f.read(200_000)
    except OSError as e:
        return f"Error: {e}", ""
    keys = store.keys_of_file(rel)
    calls = ", ".join(f"`__{k}__`" for k in keys[:100]) + (" …" if len(keys) > 100 else "")
    return content, f"**Call:** {calls}" if keys else ""


def on_ui_tabs():
    store = _get_store()
    folders = store.folders()
    with gr.Blocks(analytics_enabled=False) as tab:
        gr.HTML(CREDIT_HTML)
        status = gr.Markdown(_status_text())
        with gr.Row():
            query = gr.Textbox(label="Search", placeholder="Part of a file or folder name")
            in_content = gr.Checkbox(label="Also search content", value=False)
            search_btn = gr.Button("Search")
        with gr.Row():
            folder = gr.Dropdown(label="Folder", choices=folders, value=None)
            file = gr.Dropdown(label="File", choices=[], value=None)
        calls = gr.Markdown()
        content = gr.Textbox(label="Content", lines=20, max_lines=40, interactive=False)
        with gr.Row():
            open_btn = gr.Button("Open in editor")
            expl_btn = gr.Button("Show in Explorer")
            refresh_btn = gr.Button("Reload")
        info = gr.Markdown()
        with gr.Accordion("Check", open=False):
            check_btn = gr.Button("Check all wildcards")
            report = gr.Markdown()
            radios = []
            for key, title in CHECK_CATEGORIES:
                with gr.Accordion(title, open=False):
                    radios.append(gr.Radio(choices=[], value=None, label="not checked yet", interactive=True))

        def pick_folder(fd):
            s = _get_store()
            files = [r for r in s.files() if (os.path.dirname(r) or ".") == fd]
            return _upd(choices=files, value=files[0] if files else None)

        def do_search(q, ic):
            if not (q or "").strip():
                return _upd(), "Please enter a search term."
            hits = _get_store().search(q, ic)
            return _upd(choices=hits, value=hits[0] if hits else None), f"{len(hits)} hits" + (" (limited to 500)" if len(hits) >= 500 else "")

        def do_refresh():
            s = _get_store(force=True)
            return _status_text(), _upd(choices=s.folders())

        folder.change(_log("folder", pick_folder), inputs=[folder], outputs=[file])
        search_btn.click(_log("search", do_search), inputs=[query, in_content], outputs=[file, info])
        query.submit(_log("search", do_search), inputs=[query, in_content], outputs=[file, info])
        file.change(_log("file", _file_view), inputs=[file], outputs=[content, calls])
        open_btn.click(_log("open (tab)", lambda r: _open(r)), inputs=[file], outputs=[info])
        expl_btn.click(_log("explorer (tab)", lambda r: _open(r, True)), inputs=[file], outputs=[info])
        refresh_btn.click(_log("reload (tab)", do_refresh), outputs=[status, folder])
        def from_report(label):
            term = _check_map.get(label) if label else None
            if not term:
                return _upd(), _upd(), _upd(), _upd(), _upd()
            s_ = _get_store()
            hits = s_.search(term, False)
            pick = term if term in hits else (hits[0] if hits else None)
            content_v, calls_v = _file_view(pick) if pick else ("", "")
            return (_upd(value=term), _upd(choices=hits, value=pick), content_v, calls_v,
                    f"{len(hits)} hits for `{term}`")

        def run_check():
            try:
                return _run_check()
            except Exception as e:
                import traceback
                traceback.print_exc()
                return [f"Error: {e}"] + [_upd() for _ in CHECK_CATEGORIES]

        check_btn.click(_log("check", run_check), outputs=[report] + radios)
        for radio in radios:
            radio.change(_log("report entry", from_report), inputs=[radio],
                         outputs=[query, file, content, calls, info])
    return [(tab, NAME, "yaml_wildcards_tab")]


# ---------------- Settings ----------------
def on_ui_settings():
    section = ("yaml_wildcards", "Omega Wildcards")
    add = shared.opts.add_option
    add("yamlwc_dir", shared.OptionInfo("", "Wildcard folder (empty = extension folder)", section=section))
    add("yamlwc_editor", shared.OptionInfo("", "Editor for opening files (path to .exe, empty = system default)", section=section))
    add("yamlwc_interval", shared.OptionInfo(3, "Seconds between checks for changed files", section=section))
    add("yamlwc_layers", shared.OptionInfo(1, "Wildcard layers shown at start (1-12; more via \"+ Add layer\")", section=section))
    add("yamlwc_default_enabled", shared.OptionInfo(True, "Default: enabled", section=section))
    add("yamlwc_default_fixed_image_seed", shared.OptionInfo(False, "Default: fixed image seed", section=section))
    add("yamlwc_default_even", shared.OptionInfo(False, "Default: even distribution", section=section))
    add("yamlwc_combi_max", shared.OptionInfo(50, "Default: max combinations", section=section))
    add("yamlwc_write_infotext", shared.OptionInfo(True, "Write original prompt and wildcard seed to infotext", section=section))


def on_app_started(*args, **kwargs):
    try:
        store = _get_store(force=True)
        print(f"{TAG} v{VERSION} loaded: {store.file_count()} files, {len(store.entries)} wildcards from {store.directory}")
    except Exception as e:
        print(f"{TAG} startup failed: {e}", file=sys.stderr)


script_callbacks.on_ui_settings(on_ui_settings)
script_callbacks.on_ui_tabs(on_ui_tabs)
if hasattr(script_callbacks, "on_app_started"):
    script_callbacks.on_app_started(on_app_started)
