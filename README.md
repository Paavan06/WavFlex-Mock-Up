# WavFlex Product Tagging (UI mock)

Standalone mock of the planned **product / brand tagging** feature for WavFlex:
pick a video or image, and see which products and brands appear on screen
at each timestamp (for example, a ZUS Coffee cup on the table at 00:42).

> **All detections are fake.** No AI model is called. Results are generated
> from the file name, so the same file always gives the same results, which
> makes demos repeatable. For videos, the preview shows the **real frame**,
> pulled with FFmpeg, with fake boxes drawn on top.

This is separate from the main WavFlex app (`../wavflex`) and doesn't share
any code or data with it.

## Run

Needs Python 3.10+ and FFmpeg on PATH.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

## What the screen shows

1. **Choose media**: a video or image, or **Use demo video** (no file needed).
2. **Settings**: frame sampling interval (1, 2, 5 or 10 s), plus the brand catalogue being watched.
3. **Analyze products**: fake progress (extract frames → detect → match logos → timeline).
4. **Results**:
   - summary cards
   - frame preview with labelled boxes
   - "Brands found" with screen time
   - per-brand timeline (click to jump)
   - detections table with brand and confidence filters and Confirm / Reject review
   - Export CSV (to `exports/`)

## Files

| File | Purpose |
|---|---|
| `main.py` | Window plus WavFlex-style header |
| `product_tagging.py` | The whole Product Tagging screen, mock catalogue and mock detection generator |
| `assets/wavflex.png` | Logo (copied from WavFlex) |

## Making it real later

Replace `ProductTaggingView._generate_mock_detections()` with real per-frame
detection. Frame extraction (`_frame_for`) already works. For each sampled
frame, send it to Gemini (`google-genai`) with the brand catalogue and ask for
JSON (`brand, product, confidence, box`).
