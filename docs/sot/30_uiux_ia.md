# MDP v0.1 UI/UX and IA (SoT)

Document ID: `SOT-30`  
Version: `v0.1`  
Status: `Approved baseline`

## 1) Brand source of truth policy

### UX-001 Brand SoT assets and path strategy
- Input: Any request to use or update brand assets.
- Output:
  - Root files `logo.png` and `signature.jpg` are the sole source of truth.
  - Deployment copies to public paths are allowed only as derived artifacts.
  - All updates must originate from root SoT files.
- Boundary: Rename, move, re-encode, or replacing SoT path by public copy.
- Acceptance method: Release checklist verifies asset lineage and unchanged SoT paths.

## 2) Brand System: three logo forms

### UX-002 Primary logo
- Input: Major brand surface (landing hero, report cover, formal header block in reports).
- Output: Use Primary logo at standard aspect ratio and clear space.
- Boundary: Tiny surfaces where readability drops below acceptable threshold.
- Acceptance method: Visual QA against approved usage surfaces and minimum size rules.

### UX-003 Badge logo
- Input: Medium-compact surfaces (section badges, share thumbnails, compact cards where full primary is too wide).
- Output: Use Badge logo variant preserving shape and contrast.
- Boundary: Overcrowded backgrounds, stretched or distorted scaling.
- Acceptance method: Snapshot inspection across representative medium-size surfaces.

### UX-004 Micro logo
- Input: Very small surfaces (favicon-like marks, dense metadata blocks).
- Output: Use Micro logo variant only where 16/24/32px readability is required.
- Boundary: Use in large hero areas where Micro is visually weak.
- Acceptance method: 16/24/32px readability test and context-appropriateness review.

### UX-005 Logo prohibited usage
- Input: Logo placement and transformations.
- Output: The following are prohibited: distortion, unapproved recolor, insufficient contrast, overlay on noisy backgrounds without support plate.
- Boundary: Near-threshold contrast and extreme crop.
- Acceptance method: Brand compliance checklist on all key templates.

## 3) Signature placement rules

### UX-006 Signature allowed positions
- Input: Page/card type requiring signature presence.
- Output: Signature is allowed only on:
  - Proof Card
  - Buyout certificate
  - Report cover or report ending page
  - Footer (subtle treatment)
- Boundary: Ambiguous mixed-layout templates.
- Acceptance method: Template-by-template placement audit against allowlist.

### UX-007 Signature prohibited positions
- Input: Header/Nav/general card template rendering.
- Output: Signature must not appear in:
  - Header
  - Navigation
  - Every card in grid/list
- Boundary: Shared layout components reused across pages.
- Acceptance method: Global UI scan confirms prohibited zones remain signature-free.

## 4) Proof Card and OG specification

### UX-008 Proof Card/OG required fields
- Input: Proof Card or OG card generation request.
- Output: Card must include `proof_id`, `method_version`, and `timestamp`.
- Boundary: Missing one required field, null values.
- Acceptance method: Field presence validation on rendered card metadata and visible text.

### UX-009 Proof Card/OG signature position
- Input: Proof Card/OG rendering.
- Output: Signature is placed at bottom-right corner with safe margin and no overlap with mandatory fields.
- Boundary: Very narrow aspect ratio cards and auto-crop outputs.
- Acceptance method: Visual bounding-box inspection for bottom-right position and non-overlap.

### UX-010 Proof Card/OG use intent
- Input: Share/export citation flow.
- Output: Card is suitable for sharing and citation, preserving required proof metadata readability.
- Boundary: Downscaled share previews.
- Acceptance method: Share-preview QA confirms proof fields remain legible and present.

## 5) Brand readability acceptance baseline

### UX-011 16/24/32px recognizability
- Input: Primary mark rendered at 16px, 24px, and 32px contexts.
- Output: Brand remains recognizable at each specified size.
- Boundary: Low-DPI displays and compressed exports.
- Acceptance method: Human visual check with fixed sample set at 16/24/32px plus pixel-clarity spot check.
