<p align="center"><img src="assets/logo.svg" width="96" alt="Ω̂"></p>

<h1><img src="assets/omega-letter.svg" height="34" alt="Ω̂">mega Wildcards — v2.1.0</h1>

*by anthropropos · built with Claude*

**Example images:** [Ω̂mega Wildcards on Civitai](https://civitai.com/models/3025159/wmega-wildcards-layered-yamltxt-wildcards-for-forge-neo-and-a1111)

**A self-contained wildcard extension for Stable Diffusion WebUI Forge Neo (and A1111-style WebUIs).**
Reads `.txt` and `.yaml` wildcards at any folder depth, adds stackable wildcard layers, a searchable collection-prompt picker, reproducible variation modes, a live preview that opens the source files, and a workspace tab to sort and check large wildcard libraries.

---

## Why

Dynamic Prompts is powerful but heavy, and it does not load on every current WebUI build. The classic wildcards extension is light but only knows `.txt`, needs exact paths and offers no overview. This extension sits in between:

- **One folder, any structure.** `.txt` and `.yaml` side by side, nested as deep as you like. Calls are case-insensitive and may skip subfolders.
- **Built for big libraries.** Tested with ~6,000 files and ~8,000 wildcards. Files are indexed and re-read only when they change.
- **No more wildcards hidden in styles.** Hang any wildcard file into the prompt with a searchable layer, choose before/after and a weight — like LoRA slots.
- **Update-safe.** No fork of another extension. It only uses the stable script API (`scripts.Script`, `shared.opts`, `script_callbacks`) and plain Gradio components. Errors never break a generation: the prompt is simply left unchanged and the console says why.

## Installation

**From the WebUI:** Extensions → Install from URL → paste

```
https://github.com/Omega-prixel/Omega-Wildcards
```

→ Install. Then Apply and restart.

**Manually:** download the ZIP from [Releases](https://github.com/Omega-prixel/Omega-Wildcards/releases) and copy the folder `omega-wildcards` into `extensions/` of your WebUI.

Put your wildcards into the extension's `wildcards/` folder (`extensions/Omega-Wildcards/wildcards/` when installed from URL) (or point Settings → Omega Wildcards to an existing folder).
Restart the WebUI and reload the browser page with **Ctrl+F5**.

The console confirms: `[Omega Wildcards] v2.1.0 loaded: … files, … wildcards from …`

**Updating:** installed from URL → Extensions → Check for updates. Installed manually → delete everything in the extension folder **except** `wildcards/`, copy the new version in, restart, Ctrl+F5.

> Disable other wildcard extensions (e.g. `stable-diffusion-webui-wildcards`, Dynamic Prompts). Two resolvers on the same prompt get in each other's way.

## Where things are

| Place | What it is for |
|---|---|
| **Accordion below the prompt** | Everything you decide per generation: switches, collection prompt, wildcard layers, preview, syntax help |
| **Ω̂mega Wildcards tab** | Your workspace for sorting: search by name or content, folder/file picker, content view, open in editor or Explorer, library check |
| **Settings → Omega Wildcards** | Folder, editor, file check interval, defaults |

## The accordion

**Switches**
- **Enabled** – wildcard resolving on/off.
- **Keep prompt** – locks the wildcards of the last run or preview. The image seed keeps changing, the prompt stays.
- **Same image seed for all images** – every image of a batch gets the first image seed; only the wildcards vary. Fix the image seed across runs in the WebUI's own seed field.
- **Even distribution** – within one run, options are drawn without replacement: every option comes up once before any repeats.
- **Combinatorial** + **Max combinations** – generates every combination in order instead of random picks; batch count follows automatically.
- **Tidy commas** – removes `, ,` and stray spaces left by empty options.
- **↺ Reset** – everything back to the start: switches to their defaults, layers cleared, kept prompt and held layers forgotten.

Wildcards follow the WebUI's image seed: the same image seed always gives the same prompt.

**Collection prompt** – a searchable list of every ready-made prompt entry (any wildcard whose own name starts with `prompt`, e.g. `cf-ancient-rome/prompt-full`), labelled with its file. Pick several and every image gets one of them. Inserted before or after your prompt at generation time.

**Wildcard layers** – up to 12 rows, added with **+ Add layer** and removed with **✕**. Each row: on/off, search field (wildcard name or file name; several words narrow down), the wildcard pick (several = one per image), insert before/after, weight (`1` = plain, otherwise `(…:weight)`), **Hold** and **📝**.
- **Hold** freezes this layer's last result while all other layers keep rolling — freeze the outfit, let style and setting vary, or the other way round.
- **📝** opens the files of this layer in your editor.

Names are shown short: the title first, followed only by as much of the path as needed to tell two wildcards apart (`hair · rapunzel`, `hair · showcase`). Search still covers the full path and file name. Layers are applied in row order and written to the image infotext as `Wildcard layers` (held layers are marked).

**Preview** – *Resolve prompt* resolves what is in the prompt box. If the box is empty (e.g. your prompt comes from styles), it shows the **last generation** instead. *Wildcards used* lists every file involved; open the selected ones or all of them in your editor, or show them in Explorer.

## The Ω̂mega Wildcards tab

Search by file/folder name or inside the content, browse by folder, see each file's call names (`__…__`), open it in your editor or Explorer.

**Duplicates** lists files with the same name in several folders and wildcard names defined in several files, shows their contents side by side, with size and date, and lets you open them in your editor, show them in Explorer (to rename or move), merge each selected `.txt` group into one file (unique lines, order kept) or move files to `_trash`. Groups and files are checkbox lists; select one, several or all groups at once. **Clean up by rule** handles the selected groups or all groups: keep the largest, smallest, newest, oldest, shortest or longest path — the first click shows a preview, the second click confirms.

**Rename + update references** (in Duplicates and in the file view) renames a file and rewrites every `__reference__` in your library that pointed to it — so renaming a duplicate never leaves calls pointing to nothing. Short calls that pooled several files (e.g. `__colors__`) simply keep using the remaining files. Every rename is logged in `_trash/rename_log.csv`. Nothing is ever deleted — `_trash` sits inside your wildcard folder and is ignored by the extension.

**Check all wildcards** sorts problems into collapsible groups — loading errors (with line and column), references to nothing, references to empty wildcards, empty wildcards, names defined twice, same file name in several folders. Click an entry and the file opens in the search above.

## Syntax

| Syntax | Effect |
|---|---|
| `__name__` | random entry; case-insensitive; subfolders may be omitted (`__colors__` finds `art/deep/colors.txt`) |
| `__grimm/*/setting__` | `*` pools several wildcards |
| `{a\|b\|c}` | inline variant, nestable |
| `{3::a\|1::b}` | weighting: `a` three times as often as `b` |
| `3::text` | weighting of a `.txt` line or a YAML entry |
| `{2$$a\|b\|c}` | two different options, joined with `, ` |
| `{1-3$$a\|b\|c}` | one to three different options |
| `{2$$ and $$a\|b\|c}` | custom separator |
| `${time={amber dusk\|grey morning}}` | variable: rolled once, produces no text |
| `${time}` | inserts the same value everywhere — no more contradicting wildcards |
| `__person/hair/${age}__` | dynamic wildcard name — the variable chooses the wildcard, so age, hair and clothing stay coherent |
| `# comment` | ignored line in `.txt` |

**YAML:** keys form the path, the file name does not count (folders do). A list is a wildcard; nested keys are sub-wildcards.

```yaml
grimm:
  artist: [Arthur Rackham, Edmund Dulac, Kay Nielsen]
  rapunzel:
    hair: ["{loose|braided} floor-length bright hair"]
    prompt:
      - "__grimm/artist__ style, (Hedda, German female:1.2), __grimm/rapunzel/hair__"
```

`examples/grimm.yaml` contains twelve complete fairy-tale character sets, `examples/showcase.yaml` one character with style, clothing and setting layers — copy them into your wildcard folder to try.

## Check without the WebUI

```
python selftest.py [folder]
```
Lists loading errors, missing references, empty wildcards and duplicates — handy after updates or big imports.

## Compatibility

Developed and tested on Forge Neo 2.31 (Python 3.13, Gradio 4). Uses only APIs shared with AUTOMATIC1111-style WebUIs. PyYAML is required for `.yaml` files (it ships with the WebUI).

## Troubleshooting

- Every click is logged as `[Omega Wildcards] <action>`; errors print a full traceback.
- Buttons without effect after an update: reload the page with **Ctrl+F5**.
- `__name__` stays in the prompt: the wildcard does not exist — run the check in the Ω̂mega Wildcards tab.

---

## Changelog

**2.1.0** – Hold per layer · 📝 open per layer · ↺ Reset · Tidy commas · short unique names in all lists · preview: select several, Open all · Duplicates editor with merge, `_trash`, clean-up rules for all groups at once and rename with automatic reference update

**2.0.0** – first public release

## Built with Claude

<img src="assets/logo.svg" width="48" align="left" alt="Ω̂" style="margin-right:12px">

The name says it: **Ω̂mega** — the Ω̂ sign is the first letter. This extension was designed and written in conversation with **Claude** (Anthropic) — from the first idea to this release within a single day, including live debugging against a real Forge Neo installation with a library of ~6,000 wildcard files. The human side set the goals, tested every version and decided what the tool should feel like; Claude wrote the code, the tests and this documentation.

The **Ω̂** sign marks AI-assisted work. In statistics, **Ω** is the *sample space* — the set of all possible outcomes — and the circumflex **ˆ** marks an *estimate* derived from data. Together they describe inference: from the space of all possible results to a reasoned, data-based estimate or decision. That is also what a wildcard does — and what working with an AI is like.

## License

MIT — see `LICENSE`.
