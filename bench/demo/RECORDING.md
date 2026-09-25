# Demo recording: operator instructions

This is what to do when sitting down to record the espalier demo.
Claude Code can't record a terminal session itself; this part is yours.

The script the recording follows lives at [`script.md`](script.md). The
recording produces `espalier-demo.gif` (or `.cast` for asciinema) in
this directory.

---

## Setup checklist

Before recording, make a clean environment so the artifact is reproducible
and shows the canonical block messages.

1. **Fresh checkout.** Clone the repository. While the repo is still
   **private (pre-launch)**, the public `github.com` URL 404s — either
   record after the public-flip, or clone from your local checkout:
   ```bash
   cd /tmp
   # After the repo is public:
   git clone https://github.com/Mike-Byrne-AI/espalier-harness espalier-demo
   # Or, pre-launch, from your local checkout:
   #   git clone /path/to/Espalier-Harness espalier-demo
   cd espalier-demo
   pip install -e .
   ```

2. **Initialize the harness in a side project.** The demo blocks writes
   *into a target repo*, not into the espalier repo itself, so set up
   a small test project to record against.
   ```bash
   mkdir -p /tmp/demo-target
   cd /tmp/demo-target
   git init -q
   espalier init .
   espalier doctor .   # expect: pass
   ```

3. **Confirm hooks load.** Open Claude Code in `/tmp/demo-target` and
   verify the SessionStart banner appears:
   ```
   === Espalier-Harness === Session Start ===
   Repo:      demo-target
   Branch:    main
   Status:    clean
   Surface:   healthy
   ```
   (Abbreviated to the stable header fields — the live banner also prints a
   `Host:` line, `Memory:`/`Blueprint:` continuity lines, and a `Commands:`
   footer.) If this banner doesn't appear, see
   [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

4. **Terminal appearance.**
   - Theme: high-contrast (solarized-dark, dracula, or the default
     macOS Terminal "Pro" theme all read well)
   - Font: ≥14pt monospace, ideally 16pt
   - Window: ~1280×720 (16:9). On macOS, `Cmd+Plus` to bump font, then
     resize the window manually until the prompt fits comfortably.
   - Hide anything that names a real path or user (oh-my-zsh prompt,
     iTerm tab title, etc.). The recording goes on the public README.

5. **Practice run.** Walk through `script.md` once without recording.
   The first attempt always reveals timing or window-size issues.

---

## Recording tools

Recommended in order of output quality and ease of post-processing:

### asciinema + svg-term-cli (recommended)

Pure-text recording. Tiny file size. Crisp on every viewer. Works
inline in GitHub if converted to SVG.

```bash
brew install asciinema           # macOS
sudo apt install asciinema       # Debian/Ubuntu

asciinema rec espalier-demo.cast
# ...record the demo, Ctrl-D when done...

# Convert to inline SVG for GitHub:
npm install -g svg-term-cli
cat espalier-demo.cast | svg-term --out espalier-demo.svg --window
```

The `.cast` file is the source of truth; commit it. The `.svg` is the
embeddable artifact for the README.

### terminalizer (fallback)

Real animated GIF. Larger files. Use only if asciinema fails on the
target system.

```bash
npm install -g terminalizer
terminalizer record espalier-demo
terminalizer render espalier-demo
```

### Native screen recording (last resort)

- macOS: `Cmd+Shift+5` → record selected portion → save as `.mov`,
  then convert with `ffmpeg`:
  ```bash
  ffmpeg -i espalier-demo.mov -vf "fps=15,scale=1280:-1:flags=lanczos" \
         -loop 0 espalier-demo.gif
  ```
- Linux: peek (`flatpak install flathub com.uploadedlobster.peek`) or
  kazam.
- Windows: ScreenToGif (open source, well maintained).

---

## Post-processing

1. **Trim** to under 60 seconds. The end-card holds for 6–8 seconds —
   anything longer wastes the viewer's attention.

2. **GIF size budget: under 5MB.** GitHub embeds reliably under that
   threshold; over it you get a "Sorry, this image is too large" link
   instead of an inline render.
   ```bash
   # Optimise an oversized GIF:
   gifsicle -O3 --colors 64 espalier-demo.gif -o espalier-demo-min.gif
   ```

3. **SVG (asciinema → svg-term path).** No size budget worth caring
   about; SVGs are tiny. Just verify it renders on github.com/<repo> —
   GitHub renders SVGs differently from local previews.

4. **Verify the embed.** Push the artifact + the README change to a
   branch, open the branch on github.com, scroll to the demo. If it
   doesn't render or the layout looks wrong, fix it before merging to
   main. Don't trust the local Markdown preview — GitHub strips some
   tags and resizes others.

---

## After recording

Once the artifact is in `bench/demo/espalier-demo.gif` (or
`.svg`/`.cast`):

1. Add the GIF to the top of the README demo section. The section is
   `## 30-second demo` at `README.md:37` (lowercase `s`) — a text/code
   walkthrough, **not** an HTML-comment placeholder. Insert the image
   reference as the first line under the heading, **above** the existing
   text blocks (they stay as an accessible, source-linked fallback):

   ```markdown
   ## 30-second demo

   ![A Claude Code session attempting three different bypasses (direct write,
   path traversal, tee variant) — each blocked by Espalier-Harness's friction
   layer.](bench/demo/espalier-demo.gif)

   <!-- the existing text/code walkthrough stays below as fallback -->
   ```

   The alt text is mandatory for accessibility. Keep it descriptive —
   it's what shows up if the GIF fails to load and what screen readers
   read aloud.

2. Verify the embed on github.com (not the local Markdown preview).

3. Commit with a single message: `docs: add demo GIF`.

---

## Re-recording cadence

Re-record when:

- A canonical bypass class block message changes format (compare
  against the literal strings in `script.md`).
- The SessionStart banner format changes.
- A canonical bypass class is retired or replaced — pick the strongest
  current bypass class for the third attempt to keep the demo
  representative.
- Major version bump (0.x → 1.0, etc.) where the recording's
  apparent age would otherwise mislead viewers.

Don't re-record for cosmetic harness changes. The friction-layer
demonstration is the value; visual polish degrades it.
