# MICA HUD design QA

## Comparison target

- Source visual truth: `C:/Users/kochn_lrehka5/Desktop/Mica V2/Codex-Bild 3. Sept. 2026, 19_36_36.png`
- Rendered implementation: `C:/Users/kochn_lrehka5/Desktop/Mica V2/artifacts/mica-hud-current-ready.png`
- Full comparison: `C:/Users/kochn_lrehka5/Desktop/Mica V2/artifacts/mica-hud-comparison-ready.png`
- Audio-reactive proof: `C:/Users/kochn_lrehka5/Desktop/Mica V2/artifacts/mica-hud-audio-reactive.png`
- Viewport: 1600 x 990 CSS pixels, offscreen Qt renderer, density 1x.
- Source pixels: 1600 x 990. Implementation pixels: 1600 x 990. No density normalization was needed.
- State: listening, with no saved reminder and no saved project. This intentionally exercises the real empty states instead of the reference's example cards.

## Evidence reviewed

The full comparison places the source and current implementation side-by-side at identical 1600 x 990 pixels. It verifies the full-height left rail, central listening surface, floating lower composer and inset right context panel. The audio-reactive proof verifies the generated Mica orb, its protected transparent edge, state copy placement and the shared live audio value driving the central aura plus all three visible waveforms.

The implementation was also rendered at 960 x 680 in `artifacts/mica-hud-minimum.png`. At that width the decorative composer waveforms collapse, while the microphone, text input, send control, navigation and context remain reachable.

## Comparison history

1. **P1 – opaque dark disk around the generated portrait.** The first render revealed that the image masking routine replaced the asset alpha channel. The mask now multiplies the existing alpha channel, preserving the transparent edge. Post-fix evidence: `artifacts/mica-hud-current-ready.png`.
2. **P2 – side columns ended above the lower reference boundary.** The composer was initially allocated as a horizontal layout row. It is now a centre-only floating child, so the left rail and right context panel remain full-height. Post-fix evidence: `artifacts/mica-hud-comparison-ready.png`.
3. **P2 – centre state sat too low and the aura was clipped.** The portrait remains high like the source while the larger ribbon field now has its own lower centre and calibrated radius. The white radial surface, rail rhythm and context-card heights were also matched in the final comparison. Post-fix evidence: `artifacts/mica-hud-comparison-ready.png`.
4. **P2 – brand and microphone assets did not match the visual language.** The rail now uses the four-diamond MICA mark extracted from the provided reference, while the round control uses dedicated microphone and muted-microphone image assets. Post-fix evidence: `artifacts/mica-hud-current-ready.png`.

## Fidelity surfaces

- **Fonts and typography:** Uses Segoe UI with normal Qt fallbacks and a clear display/body hierarchy. The final offscreen Windows proofs render all primary text without replacement glyphs.
- **Spacing and layout rhythm:** The 164 px rail, broad central canvas, 320 px inset context region and 850 px maximum composer align to the reference proportions. The user avatar has no widget or asset placement in the rail.
- **Colors and tokens:** White, pale-blue surfaces, low-contrast blue aura lines, subtle borders and state colours map to the supplied light reference.
- **Image quality and asset fidelity:** `assets/mica-orb-v2.png` is a dedicated high-resolution, transparent Mica portrait, rendered with smooth scaling. It intentionally replaces the source's generic face with the requested Mica asset while retaining the same small central placement.
- **Icons and controls:** Navigation and composer controls use native Qt icon assets rather than emoji. Buttons retain keyboard focus styles and accessible names.
- **Copy and content:** Context data is never fabricated: it derives from connection/state, supplied audio level, locally indexed reminders and real `projects` memory. Empty cards are explicit.
- **Interactions and accessibility:** Chat, history and settings navigation switch real states; settings exposes the existing audio menu; F4 and the round microphone control share mute state; Esc is unchanged. Reduced motion can be toggled in settings and is persisted in configuration.

## Primary interactions tested

- Navigation: chat, history and settings drawer.
- State changes: listening, thinking, speaking and muted.
- Live-level propagation to aura, context waveform and composer waveforms.
- Physical Windows microphone capture at the application's 16 kHz mono input rate.
- Text send callback and input clearing.
- File ingestion through the composer drop target without a visible upload panel.
- Project and reminder empty states; reminder index future filtering.
- Render at reference and minimum viewport.

The physical Windows microphone probe ran through `tests/manual_physical_audio_probe.py` at the application's 16 kHz mono rate. It read 47 live blocks from the selected Buds3 Pro microphone, observed 40 non-zero HUD-level blocks, no overflows, a peak RMS of 176.785 and a peak normalized HUD level of 0.045978. PCM was discarded block-by-block and no raw audio was saved. The measured value was delivered through `JarvisUI.set_audio_level()` and rendered in `artifacts/mica-hud-physical-mic.png`; `artifacts/mica-hud-audio-reactive.png` separately proves the same visual path at a high level.

## Findings

No actionable P0, P1 or P2 differences remain for the requested HUD target. The generated portrait is intentionally more characterful than the generic reference face, per the requested Mica asset.

## Follow-up polish

- [P3] Optional: repeat the privacy-preserving probe while speaking to capture a higher-amplitude reference frame for documentation. The physical input and shared HUD path are already proven.

## Implementation checklist

- [x] Remove the lower-left user avatar.
- [x] Build functional navigation, context, floating composer and audio-reactive aura.
- [x] Add local reminder index and memory-backed project card.
- [x] Add PyQt contract tests and reference/minimum renders.

final result: passed
