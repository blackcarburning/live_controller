# show-sync Timeline Editor — Usage Notes

## Overview

`show-sync-editor.py` is a standalone timeline-based editor for composing
light/display shows that are played back through the **show-sync** web client.
It replaces the previous simple effect-list approach with a proper
multitrack-style editor complete with draggable clips, resize handles, a
WYSIWYG preview, and `.mov` video reference.

---

## Launching the editor

```bash
# Blank show
python show-sync-editor.py

# Open an existing show file
python show-sync-editor.py my-show.json
```

The editor starts a local HTTP server on **http://127.0.0.1:5556** and opens
your default browser automatically.  Press **Ctrl+C** in the terminal to stop
the server.

---

## Loading a .mov reference video

1. Click **Load .mov** in the toolbar, *or*
2. Drag and drop a `.mov` (or `.mp4`, `.mkv`, etc.) file onto the video player.

The video appears in the **Reference Video** panel on the right.  Its duration
is used to set the timeline length.

You can also type a filename directly into the video path field if you prefer
to use a server-side path (the `/video?path=…` endpoint serves the file with
range-request support for seeking).

---

## Transport controls

| Control | Action |
|---------|--------|
| **▶ Play / ⏸ Pause** button | Play or pause the reference video |
| **Spacebar** | Toggle play/pause (when no text field is focused) |
| Scrub bar | Drag to seek; timeline playhead follows |
| Click on the timeline ruler | Seek to that position |
| **Drag on the timeline ruler** | Continuously scrub the playhead — hold mouse button and drag left or right to scrub; the video and preview update in real time |

---

## Creating clips

Use the **Add** buttons in the timeline toolbar to create a clip at the current
playhead position:

| Button | Clip type | Description |
|--------|-----------|-------------|
| **+ Solid** | `color` | Fills the screen with a solid colour for the duration |
| **+ Text** | `text` | Displays centred text above the colour layer |
| **+ Image** | `image` | Displays an image (by URL) over the preview |
| **+ Fade In** | `fade_in` | Fades from black into a colour over the duration |
| **+ Fade Out** | `fade_out` | Fades from a colour back to black over the duration |
| **+ Strobe** | `strobe` | Rapid on/off flashing at a configurable rate (Hz) |
| **+ Pulse** | `pulse` | Sine-wave opacity pulsing at a configurable rate (Hz) |
| **+ Glitch** | `glitch` | Position-jitter/shake effect with configurable intensity |
| **+ Blur In** | `blur` | Starts heavily blurred and sharpens to full clarity over the clip |
| **+ Sweep** | `color_sweep` | A colour that sweeps across the screen (four directions) |
| **+ Bounce** | `bounce` | Vertical sine-wave bounce at a configurable rate and amplitude |
| **+ Shake** | `shake` | Horizontal rapid shake at a configurable rate and amplitude |
| **+ Zoom** | `zoom_pulse` | Scale in/out pulsing at a configurable rate and amount |
| **+ HueRot** | `hue_rotate` | Continuously rotates the display hue at a configurable rate |
| **+ Glow** | `neon_glow` | Pulsing neon drop-shadow glow at a configurable size and rate |

Solid / fade clips go on the **Solids** track (layer 1).
Text clips go on the **Text** track (layer 10 — rendered on top).

---

## Moving and resizing clips

- **Drag the clip body** left or right to move it in time.
- **Drag the left edge handle** to change the clip's start time (and
  consequently its duration).
- **Drag the right edge handle** to change the clip's end time (duration).
- **Click a clip** to select it; selected clips are highlighted with a white
  outline.
- **Delete / Backspace** removes the selected clip.

---

## Editing clip properties

When a clip is selected, the **properties bar** at the bottom shows:

| Field | Notes |
|-------|-------|
| **Type** | Change the clip type (all fifteen types listed above) |
| **Start (s)** | Exact start time in seconds |
| **Duration (s)** | Length of the clip in seconds |
| **Beats (N BPM) →** | One-click beat presets: ¼ / ½ / 1 / 2 / 4 beats at the show's current BPM — sets Duration instantly |
| **Colour** | Background / text colour (colour picker) |
| **Text** | *(text clips only)* The text string to display |
| **Size (vmin)** | *(text clips only)* Font size in `vmin` units (1–30) |
| **Font** | *(text clips only)* Font family — 8 web-safe system stacks; empty = browser default |
| **Link URL** | *(text clips only)* Optional clickable URL — rendered as `<a href="...">` on client devices; allowed schemes: `http`, `https`, `mailto`, `tel` |
| **Image URL** | *(image clips only)* `http` / `https` URL of the image file |
| **Fit** | *(image clips only)* `Contain` (letterbox) / `Cover` (crop) / `Fill` (stretch) |
| **Rate (Hz)** | *(strobe / pulse / bounce / shake / zoom_pulse / hue_rotate / neon_glow)* Cycles or flashes per second |
| **Intensity (px)** | *(glitch only)* Maximum pixel offset for the jitter |
| **Max Blur (px)** | *(blur only)* Starting blur radius in pixels (reduces to 0 over the clip) |
| **Direction** | *(color_sweep only)* Sweep direction: → Left→Right, ← Right→Left, ↓ Top→Bottom, ↑ Bottom→Top |
| **Amplitude (px)** | *(bounce / shake only)* Peak displacement in pixels |
| **Amount** | *(zoom_pulse only)* Scale variation per cycle (0.2 = ±20% size change) |
| **Glow Size (px)** | *(neon_glow only)* Peak drop-shadow radius in pixels |
| **Fade In (s)** | Ramp-up time at the start of the clip (0 = instant) |
| **Fade Out (s)** | Ramp-down time at the end of the clip (0 = instant) |

---

## Five new live-show effects

The following effect types were added for live-performance contexts.  They are
available from the **FX** buttons in the timeline toolbar and from the **Type**
dropdown in the properties bar.

### 1 — Strobe (`strobe`)

Rapid on/off flashing at a configurable frequency.

| Param | Default | Notes |
|-------|---------|-------|
| `color` | `#ffffff` | Flash colour |
| `rate` | `10` | Flashes per second (Hz) — each flash = one on + one off cycle |

**Live rendering:** toggles the display between `color` and black at `rate` Hz
with a 50 % duty cycle (equal on/off time).  Fade in/out is applied as an
opacity envelope across the whole clip.

### 2 — Pulse (`pulse`)

Smooth sine-wave opacity cycling.

| Param | Default | Notes |
|-------|---------|-------|
| `color` | `#ffffff` | Pulse colour |
| `rate` | `1` | Full oscillation cycles per second (Hz) |

**Live rendering:** opacity = `0.5 + 0.5 × sin(2π × pos × rate)` — ranges from
0 to 1 over each cycle, creating a smooth breathing or heartbeat effect.

### 3 — Glitch (`glitch`)

Rapid position-jitter using deterministic pseudo-random offsets.

| Param | Default | Notes |
|-------|---------|-------|
| `color` | `#ff4040` | Fill colour during jitter |
| `intensity` | `8` | Maximum pixel displacement (x and y) |

**Live rendering:** applies `transform: translate(dx, dy)` each frame where
`dx = sin(pos × 137.5) × intensity` and `dy = cos(pos × 89.3) × intensity`.
The displacement is multiplied by the fade-in/fade-out opacity envelope so the
jitter can be ramped in or out naturally.

### 4 — Blur In (`blur`)

Screen starts heavily blurred and gradually sharpens to full clarity.

| Param | Default | Notes |
|-------|---------|-------|
| `color` | `#ffffff` | Background colour shown through the blur |
| `max_blur` | `20` | Starting blur radius in pixels; decreases linearly to 0 |

**Live rendering:** applies `filter: blur(Npx)` where N decreases from
`max_blur` to 0 over the clip duration.  Combine with a `fade_out` clip
underneath for a sharp→blurry-exit effect.

### 5 — Color Sweep (`color_sweep`)

A solid colour that sweeps across the screen from one side.

| Param | Default | Notes |
|-------|---------|-------|
| `color` | `#ff0000` | Sweep colour |
| `direction` | `lr` | `lr` left→right, `rl` right→left, `tb` top→bottom, `bt` bottom→top |

**Live rendering:** uses `clip-path: inset(…)` to reveal the colour block
progressively from 0 % to 100 % over the clip duration.

---

## Five additional live-show effects (2nd set)

The following five effect types extend the available FX palette.  They are
available from the **FX** buttons in the timeline toolbar and from the **Type**
dropdown in the properties bar.

### 6 — Bounce (`bounce`)

Colour block that bounces vertically using a sine-wave displacement.

| Param | Default | Notes |
|-------|---------|-------|
| `color` | `#ff4080` | Fill colour |
| `rate` | `1` | Bounce cycles per second (Hz) |
| `amplitude` | `30` | Peak vertical displacement in pixels |

**Live rendering:** applies `transform: translateY(…px)` each frame where the
offset = `sin(2π × pos × rate) × amplitude × opacity_envelope`.

### 7 — Shake (`shake`)

Rapid horizontal shake — useful for impact hits and stingers.

| Param | Default | Notes |
|-------|---------|-------|
| `color` | `#8040c0` | Fill colour |
| `rate` | `4` | Shake cycles per second (Hz) |
| `amplitude` | `15` | Peak horizontal displacement in pixels |

**Live rendering:** applies `transform: translateX(…px)` with a sine function,
scaled by the fade-in/fade-out envelope.

### 8 — Zoom Pulse (`zoom_pulse`)

Rhythmically scales the display in and out like a heartbeat or camera zoom.

| Param | Default | Notes |
|-------|---------|-------|
| `color` | `#40c080` | Fill colour |
| `rate` | `1` | Scale cycles per second (Hz) |
| `amount` | `0.2` | Scale variation (0.2 = ±20 % size per cycle) |

**Live rendering:** applies `transform: scale(…)` where scale = `1 + amount × sin(2π × pos × rate)`.

### 9 — Hue Rotate (`hue_rotate`)

Continuously cycles the display colour through the full hue wheel.

| Param | Default | Notes |
|-------|---------|-------|
| `color` | `#ff6000` | Base colour (rotated through 360 °) |
| `rate` | `0.5` | Full hue-wheel revolutions per second |

**Live rendering:** applies `filter: hue-rotate(Ndeg)` where N = `pos × rate × 360` (mod 360),
producing a smooth rainbow colour-cycling effect.

### 10 — Neon Glow (`neon_glow`)

Pulsing neon drop-shadow glow — great for logo reveals and transitions.

| Param | Default | Notes |
|-------|---------|-------|
| `color` | `#00d0ff` | Glow and fill colour |
| `size` | `20` | Peak glow radius in pixels |
| `rate` | `2` | Glow pulse cycles per second (Hz) |

**Live rendering:** applies `filter: drop-shadow(0 0 Npx color)` where N = `size × (0.5 + 0.5 × sin(2π × pos × rate))`,
ranging from 0 to `size` px over each cycle.

---

## BPM-aware timing

### Setting the show BPM

The **BPM** field in the toolbar (default **120**) stores the tempo in the
show file (`show.bpm`).  It is used exclusively for the beat-duration helper;
it does not affect the audio or video playback rate.

When you load a show file that contains a `bpm` key, the input is updated
automatically.  When you start a new show, it resets to 120.

### Beat-duration presets

When a clip is selected, the properties bar shows a row of beat-duration
buttons labelled **¼ ½ 1 2 4**.  Clicking one sets the clip's **Duration (s)**
field to the equivalent number of seconds at the current BPM:

```
duration_seconds = round(beats × 60 / BPM × 1000) / 1000
```

| Button | Beats | At 120 BPM | At 128 BPM |
|--------|-------|-----------|-----------|
| **¼** | 0.25 | 0.125 s | 0.117 s |
| **½** | 0.5  | 0.250 s | 0.234 s |
| **1** | 1    | 0.500 s | 0.469 s |
| **2** | 2    | 1.000 s | 0.938 s |
| **4** | 4    | 2.000 s | 1.875 s |

The tooltip on each button shows the exact seconds value for the current BPM.

### Show file format (BPM field)

The `bpm` key is stored at the top level of the show JSON and is backward
compatible — older show files without it default to 120 in the editor.

```json
{
  "version": 2,
  "bpm": 128,
  "media": { "type": "video", "src": "my-show.mov", "duration": 185.2 },
  "tracks": [ ... ]
}
```

### Example: four-beat strobe at 128 BPM

1. Click **+ Strobe** at the desired playhead position.
2. Select the new clip; it defaults to 2 s / 10 Hz / white.
3. In the properties bar click **4** in the beats row → Duration becomes 1.875 s (4 beats at 128 BPM).
4. Change Rate (Hz) to `8` for a slightly slower strobe.
5. Save the show.

---

## Device viewport preview

### Overview

The **Preview** panel (left of the media area) renders an accurate scale-to-fit
representation of how the show will appear on a real phone screen.  The inner
canvas is sized to the **logical pixel dimensions** of the selected device and
then scaled down to fit the available panel space while preserving the aspect
ratio.

The preview panel is **280 px wide** and the media area is **480 px tall** by
default, giving a large, easy-to-read view of the phone screen on most desktop
displays.

This means that font sizes, padding, and element proportions in the preview
match the client device exactly — content that fits on one line on an iPhone 14
will also fit on one line in the preview.

### Selecting a device preset

Click the **preset dropdown** in the preview panel header to choose a device:

| Preset | Logical size (portrait) |
|--------|------------------------|
| iPhone SE | 375 × 667 |
| **iPhone 14** *(default)* | 390 × 844 |
| iPhone 14 Plus | 428 × 926 |
| iPhone 14 Pro Max | 430 × 932 |
| iPhone 15 Pro | 393 × 852 |
| iPhone 16 Pro Max | 440 × 956 |
| Android S | 360 × 800 |
| Android M — Pixel 7 | 412 × 915 |
| Android L — S22 Ultra | 384 × 854 |

The active dimensions (width × height) are shown to the right of the dropdown.

### Orientation toggle

Click the **↻** button to switch between portrait and landscape.  The device
dimensions are swapped (width ↔ height) and the preview is redrawn immediately.
Click again to return to portrait.

### WYSIWYG font-size behaviour

Text clip **Size (vmin)** values are translated to device-pixel sizes in the
preview:

```
preview_font_px = (size_vmin / 100) × min(device_width, device_height)
```

For example, `Size = 5` on an iPhone 14 portrait (390 × 844) renders as:

```
5 / 100 × 390 = 19.5 px
```

On the real client device the browser interprets `5vmin` identically (since
`1vmin = 1 % of the viewport's shorter dimension`), so the preview is a true
pixel-for-pixel representation.

> **Note:** minor rendering differences (subpixel font hinting, OS default
> font metrics) may cause slight visual variations between the preview and a
> physical device, but proportions and line-breaking behaviour will be accurate.

---

## Link support in text clips

Text clips can optionally include a **Link URL** so that the text appears as a
clickable hyperlink on the client device.

### Adding a link

1. Select a **text** clip on the timeline.
2. In the properties bar, fill in the **Link URL** field with a full URL:
   - `https://example.com`
   - `mailto:user@example.com`
   - `tel:+441234567890`
3. Press **Tab** or **Enter** — the URL is validated immediately.
   - Invalid or unsafe URLs (including `javascript:`) are silently rejected and
     the field is cleared.

### Removing a link

Clear the **Link URL** field and press **Tab** or **Enter**.  The `link_url`
key is removed from the clip's `params` object.

### Allowed URL schemes

| Scheme | Example | Notes |
|--------|---------|-------|
| `https:` | `https://example.com/page` | Standard secure web link |
| `http:` | `http://192.168.1.10:8000/` | Plain web link (LAN / internal) |
| `mailto:` | `mailto:band@venue.com` | Opens email client |
| `tel:` | `tel:+441234567890` | Opens phone dialler |

All other schemes (including `javascript:`, `data:`, `vbscript:`) are rejected.

### Show file format (link_url field)

The link URL is stored inside the clip's `params` object:

```json
{
  "id": "def67890",
  "type": "text",
  "start": 13.0,
  "duration": 2.0,
  "params": {
    "text": "Visit our site",
    "color": "#ffffff",
    "size": 5,
    "link_url": "https://example.com"
  },
  "fade_in": 0.1,
  "fade_out": 0.2
}
```

Clips without a `link_url` key render as plain text (backward compatible).

### Client-side rendering

On the live show-sync client (`join.html` / `client.js`), text clips with a
`link_url` are rendered as:

```html
<a href="https://example.com" style="color:#ffffff;text-decoration:underline;">
  Visit our site
</a>
```

The anchor is styled with `color: inherit` so it picks up the clip's text colour,
and `text-decoration: underline` to indicate it is clickable.

---

## Font selection in text clips

### Font strategy

The editor uses **web-safe / system font stacks** only.  No external fonts are
downloaded at runtime, so every font listed below renders consistently on every
browser and operating system without requiring network access.

### Available fonts

| Font id | Label | Characteristics |
|---------|-------|-----------------|
| *(empty)* | Default (system UI) | Inherits the browser/OS system font — most neutral choice |
| `sans` | Sans-serif | `-apple-system`, Segoe UI, Roboto, Helvetica, Arial — renders as the system sans-serif on every platform |
| `serif` | Serif | Georgia, Times New Roman — classic document serif |
| `mono` | Monospace | Courier New — fixed-width; good for code or numbers |
| `impact` | Impact | Bold condensed display font — high-impact headlines |
| `georgia` | Georgia | Georgia / Palatino — elegant serif, wide device coverage |
| `verdana` | Verdana | Wide letter-spacing, good on small screens |
| `trebuchet` | Trebuchet MS | Humanist sans; legible at many sizes |

### Adding a font to a text clip

1. Select a **text** clip on the timeline.
2. In the properties bar, click the **Font** dropdown.
3. Choose a font — the preview updates immediately.
4. Save the show; the `font_family` key is stored in `params`.

### Backward compatibility

Clips without a `font_family` key (created before this feature) continue to
render using the browser default.  The `font_family` field defaults to `''`
(empty), which resolves to the system UI font.

### Show file format (font_family field)

```json
{
  "id": "txt001",
  "type": "text",
  "start": 4.0,
  "duration": 3.0,
  "params": {
    "text": "IGNITE",
    "color": "#ff8800",
    "size": 10,
    "font_family": "impact"
  },
  "fade_in": 0.2,
  "fade_out": 0.2
}
```

---

## Image clips

### Overview

The `image` clip type displays an external image (JPEG, PNG, WebP, GIF) over
the preview for the clip's duration.  Images are inserted by URL and rendered
in the same WYSIWYG preview used for colour and text clips.

### Adding an image

1. In the timeline toolbar click **+ Image**.  A new image clip is placed at
   the current playhead on the **Text** track (layer 10, above solids).
2. Click the clip to select it.
3. In the properties bar fill in **Image URL** with a full `http://` or
   `https://` URL pointing to the image file.
4. Press **Tab** or **Enter**.  The URL is validated and the preview updates.
5. Choose a **Fit** mode:
   - **Contain (letterbox)** *(default)* — scales the image to fit inside the
     preview while preserving its aspect ratio; may show black bars.
   - **Cover (crop)** — fills the full preview, cropping the image if necessary.
   - **Fill (stretch)** — stretches the image to fill exactly.
6. Optionally adjust **Fade In (s)** and **Fade Out (s)** in the properties bar.
7. Save the show.

### URL validation and safety

Only `http:` and `https:` image URLs are accepted.  `data:`, `blob:`,
`javascript:`, and other schemes are silently rejected and the field is cleared.
The URL is always re-serialised through the browser's URL parser before it is
stored, so the saved URL is always in canonical form.

### Fit modes

| Mode | Object-fit | When to use |
|------|-----------|-------------|
| Contain | `contain` | Logos, graphics with transparency or fixed aspect ratio |
| Cover | `cover` | Full-screen hero images where cropping is acceptable |
| Fill | `fill` | Pixel-perfect banners sized exactly for the device |

### Show file format (image clip)

```json
{
  "id": "img001",
  "type": "image",
  "start": 10.0,
  "duration": 5.0,
  "params": {
    "src": "https://cdn.example.com/banner.webp",
    "fit": "contain"
  },
  "fade_in": 0.5,
  "fade_out": 0.5
}
```

### Load-status indicator

While an image clip is selected, a small status line appears in the properties
bar after the **Fit** control:

- **⏳ loading…** — image is being fetched.
- **800×600px ✓** — loaded successfully; dimensions are within recommended range.
- **2400×1600px ⚠ large — consider resizing to ≤800px** — image is large;
  see the performance recommendations below.
- **✗ could not load** — the URL returned an error (check the URL and CORS policy).

### Performance recommendations for live use

Images add network and memory overhead.  Follow these guidelines for smooth
playback, especially on phones:

| Recommendation | Detail |
|---------------|--------|
| **Format** | Use **WebP** (best quality/size) or optimised JPEG.  Avoid uncompressed PNG for photographs. |
| **Dimensions** | Resize to ≤ **800 px** on the longest edge before use.  Phone previews are ~390–440 logical pixels wide; a 2 MP image is wasted and slows rendering. |
| **File size** | Aim for ≤ **150 KB** per image.  On a 50 Mbps connection a 150 KB image loads in ~24 ms; a 2 MB image takes ~320 ms — risking a visible blank frame at show time. |
| **Hosting** | Use images served from a fast, reliable host (CDN, local server, or `show-sync/app/static/`).  Remote images from social media or slow third-party hosts are unpredictable under show conditions. |
| **Preloading** | The editor automatically preloads all image URLs in the show when a show file is opened.  This populates the browser cache so images are ready before playback.  Open the show file a few seconds before triggering playback to allow preloading to complete. |
| **CORS** | The image server must send appropriate `Access-Control-Allow-Origin` headers if the image is cross-origin (different domain from the show-sync server). |

### Cross-browser rendering notes

- `object-fit: contain/cover/fill` is supported in all modern browsers (Chrome,
  Safari, Firefox, Edge — including mobile).
- Images fetched from a different origin than the show-sync server may be blocked
  by the browser's CORS policy.  Host images on the same server or configure
  the CDN/image host to allow `Access-Control-Allow-Origin: *`.
- Animated GIFs are rendered by the browser natively; however, large animated
  GIFs (> 500 KB) can cause jank on older phones — prefer short WebP animations.

---

## Zoom

Use the **Zoom − / +** buttons in the timeline toolbar to increase or decrease
the pixels-per-second scale.  The default is 50 px/s.

---

## Exporting (saving) the show file

Click **Save Show** (or press **Ctrl+S** / **⌘S**) to download the show as a
`.json` file.

If the editor was opened with an existing file on the command line, it will
attempt to save back to that path via the server; otherwise it triggers a
browser download.

### Show file format (v2)

```json
{
  "version": 2,
  "media": {
    "type": "video",
    "src": "my-show.mov",
    "duration": 185.2
  },
  "tracks": [
    {
      "id": "t1",
      "name": "Solids",
      "layer": 1,
      "clips": [
        {
          "id": "abc12345",
          "type": "color",
          "start": 12.2,
          "duration": 3.5,
          "params": { "color": "#ff0000" },
          "fade_in": 0.2,
          "fade_out": 0.5
        }
      ]
    },
    {
      "id": "t2",
      "name": "Text",
      "layer": 10,
      "clips": [
        {
          "id": "def67890",
          "type": "text",
          "start": 13.0,
          "duration": 2.0,
          "params": { "text": "GO", "color": "#ffffff", "size": 5 },
          "fade_in": 0.1,
          "fade_out": 0.2
        }
      ]
    }
  ]
}
```

---

## Importing (loading) a show file

Click **Load Show** and choose a `.json` file.

The editor supports both:
- **v2 format** (tracks + clips, as above)
- **v1 legacy format** (flat `"effects"` list from the old Tkinter editor) —
  automatically migrated to v2 on load.

---

## Playing a show back through show-sync

### 1 — Start the show-sync server

```bash
cd show-sync
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 2 — Create a session

```bash
curl -X POST http://localhost:8000/api/session \
     -H 'Content-Type: application/json' \
     -d '{"name": "my-show"}'
# → {"session_id": "a1b2c3d4", "join_url": "/join/a1b2c3d4"}
```

### 3 — Open the join URL on client devices

```
http://<server-ip>:8000/join/a1b2c3d4
```

### 4a — Timeline playback (v2, recommended)

```bash
curl -X POST "http://localhost:8000/api/session/a1b2c3d4/play-timeline?offset=5" \
     -H 'Content-Type: application/json' \
     -d @my-show.json
```

The server broadcasts `show_load` + `show_start` to all connected clients.
Each client runs its own rAF composite loop, evaluating clips at the
synchronised show time.

### 4c — Play a show by name (from the shows library)

Place exported show JSON files in `show-sync/app/static/shows/`.  They are
served statically and can be triggered by name without uploading the JSON body
on each call — ideal for scripted control from `live_controller`.

**List available shows:**

```bash
curl http://localhost:8000/api/shows
# → {"shows": ["A_storm_is_coming.json", "outro.json"]}
```

**Trigger a named show (legacy relative offset):**

```bash
curl -X POST "http://localhost:8000/api/session/a1b2c3d4/play-show-by-name?name=A_storm_is_coming.json&offset=5"
```

**Trigger a named show with absolute-time scheduling (recommended):**

Pass `start_at` as a Unix timestamp (seconds, float) for the exact wall-clock
moment when show time = 0 begins.  Both the server and all clients wait until
that instant before starting the animation loop, eliminating the network-latency
error that accumulates with a relative offset.

```bash
# start_at = Unix timestamp 2 seconds in the future
START=$(python -c "import time; print(f'{time.time()+2:.6f}')")
curl -X POST "http://localhost:8000/api/session/a1b2c3d4/play-show-by-name?name=A_storm_is_coming.json&start_at=$START"
```

`live_controller` uses this mode automatically for all sync-enabled setlist
items.  It computes `target_start = now + preload_time`, sends the request
with `start_at=target_start`, and starts the local MIDI pre-roll immediately
so the video unpauses at exactly `target_start`.  The pre-roll window
(typically 2–8 s) is sufficient lead time for the HTTP request to arrive via
Tailscale well before show time = 0.

**Preload a show on the client via query parameter:**

Append `?show=<filename>` to the join URL.  The client fetches the show JSON
from `/static/shows/` immediately on load so it is ready before the server
sends `show_start`.

```
http://<server-ip>:8000/join/a1b2c3d4?show=A_storm_is_coming.json
```

### 4b — Legacy cue playback (v1)

```bash
curl -X POST "http://localhost:8000/api/session/a1b2c3d4/play-show?offset=5" \
     -H 'Content-Type: application/json' \
     -d @my-show.json
```

### 5 — Stop the show

```bash
curl -X POST http://localhost:8000/api/session/a1b2c3d4/stop
```

---

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| **Space** | Play / Pause |
| **← Left arrow** | Step playhead back by the configured nudge amount |
| **→ Right arrow** | Step playhead forward by the configured nudge amount |
| **Delete** or **Backspace** | Delete selected clip (or selected marker if no clip is selected) |
| **Ctrl+S** / **⌘S** | Save show |
| **Ctrl+C** / **⌘C** | Copy selected clip (text or solid) |
| **Ctrl+V** / **⌘V** | Paste copied clip at current playhead |
| **m** | Add a marker at the current playhead position |

> **Arrow key step size** — the **Step** and **fps** inputs in the transport
> bar control how far each arrow-key press moves the playhead.  The default is
> **1 frame at 25 fps** (= 40 ms).  Change *Step* to nudge by multiple frames
> at once, or change *fps* to match your source material (e.g. 24, 30, 60).
> Arrow keys have no effect while a text/number input field is focused.

---

## Copy / Paste clips

1. Click a **text**, **image**, or **solid/colour** clip to select it.
2. Press **Ctrl+C** (or **⌘C** on Mac) to copy it.
   - The full clip is copied: type, duration, colour, text, font, image URL, size, fade in/out.
3. Seek or play to the position where you want the duplicate.
4. Press **Ctrl+V** (or **⌘V**) to paste.
   - A new clip is placed with its start at the **current playhead position**.
   - All other properties are identical to the original.
   - The pasted clip is automatically selected so you can adjust it immediately.

---

## Timeline markers

Press **`m`** at any time (the timeline does not need to be playing) to drop an amber
marker at the current playback position.

- Markers appear as **amber (yellow) vertical lines** on the timeline ruler and
  on every track lane.
- A small time label is drawn at the top of the ruler for each marker.
- Markers are saved with the show file (`"markers"` key in the JSON).

### Deleting markers

There are two ways to remove a marker:

1. **Inline × button** — hover over the ruler; a small **×** button appears at
   the top of each marker.  Click the **×** to delete that marker immediately.

2. **Click + Delete key** — click on the marker line in the ruler to select it
   (it turns bright orange to confirm selection), then press **Delete** or
   **Backspace** to remove it.

Deleting a marker updates the show state immediately and is reflected in saved
show files on the next **Save Show**.

### Snapping clips to markers

When you **drag** a clip or **resize** it by its handles, the clip's moving edge
will **snap** to the nearest marker if it comes within ~8 px of it at the current
zoom level.

- Moving a clip: the **start edge** snaps to nearby markers.
- Resizing from the left handle: the **start** snaps.
- Resizing from the right handle: the **end** snaps.

This makes it easy to align clip boundaries to musical or visual cue points that
you marked while the show was playing.

> **Tip:** mark cue points first (let the show play, press `m`), then drag clips
> onto those positions — they will lock in cleanly.

---

## Architecture notes

- `show-sync-editor.py` — Python stdlib HTTP server (no extra dependencies).
- `show-sync-editor.html` — Self-contained browser editor (HTML + CSS + JS).
- `show-sync/app/main.py` — FastAPI server; new `/play-timeline` and `/stop`
  endpoints added alongside the existing `/play-show` legacy endpoint.
- `show-sync/app/static/client.js` — Updated to handle `show_load`,
  `show_start`, `show_stop` messages in addition to the legacy `cue` protocol.
- `show-sync/app/templates/join.html` — Text overlay moved to its own `z-index`
  layer above the colour display; font size is now dynamic per clip.
