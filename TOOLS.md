# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

### Diamondback tape analysis

- Preset runner: `/root/.openclaw/workspace/scripts/run_diamondback_tape_analysis.py`
- Default source remote: `dropbox:OpenClaw/inbox/UEA/Diamondback`
- Default local inbox: `/root/.openclaw/dropbox/inbox/UEA/Diamondback`
- Default SOW template: `/root/.openclaw/dropbox/inbox/SOW_Templates/CSI_SOW_ TEMPLATE 31 March 2020.docx`
- Default upload target: `dropbox:OpenClaw/output/UEA/Diamondback/<batch-id>/`
- Purpose: pull the current Diamondback batch, exclude prior review docs and `old quotes - do not use`, run a non-comparative analysis, build a templated SOW-style `summary.docx` with cover page and table of contents, then upload the outputs back to Dropbox.
- If Mark asks to “run the Diamondback tape analysis”, use this runner.

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.
