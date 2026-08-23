

# Clair image consistency protocol (CR, 2026-08-23)

## 1. Master references (the only ground truth)
- `~/Desktop/2ndBRAIN/Clair/Claire_Lindqvist_MASTER.png` = original *evening* shot (black satin gown, dim luxury bar, looking over shoulder). Face + body + mood reference. CR: "이거가 제일 마음에 드는 사진들이야", "이브닝이 좋아".
- `~/Desktop/2ndBRAIN/Clair/Claire_Lindqvist_MASTER_back.png` = original *back* shot. Back-view reference.
- Also kept: `Claire_Lindqvist_front.png`, `_evening.png`, `_back.png` (originals). Everything else was deleted by CR.
- Never generate from text only. Always `images.edit` (OpenAI gpt-image-2, or Gemini/nano-banana Pro with 2–3 reference images once billing is on) with MASTER as input; for back views also pass MASTER_back.

## 2. Fixed identity (paste verbatim)
"Claire Lindqvist, 32, tall Swedish woman, 173cm, slender with long legs and elegant model proportions exactly as the reference; Nordic angelic face, white-blonde wavy hair, light freckles, serene expression — identical to the reference photo."

## 3. Prompt template
```
Same woman as the reference photo. Keep her face, hair, freckles, body and proportions EXACTLY as the reference. {IDENTITY}
High-fashion editorial photograph (Vogue level): professional model posture and posing, refined styling, cinematic lighting, 85mm lens, full body head-to-toe, camera slightly below eye level so she reads tall.
{VIEW: front / three-quarter / back looking over shoulder}
Scene: {elegant scene — evening wear, luxury interior, golden-hour terrace, rooftop at dusk, gala, hotel suite, gallery}.
Tasteful, fully clothed. Change nothing about her.
```

## 4. Forbidden (caused the "worst" results)
- Body words: fuller, curvier, glamorous figure, hourglass, bust, hips, slim/thick — ANY body descriptor beyond "exactly as the reference".
- Casual/snapshot scenes: music studio, cafe, t-shirt & jeans, headphones, mixing console, street casual.
- Chest-height or wide-angle close framing (makes her look short/heavy).
- Combining multiple changes in one prompt.

## 5. Change policy (CR: "아주 조금씩", "기준점에서 앞으로")
- One attribute, one small step, everything else identical to MASTER → show CR → he says 좋아/덜/더 → next step.
- Goal: gradually sculpt toward his ideal (조금씩 더 이상적으로 성형).
- When CR accepts a step: save as `Clair/MASTER_v{N}_{YYYY-MM-DD}.png`, copy to `Claire_Lindqvist_MASTER.png`, log the change in `Clair/CHANGELOG.md` (what changed, from which version). Keep every version.

## 6. Review loop
- After each batch: embed ≤700px JPEGs in an HTML gallery artifact with the MASTER beside the new images so CR compares directly.
- Ask one question only: "기준점 대비 어때요? 좋아/덜/더".

## 7. Engines & cost
- Default OpenAI gpt-image-2 `images.edit`, 1024x1536, quality medium, ≈₩90/img, 5/min (sleep 13s between).
- Gemini key (`GEMINI_API_KEY` in .env) works for text but image models return 429 on free tier — needs billing. When on: nano-banana Pro for key shots (multi-reference).
- Future: local LoRA on CR's planned workstation ([[cr-ai-server-plan]]).

See [[clair-persona]], [[clair-companion-vision]].
