# IntelliStudy — Implementation Context (`context.md`)

> Implementation context for a coding agent building the IntelliStudy web app (React + TypeScript + Tailwind CSS frontend, FastAPI backend) from the real Figma file.
> **No application code is included.** Nothing here is redesigned, improved or invented. Where Figma does not show something it is labelled **Not verified in Figma**.

Legend used throughout:
- **[Confirmed]** read directly from the Figma file on 2026-11-10 (frame, component or variable value).
- **[Recommendation]** a suggested implementation choice; not in Figma.
- **[Open]** a decision nobody has made; see section 16.
- **[Not verified in Figma]** not present in, or not inspectable from, the file.



**Revision 2 (2026-11-10, implementation-readiness audit).** Re-inspected Figma for every item previously marked "Not verified" and corrected v1 errors: desktop user chat message is a right-aligned 520 px bubble; Chat/Quiz columns are centred; Upload dropzone border is dashed; Settings toggle text styles; quiz question uses `text/h2`; Rail selected item is Courses on every Rail frame; mobile Tab bar selection; Input/Chip/CitationBadge state styling; ChatMessage and FileUploadRow internals; icon placements. New material: 4.7 text style map, 5.4 resizing table, 7.23 un-componentised patterns, **“Developer Assumptions To Eliminate”**, and sections 18–20 (adopted defaults, backend contract defaults, testable acceptance criteria). Items marked **Default** in sections 18–19 are *not* Figma facts; they are proposals that remove guessing and need owner sign-off.

---

## 1. Source of Truth

### 1.1 The file
| Item | Value |
|---|---|
| Figma file name | IntelliStudy – Web App |
| File key | `xrJtzDx1Eb8WjV7BZ5SH5e` |
| URL | https://www.figma.com/design/xrJtzDx1Eb8WjV7BZ5SH5e |
| Inspected | 2026-11-10, via the Figma Plugin API (`use_figma`) and screenshots |
| Font | Inter (Regular 400, Medium 500, Semi Bold 600, Bold 700) |

### 1.2 Priority order when sources disagree
1. The actual Figma frame (what is drawn).
2. The actual Figma component and variable values.
3. This document.
4. Product requirements (the original brief).
5. Developer assumptions.

If this document contradicts a Figma frame, the frame wins; report the mismatch.

### 1.3 What the Figma file is and is not
- It is a **light-theme, desktop-first** design with **four mobile frames**. **[Confirmed]**
- A **Dark** semantic colour set exists as variables (`Color/Dark`) but **no screen is rendered in dark**. **[Confirmed]**
- There is **no tablet layout**. **[Confirmed]**
- Most modules show **one state only** (the "happy" state). Chat is the exception (5 answer states) and Upload (6 file statuses). **[Confirmed]**
- Only **7 prototype links** exist, all in the Prototype section. Nothing on the Desktop or Mobile sections is wired. **[Confirmed]**
- All data in the frames (names, numbers, dates) is **sample copy**, not a data contract.

### 1.4 Counts (verified)
| Thing | Count |
|---|---|
| Pages | 3 (Foundations, Components, Screens) |
| Desktop frames | 20 |
| Mobile frames | 4 |
| Prototype frames | 7 |
| Component sets | 22 |
| Icon components | 30 (24×24) |
| Variable collections | 5 (Primitives 44, Color/Light 38, Color/Dark 38, Spacing 23, Type 19) |
| Text styles | 12 |
| Effect styles | 3 |
| Paint styles | 0 |
| Prototype reactions | 7 |

---

## 2. Product Overview

IntelliStudy is a web application for **university students**. A student uploads course materials (PDF, Word `.docx`, PowerPoint `.pptx`) into a **course**. From those files only, the app provides:

1. **Structured summaries** where every statement carries a citation badge `[n]` to a page, slide or section.
2. **A chatbot** that answers only from the student's materials, cites its sources, and visibly refuses, partially answers, or flags low confidence instead of guessing.
3. **Auto-generated quizzes** (multiple choice and short answer) with an answer review that explains and cites.
4. **Analytics**: mastery per topic, weak topics, score history, recommended next actions.
5. **Personalised exams** built from selected topics, weighted toward weak topics.

Design principles visible in the file (stated on the Foundations page and enforced in copy):
- **Trust** — every answer is traceable to the student's own file; the app says so.
- **Honest states** — uploading, extracting, OCR, unsupported, empty, refused, partial, low-confidence are explicit and labelled.
- **Focus** — one accent colour, calm layouts; the quiz hides the sidebar nav behind a slim rail.
- **Accessibility** — WCAG 2.2 AA target; interactive controls ≥ 44×44 px; focus ring 2 px; status never conveyed by colour alone.

Out of scope in Figma (do not add): social features, sharing, flashcards, study-group features, notifications beyond the settings toggles, any file types other than PDF/DOCX/PPTX.

---

## 3. Figma File Architecture

### 3.1 Pages
| Page | Node id | Content |
|---|---|---|
| Foundations | 0:1 | One frame `Foundations / Overview` (4:2), 1680×4472 |
| Components | 1:4 | One frame `Components / Overview` (6:2), 1680×12058 |
| Screens | 1:5 | Three Sections (below) |

> The file has 3 pages and 1 mode per variable collection because of the Figma plan limit. Light and Dark are therefore **two collections with identical token names**, not one collection with two modes. **[Confirmed]**

### 3.2 Foundations / Overview (4:2) — sections in order
1. Title text "IntelliStudy — Foundations" and a one-line description (teal-blue accent; variable chain Primitives → Color/Light + Color/Dark → Spacing → Type; components bind only to semantic tokens).
2. `Section / Primitive colors` (1216×540) — states primitives are **hidden from pickers (scope: none)** and never bound directly in components.
3. `Section / Semantic color — Light and Dark` (1552×1110).
4. `Section / Spacing, radius and size` (1100×590) — "8px grid with a 4px half-step".
5. `Section / Type scale — Inter` (1100×690).
6. `Section / Accessibility foundations` (1100×204) — WCAG 2.2 AA, focus ring 2 px outside ≥ 3:1, hit area 44×44.
7. `Section / Contrast check (computed from the variables)` (1552×658) — text ≥ 4.5:1, non-text ≥ 3:1; shows e.g. text/primary on bg/surface 17.68:1, text/secondary 7.05:1.

### 3.3 Components / Overview (6:2) — sections in order
Icons (1100×202) · Button · Input (TextField) · Tab · Chip · Tag · Citation badge · Progress bar · Mastery ring · Card · Source card · Icon button · Table row · Toast · Modal · Empty state · File upload row · Nav item · Notice (inline) · Toggle · Answer option · Chat composer · Chat message.

### 3.4 Screens page — sections and frames
**Section `Desktop — 1440`** (22:1969, 6280×6594). All frames fill `color/bg/canvas`.

| Frame | Node id | Size |
|---|---|---|
| 01 Auth / Sign in | 12:2 | 1440×900 |
| 01 Auth / Sign up | 12:55 | 1440×900 |
| 02 Dashboard | 12:123 | 1440×1086 |
| 03 Course workspace | 15:158 | 1440×900 |
| 04 Upload flow | 15:393 | 1440×1168 |
| 05 Summary | 15:606 | 1440×900 |
| 06 Chat / Answered | 17:482 | 1440×900 |
| 06 Chat / Answered — source open | 17:615 | 1440×900 |
| 06 Chat / Refused | 17:780 | 1440×1060 |
| 06 Chat / Partial | 17:927 | 1440×900 |
| 06 Chat / Loading | 17:1048 | 1440×900 |
| 06 Chat / Low confidence | 17:1147 | 1440×900 |
| 07 Quiz / Question (multiple choice) | 18:1013 | 1440×900 |
| 07 Quiz / Short answer | 18:1095 | 1440×900 |
| 07 Quiz / Review | 18:1165 | 1440×1280 |
| 08 Analytics | 20:1139 | 1440×1244 |
| 09 Exam / Builder | 20:1384 | 1440×1000 |
| 09 Exam / Results | 20:1576 | 1440×1100 |
| 10 Settings | 21:1349 | 1440×1320 |
| 10 Data & privacy | 21:1493 | 1440×1211 |

**Section `Mobile — 390`** (22:1970, 2080×1044). All frames 390×844, fill `color/bg/canvas`.

| Frame | Node id |
|---|---|
| M3 Course workspace | 22:1467 |
| M5 Summary | 22:1580 |
| M6 Chat | 22:1682 |
| M8 Analytics | 22:1742 |

(The numeric prefixes "M3, M5, M6, M8" mirror the desktop numbering; there is no M1, M2, M4, M7, M9, M10.)

**Section `Prototype — Upload → Summary → Chat → Quiz → Analytics`** (22:1971, 10960×1480).

| Frame | Node id | Size |
|---|---|---|
| P1 Upload | 22:1972 | 1440×1168 |
| P2 Summary | 22:2015 | 1440×900 |
| P3 Chat — answered | 22:2139 | 1440×900 |
| P4 Chat — source open | 22:2178 | 1440×900 |
| P5 Quiz — question | 22:2237 | 1440×900 |
| P6 Quiz — review | 22:2279 | 1440×1280 |
| P7 Analytics | 22:2339 | 1440×1244 |

The Prototype frames are **separate copies** of the matching desktop frames (their rail items are plain frames named `RailItem / …`, not component instances; a few labels differ). The Desktop and Mobile frames are the design reference; the Prototype frames only carry the click-through. **[Confirmed]** Their internal text was **not** re-dumped frame by frame in this pass → **Not verified in Figma** for exact copy differences against the desktop twins.

### 3.5 Naming conventions seen
- Frames: `NN Module / State`.
- Layers: `Region`, `Component / Variant label`, `Row`, `Section / …`.
- Variant properties are Title Case values: `State=Default|Hover|Focus|Selected|Disabled`, `Variant=Primary|…`, `Tone=Neutral|Accent|Success|Warning|Danger`.
- Icons: `icon/<camelCase>`.
- Variables: `group/name` with slashes (`color/accent/default`, `space/16`, `radius/md`).

---

## 4. Design Tokens

All values below are read from the file's variables and styles. Semantic tokens alias primitives.

### 4.1 Colors

#### 4.1.1 Primitives (hex) **[Confirmed]**
| Ramp | Values |
|---|---|
| accent | 50 `#ECF7FA` · 100 `#D3EEF4` · 200 `#A9DCE8` · 300 `#78C4D7` · 400 `#3FA5BF` · 500 `#1B8AA6` · 600 `#0F6F8A` · 700 `#0B5970` · 800 `#0A4457` · 900 `#082F3D` |
| neutral | 0 `#FFFFFF` · 50 `#F6F8F9` · 100 `#EDF0F2` · 200 `#DDE2E6` · 300 `#C3CBD1` · 400 `#9AA5AD` · 500 `#6B7782` · 600 `#4F5A64` · 700 `#38424B` · 800 `#232B33` · 850 `#1A2027` · 900 `#131920` · 950 `#0D1116` |
| green | 50 `#E8F5EE` · 300 `#86CFA6` · 400 `#4DB37E` · 500 `#2E9560` · 600 `#1E7A4C` · 700 `#17603B` · 900 `#0F3D26` |
| amber | 50 `#FDF4E3` · 300 `#F0C675` · 400 `#E0A33A` · 500 `#B7791A` · 600 `#A15C07` · 700 `#7C4705` · 900 `#4A2B04` |
| red | 50 `#FCECEC` · 300 `#F2A29B` · 400 `#E5675C` · 500 `#C9473B` · 600 `#B42318` · 700 `#8F1B12` · 900 `#4F120D` |

#### 4.1.2 Semantic tokens (Light → Dark) **[Confirmed]**
Same token name in both collections. CSS-variable intent: expose each as `--color-<group>-<name>` and switch the set via a theme attribute.

| Token | Light | Dark |
|---|---|---|
| color/bg/canvas | neutral/50 `#F6F8F9` | neutral/950 `#0D1116` |
| color/bg/surface | neutral/0 `#FFFFFF` | neutral/900 `#131920` |
| color/bg/raised | neutral/0 `#FFFFFF` | neutral/850 `#1A2027` |
| color/bg/subtle | neutral/100 `#EDF0F2` | neutral/800 `#232B33` |
| color/bg/scrim | neutral/950 `#0D1116` | neutral/950 `#0D1116` |
| color/border/default | neutral/200 `#DDE2E6` | neutral/700 `#38424B` |
| color/border/strong | neutral/300 `#C3CBD1` | neutral/600 `#4F5A64` |
| color/text/primary | neutral/900 `#131920` | neutral/50 `#F6F8F9` |
| color/text/secondary | neutral/600 `#4F5A64` | neutral/300 `#C3CBD1` |
| color/text/tertiary | neutral/500 `#6B7782` | neutral/400 `#9AA5AD` |
| color/text/on-accent | neutral/0 `#FFFFFF` | neutral/950 `#0D1116` |
| color/text/link | accent/700 `#0B5970` | accent/300 `#78C4D7` |
| color/accent/default | accent/600 `#0F6F8A` | accent/400 `#3FA5BF` |
| color/accent/hover | accent/700 `#0B5970` | accent/300 `#78C4D7` |
| color/accent/pressed | accent/800 `#0A4457` | accent/200 `#A9DCE8` |
| color/accent/subtle | accent/50 `#ECF7FA` | accent/900 `#082F3D` |
| color/accent/subtle-border | accent/200 `#A9DCE8` | accent/700 `#0B5970` |
| color/accent/fg | accent/700 `#0B5970` | accent/300 `#78C4D7` |
| color/focus/ring | accent/600 `#0F6F8A` | accent/300 `#78C4D7` |
| color/disabled/bg | neutral/100 `#EDF0F2` | neutral/800 `#232B33` |
| color/disabled/fg | neutral/400 `#9AA5AD` | neutral/500 `#6B7782` |
| color/success/bg | green/50 `#E8F5EE` | green/900 `#0F3D26` |
| color/success/border | green/300 `#86CFA6` | green/700 `#17603B` |
| color/success/fg | green/700 `#17603B` | green/300 `#86CFA6` |
| color/success/solid | green/600 `#1E7A4C` | green/400 `#4DB37E` |
| color/warning/bg | amber/50 `#FDF4E3` | amber/900 `#4A2B04` |
| color/warning/border | amber/300 `#F0C675` | amber/700 `#7C4705` |
| color/warning/fg | amber/700 `#7C4705` | amber/300 `#F0C675` |
| color/warning/solid | amber/600 `#A15C07` | amber/400 `#E0A33A` |
| color/danger/bg | red/50 `#FCECEC` | red/900 `#4F120D` |
| color/danger/border | red/300 `#F2A29B` | red/700 `#8F1B12` |
| color/danger/fg | red/700 `#8F1B12` | red/300 `#F2A29B` |
| color/danger/solid | red/600 `#B42318` | red/400 `#E5675C` |
| color/mastery/not-started | neutral/500 `#6B7782` | neutral/500 `#6B7782` |
| color/mastery/weak | red/500 `#C9473B` | red/400 `#E5675C` |
| color/mastery/learning | amber/500 `#B7791A` | amber/400 `#E0A33A` |
| color/mastery/proficient | accent/500 `#1B8AA6` | accent/400 `#3FA5BF` |
| color/mastery/mastered | green/500 `#2E9560` | green/400 `#4DB37E` |

Notes:
- `color/bg/scrim` is used at **45% opacity** on the mobile source sheet scrim (node opacity 0.45). **[Confirmed]**
- All frame and component fills, strokes and text fills that were scanned are bound to variables (icon vector internals were not scanned). The only text layer without a text style is the SourceCard passage (raw 14 px).
- Shadow colour is `#0D1217` (not a variable). **[Confirmed]**

#### 4.1.3 Semantic usage map (what colour means) **[Confirmed]**
| Meaning | Surface | Text/icon |
|---|---|---|
| Brand / primary action / selected | accent/default (solid), accent/subtle (tint) | on-accent (on solid), accent/fg (on tint) |
| Neutral info | bg/subtle | text/secondary |
| Success (Indexed, Mastered, Correct) | success/bg | success/fg |
| Warning (Learning, Partly correct, scanned-PDF notice) | warning/bg | warning/fg |
| Danger (Failed, Weak, Incorrect, destructive) | danger/bg, danger/solid | danger/fg, on-accent on solid |
| Mastery levels | `color/mastery/*` (ring arc, bar fill) | — |

Mastery colours by level: Not started = neutral/500 · Weak = red/500 · Learning = amber/500 · Proficient = accent/500 · Mastered = green/500 (light theme).

### 4.2 Typography **[Confirmed]**
Font family variable `font/family/sans = Inter`. Letter spacing is stored in **percent** in Figma.

| Text style | Weight | Size / line-height | Letter-spacing | Typical use (seen) |
|---|---|---|---|---|
| text/display | Bold 700 | 40 / 48 | −1% | Auth brand headline |
| text/h1 | Semi Bold 600 | 32 / 40 | −0.5% | Page titles (Dashboard greeting, Course name, Summary, Upload) |
| text/h2 | Semi Bold 600 | 24 / 32 | −0.25% | Section titles ("Your courses"), auth card title, stat values, ring label (Lg) |
| text/h3 | Semi Bold 600 | 20 / 28 | 0 | Card titles ("Weakest topics"), recommendation title, modal title |
| text/title | Semi Bold 600 | 16 / 24 | 0 | Panel titles, wordmark, summary section titles |
| text/body-lg | Regular 400 | 18 / 28 | 0 | Auth brand subcopy |
| text/body | Regular 400 | 16 / 24 | 0 | Body copy, inputs, answer options |
| text/body-strong | Medium 500 | 16 / 24 | 0 | Topic names in rows, selected NavItem label |
| text/body-sm | Regular 400 | 14 / 20 | 0 | Helper/secondary copy, meta rows |
| text/label | Medium 500 | 14 / 20 | 0 | Button, tab, chip, nav labels |
| text/caption | Regular 400 | 12 / 16 | 0 | Breadcrumbs, timestamps, scope line |
| text/caption-strong | Semi Bold 600 | 12 / 16 | +0.2% | Tags, citation index, eyebrows (uppercase in copy) |

Type variables: `font/size/*` and `font/line-height/*` for display 40/48, h1 32/40, h2 24/32, h3 20/28, title 16/24, body-lg 18/28, body 16/24, body-sm 14/20, caption 12/16 (no variable for label/body-strong/caption-strong; they reuse body-sm/body/caption sizes). **[Confirmed]** **CSS conversion:** Figma letter-spacing percent → `em` (−1% = `-0.01em`, −0.5% = `-0.005em`, −0.25% = `-0.0025em`, +0.2% = `0.002em`); line-heights are pixel values (use px or the exact ratio); weights Regular 400 / Medium 500 / Semi Bold 600 / Bold 700.

Casing: eyebrows and field captions are **typed in upper case in the string** (e.g. "NEXT RECOMMENDED ACTION", "SELECTED FILE", "SOURCES"). The file does not use a text-transform property. **[Confirmed in strings]** → implement as authored uppercase text or `text-transform: uppercase` — same visual result; keep accessible name in sentence case if desired **[Recommendation]**.

### 4.3 Spacing **[Confirmed]**
`space/0=0, 4, 8, 12, 16, 24, 32, 40, 48, 64, 80, 96` (px). Grid note on Foundations: "8px grid with a 4px half-step".

Spacing actually used in layouts:
| Where | Value |
|---|---|
| Desktop page content padding (Main) | top 40 / right 48 / bottom 48 / left 48; vertical gap between blocks 32 |
| Card padding | 24 (SourceCard, Notice, Toast use 16 / 16 / 4-4-4-16 respectively) |
| Auth card padding | 40, inner gap 24 |
| Auth brand panel padding | 80, gap 32 |
| Side panels (source, details) | 32 top/bottom, 24 left/right |
| File list column | padding 24/16, gap 16 |
| Chat messages area | padding 40, gap 32 |
| Mobile body | padding 16, gap 16 |
| Buttons | horizontal padding 16, gap 8 |

### 4.4 Dimensions **[Confirmed]**
| Token / measurement | px |
|---|---|
| size/touch-target | 44 |
| size/control-md | 44 |
| size/control-lg | 48 (defined; not seen applied in inspected frames → **Not verified** where used) |
| size/focus-ring | 2 |
| size/sidebar | 264 |
| size/panel | 360 (SourceCard width; the actual source panel frames are 380 and 340 wide) |
| Left rail (compact nav) | 72 |
| Course file list column | 300 |
| Workspace file-details column | 340 |
| Summary/Chat source panel | 380 |
| Analytics right column | 400 (left 656, gap 24) |
| Exam preview column | 380 (settings column 676) |
| Quiz column | 720 |
| Settings and Data & privacy column | 760 |
| Chat message / composer width | 760 |
| Desktop main content width | 1080 (1176 minus 48 + 48) |
| Mobile app bar | 61 (M8: 41) |
| Mobile tab bar | 69 |
| Mobile bottom sheet | 390 × 416 |

### 4.5 Borders, radius, shadows **[Confirmed]**
- Radius tokens: sm 4, md 8, lg 12, xl 16, full 999.
- Applied: Tags 4; citation pill 4; Buttons/Inputs/Tabs-hover/NavItem/IconButton 8; AnswerOption, SourceCard, Notice, Toast, FileUploadRow, Summary sections 12; Cards, panels, Auth card, Modal, ChatComposer, dropzone 16; Chip pill, avatar, toggle track, progress bar 999.
- Borders: default **1 px** `color/border/default`; emphasised controls `color/border/strong`; selected/active **2 px** `color/accent/default`; focus ring **2 px** `color/focus/ring`; the Upload dropzone has a **2 px dashed** `accent/default` stroke (dash 8 px, gap 6 px, stroke aligned inside).
- **Shadow → CSS** (colour `#0D1217` = `rgb(13 18 23)`): `shadow/sm` = `0 1px 2px rgb(13 18 23 / 6%)`; `shadow/md` = `0 4px 12px rgb(13 18 23 / 8%), 0 1px 2px rgb(13 18 23 / 5%)`; `shadow/lg` = `0 16px 40px rgb(13 18 23 / 16%), 0 4px 8px rgb(13 18 23 / 6%)`. Elements bound to a shadow style: Auth card (`shadow/md`), Card Hover (`shadow/md`), SourceCard Hover (`shadow/sm`), Toast (`shadow/md`), Modal (`shadow/lg`), mobile Source sheet (`shadow/lg`).
- **Stroke alignment:** all default 1 px and 2 px selected strokes are **inside** (CSS `border` with `box-sizing: border-box`; element size includes the border). Focus rings on Button, Chip, Card and Tab are **outside** 2 px strokes (CSS `outline: 2px solid` with `outline-offset: 0`); the **Input field's** focus stroke is **inside** 2 px (use a 2 px border/inset ring). **[Confirmed]**
- Column dividers are single-side 1 px strokes (e.g. Sidebar right, Source panel left, Header bottom, Composer area top, Tab bar top, App bar bottom).
- Shadows (effect styles; colour `#0D1217`):
  - `shadow/sm` 0 1 2, 6%.
  - `shadow/md` 0 4 12 @8% + 0 1 2 @5% (Auth card shows 2 effects; Card hover and SourceCard hover show effects).
  - `shadow/lg` 0 16 40 @16% + 0 4 8 @6% (Modal, mobile source sheet, Toast show effects).

### 4.6 Layout and grid — Figma terms mapped to CSS intent
| Figma | CSS intent |
|---|---|
| Auto layout, direction `H` / `V` | `display:flex; flex-direction: row / column` |
| Item spacing (`g`) | `gap` |
| Padding top/right/bottom/left | `padding` |
| Primary-axis sizing FIXED / HUG / FILL | fixed width·height / `fit-content` / `flex:1` (or `width:100%`) |
| Counter-axis sizing | `align-items` + width/height |
| "Spacer" frame with absolute size | `flex:1` push (e.g. sidebar spacer between nav and user card) |
| Absolute-positioned children (`abs` in dumps are icons inside Hug frames and ring parts) | `position:absolute` inside a `position:relative` parent |
| Single-side stroke | `border-left` / `border-bottom` etc. |
| Corner radius | `border-radius` |
| Effect style shadow | `box-shadow` |

There is **no Figma layout grid** (column grid) on any frame; widths come from auto-layout constraints and fixed column widths listed in 4.4. **[Confirmed]** all 31 frames on the Screens page have an empty `layoutGrids` list. All frames clip their content (`clipsContent = true`); none has an overflow-scroll setting, so scroll regions are a code decision (see 17).

### 4.7 Text style usage map (what style is used for which element) **[Confirmed by scan of all desktop and mobile frames]**
All text is left-aligned unless stated. Colours are semantic tokens.

| Element | Style | Colour |
|---|---|---|
| Page title (Dashboard greeting, Course workspace, Summary, Upload, Analytics, Exam, Settings, Data & privacy) | `text/h1` | text/primary |
| Page title exceptions: **Chat frames** course title; **mobile Summary** page title | `text/h2` | text/primary |
| Mobile app-bar title | `text/title` | text/primary |
| Page subtitle / helper under title | `text/body` | text/secondary |
| Breadcrumb | `text/caption` | text/secondary |
| Section heading outside a card ("Your courses") | `text/h2` | text/primary |
| Card title — Dashboard cards (recommendation, streak, Weakest topics, Recent activity) and stat level word | `text/h3` | text/primary |
| Card title — Workspace ("Materials", "Topics found…"), Analytics, Settings, Privacy, Exam preview/results, panel heads, summary section titles, wordmark | `text/title` | text/primary |
| Stat label (UPPERCASE authored) | `text/caption-strong` | text/tertiary |
| Stat value | `text/h2` | text/primary |
| Stat note, timestamps in meta, counts ("3 sources") | `text/caption` | text/secondary (timestamps in Recent activity: text/tertiary) |
| Eyebrow in panels / quiz ("EXACT PASSAGE", "MULTIPLE CHOICE", "WHY", "ALL SOURCES…") | `text/caption-strong` | text/tertiary |
| Eyebrow on tinted card ("NEXT RECOMMENDED ACTION") | `text/caption-strong` | accent/fg |
| Avatar initials | `text/caption-strong` | accent/fg, centred |
| List row primary text — topic lists, results, analytics rows, activity text, summary bullets, statement text | `text/body` | text/primary |
| Dashboard weak-topic name; Exam-preview values | `text/body-strong` | text/primary |
| File names, settings/privacy row titles, form labels, percentages in rows (right-aligned) | `text/label` | text/primary (row % for weak topics: danger/fg) |
| Secondary descriptions — meta rows, privacy descriptions, Analytics action body, panel context text | `text/body-sm` | text/secondary (meta values: text/primary) |
| Settings toggle description | `text/caption` | text/secondary |
| Quiz question | `text/h2` | text/primary |
| Quiz hint ("Choose one answer.") | `text/body-sm` | text/secondary |
| Quiz bar: line 1 "Quiz · …" | `text/caption` secondary; line 2 "Advice and weaving · …" `text/title` primary; right text "Question n of 10" `text/label` secondary | — |
| Short-answer text | `text/body` | text/primary |
| Auth headline / subcopy / trust points | `text/display` / `text/body-lg` (secondary) / `text/body` | primary |
| Auth card title | `text/h2` | text/primary |
| "Forgot your password?" | `text/body-sm`, **centred** | text/link |
| Retry text link in file list | `text/label` | text/link |
| Mobile Tab-bar labels | `text/caption` | text/secondary (selected: accent/fg) |
| Disclaimer under composer | `text/caption` | text/secondary |

No text in any frame uses an ellipsis/truncation setting; every long string **wraps** (file names, topic names, messages). Heights of rows therefore grow (see 7.23). **[Confirmed]**

---
## 5. Responsive Design Rules

### 5.1 What exists **[Confirmed]**
| Breakpoint | Frames | Notes |
|---|---|---|
| Desktop 1440 | all 20 desktop frames | Heights vary (900–1320) because content is not clipped; this is page content length, not a viewport |
| Mobile 390 | M3 Course workspace, M5 Summary, M6 Chat, M8 Analytics | All 390×844 |
| Tablet | **none** | **Not verified in Figma** — no frame exists |

Modules with **no mobile frame**: Auth, Dashboard, Upload flow, Quiz (question, short answer, review), Exam builder, Exam results, Settings, Data & privacy. Their mobile behaviour is **Not verified in Figma** (see Open Questions).

### 5.2 Rules derived from the frames
**Navigation**
- Desktop: either the **264 px Sidebar** (Dashboard, Upload, Analytics, Exam, Settings, Data & privacy) or the **72 px Rail** (Course workspace, Summary, Chat, Quiz). Both carry the same six destinations. Why two forms is a design decision of the file, not stated in a rule; the rail appears in course-level and focus screens. **[Confirmed pattern]**
- Mobile: no sidebar or rail. A **bottom Tab bar** (4 items: Home, Courses, Analytics, Settings) and a top **App bar** (back + title). "Personalised exam" and "Data & privacy" have **no mobile entry** in the Tab bar. **[Confirmed; how to reach them is Not verified]**

**Course tabs** (Overview · Summary · Chat · Quiz · Analytics): same five Tab instances on desktop and mobile; on mobile they sit in a 358-wide row (5 tabs total 413 px wide on desktop). On mobile whether the row scrolls horizontally or wraps is **Not verified in Figma** (the row is a 358-wide frame; contents 96+96+64+63+94 = 413 px overflow it).

**Two-pane → one-pane**
- Course workspace desktop = file list (300) + center (728) + details (340). Mobile M3 = single column: Tabs → course-mastery stat → Notice → Materials header with `Add` → file items. The **selected-file details panel has no mobile equivalent** → **Not verified in Figma**.
- Summary desktop = center + 380 source panel. Mobile M5 = single column; the source panel becomes a **bottom sheet** (390×416, radius 16, shadow/lg, grabber 40×4) over a 45% scrim.
- Chat desktop = chat column (1368 wide, or 988 when the source panel is open) + 380 source panel. Mobile M6 shows only the Answered state; mobile behaviour for source open, refused, partial, loading, low confidence is **Not verified in Figma**.
- Analytics desktop = 4 stats in a row + two-column grid (656 / 400). Mobile M8 = single column: filter chips (wrapping, 96 high), 2 stats, "Mastery per topic" (4 rows, no percentage column), one "Recommended next" card. **Score history, Weak topics list, and the other two recommended actions are absent on mobile.** **[Confirmed]**

**Component changes on mobile**
- Chat user message: on desktop `ChatMessage / User` is a **right-aligned bubble 520 px wide** inside the 760 px message column (fill `bg/subtle`, radius 12, padding 12/16, `text/body`); on mobile it is a **detached frame** `ChatMessage / User (mobile)` — a 300-wide bubble with the same fill and padding. **[Confirmed]**
- Topic rows on mobile stack: row 1 = name + Tag, row 2 = full-width bar (no % number, no separate tag column).
- Stats on mobile: 2 per row, 173 wide, gap 12.
- Course filter chips wrap to a second line.
- Buttons stay 44 high; full-width buttons (324–358) in cards.
- Mobile tap targets: Toggle target 44×44; Back 44×44.

### 5.3 Scaling rules
- Desktop content is **fluid inside the fixed columns** (see 5.4): FILL regions stretch and shrink; only panels, the Quiz column (720), the Chat message column (760) and Settings/Privacy content (760) are fixed. Behaviour below ~1100 px or above 1440 px was not drawn → **Not verified in Figma** (defaults in section 18).
- **[Recommendation]** Treat 1440 as the reference width; honour the FILL / FIXED table above rather than capping content with `max-width`; add breakpoints per section 18 (D-3).
- Text must not truncate silently: long file names wrap (File items grow from 60 to 82 px tall when the name wraps to two lines). **[Confirmed]**

### 5.4 Resizing behaviour read from Figma (auto-layout sizing) **[Confirmed]**
| Container | Horizontal | Vertical |
|---|---|---|
| Sidebar | FIXED 264 | FILL (full frame height) |
| Rail | FIXED 72 | FILL |
| Main (right of Sidebar/Rail) | FILL | FILL |
| Dashboard: Header, Row A, Courses, Row C | FILL | HUG |
| Dashboard Row A: recommendation card | FILL (grow) | — |
| Dashboard Row A: Study streak | FIXED 340 | — |
| Dashboard course cards (3) / Row C cards (2) | FILL (equal grow) | — |
| Workspace: File list | FIXED 300 | FILL |
| Workspace: Center | FILL | FILL |
| Workspace: File details | FIXED 340 | FILL |
| Workspace Stats (3 cards) / Topics card / Notice | FILL (equal) | HUG |
| Summary: Center | FILL | FILL |
| Summary / Chat: Source panel | FIXED 380 | FILL |
| Chat column | FILL (1368 → 988 when the panel is open) | FILL |
| Chat Messages | FILL | FILL (grows; fills space above the Composer area) |
| Chat message column and Composer | **FIXED 760, centred** in the chat column (x = 304 of 1368) | HUG |
| Quiz bar / ProgressBar | FILL | 77 / 8 (ProgressBar sits directly **below** the bar, not overlaid) |
| Quiz column | **FIXED 720, centred** (x = 324 of 1368) | HUG |
| Analytics: Page header, filter, Stats, Grid | FILL | HUG |
| Analytics Stats (4 cards) | FILL (equal) | — |
| Analytics Grid: Left column | FILL (grow) | — |
| Analytics Grid: Right column | FIXED 400 | — |
| Exam builder Grid: Exam settings / Exam preview | FILL (grow) / FIXED 380 | — |
| Settings / Data & privacy: Content | FIXED 760, **left-aligned** in Main (x = 48) | HUG |
| Upload: Dropzone / Upload list | FILL | HUG |
| Auth: Brand panel / Form side | FIXED 640 / FILL | FILL |
| Auth card | FIXED 440, **centred** both axes in Form side | HUG |

Implication: at widths above 1440, FILL regions grow while FIXED columns stay; below 1440 FILL regions shrink first. The reference widths in 4.4 are the 1440 result. Mobile frames' sizing modes were **not read** (Not verified in Figma).

---

## 6. Application Shell and Shared Navigation

### 6.1 Shell variants **[Confirmed]**
| Variant | Used by | Width | Fill / border |
|---|---|---|---|
| **Sidebar** | 02 Dashboard, 04 Upload, 08 Analytics, 09 Exam Builder, 09 Exam Results, 10 Settings, 10 Data & privacy | 264 | `bg/surface`, 1 px right border `border/default` |
| **Rail** | 03 Workspace, 05 Summary, all 06 Chat, all 07 Quiz | 72 | same |
| **Mobile App bar + Tab bar** | M3, M5, M6, M8 | 390 | App bar `bg/surface` bottom border; Tab bar `bg/surface` top border |
| **Auth split** | Sign in / Sign up | 640 + 800 | Brand panel `accent/subtle`; form side transparent on canvas |

### 6.2 Sidebar (264×frame height)
- Vertical auto layout, padding 24 / 16 / 24 / 16, gap 4.
- Children top → bottom: **Wordmark** (132×56 block: 32×32 mark, radius 8, fill `accent/default`, white `icon/book` 18, then "IntelliStudy" `text/title`) → 6 **NavItem** instances (231–232×44) → **Spacer** (fills remaining height) → **User card** (231×60, padding 12, gap 12).
- NavItems in order, with the icon each shows in the Rail twin:
  1. Dashboard (`icon/home`)
  2. Courses (`icon/book`)
  3. Analytics (`icon/chart`)
  4. Personalised exam (`icon/target`)
  5. Settings (`icon/sliders`)
  6. Data & privacy (`icon/shield`)
- Selected item per frame: Dashboard→Dashboard; Upload→**Courses**; Analytics→Analytics; Exam Builder/Results→Personalised exam; Settings→Settings; Data & privacy→Data & privacy. **[Confirmed]**
- User card: avatar 36×36 circle, fill `accent/subtle`, initials "LH" `text/caption-strong`; name "Layla Hassan" `text/label`; subtitle "Computer Science · Year 3" `text/caption`.
- The user card is not a button in Figma (no hover/menu drawn). Sign-out is **not shown anywhere**. **[Confirmed absence]**

### 6.3 Rail (72×900 in workspace-type frames)
- Vertical, padding 24 / 0, gap 4, items centred. Wordmark is the 32×32 mark only (no text) inside a 32×56 block.
- Six `RailItem / <name>` **frames** (44×44, radius 8, icon 20) — these are **plain frames, not NavItem instances**; the selected one has fill `accent/subtle`. **`RailItem / Courses` is the selected item in every Rail frame** (workspace, summary, all six chat frames, all three quiz frames and the Prototype copies).
- Bottom: Spacer then avatar 36 "LH".
- Rail items have **no visible labels**; accessible names must be provided (aria-label). **[Recommendation]**
- Rail and Sidebar are two different visual components in Figma; implement as one navigation component with `variant="sidebar" | "rail"`. **[Recommendation]**

### 6.4 Page header patterns **[Confirmed]**
| Pattern | Where | Structure |
|---|---|---|
| Greeting header | Dashboard | H1 "Good afternoon, Layla" + date/midterm line + primary Button (right) |
| Page header | Analytics, Exam Builder/Results, Settings, Data & privacy, Upload | H1 (32) + `text/body` subtitle in `text/secondary`; optional right Button |
| Course header | Workspace, Summary, Chat | Breadcrumb `text/caption` ("Courses  /  Aspect-Oriented Programming") → title row (H1 + right Button) → Tabs | (Chat frames render the title in `text/h2`.)
| Quiz bar | Quiz frames | 77-high bar: Exit quiz Button, title block (caption + subtitle), "Question n of 10" right; 8-high ProgressBar full width below |

Breadcrumb strings contain **two spaces around `/`** ("Courses  /  Aspect-Oriented Programming"); they are not links in Figma (no hover). **[Confirmed]**

### 6.5 Mobile shell **[Confirmed]**
- **App bar** (390×61; M8 is 41): padding 8, gap 8; Back 44×44 (uses `icon/chevronDown` rotated −90° so the chevron points left) + title (`text/title`). M8's app bar has **title only, no Back**.
- **Tab bar** (390×69): padding 8; 4 `TabItem` frames (94×52) with icon 20 + label: Home (`icon/home`), Courses (`icon/book`), Analytics (`icon/chart`), Settings (`icon/sliders`). Selected item: **Courses** in M3 and M5, **Analytics** in M8; **M6 has no Tab bar**. Selected = item fill `accent/subtle` + label `accent/fg`; unselected label `text/secondary`; labels use `text/caption` (Regular) for every item.
- Screen background `color/bg/canvas`.

### 6.6 Global patterns not drawn
There is **no** global search, notification bell, theme switch in the shell, language switch, help menu, breadcrumb links, toast container, or modal host drawn in any frame. Toast and Modal exist only as components. **[Confirmed]**

---

## 7. Component Library

General: all components live on the Components page. Every fill/stroke is bound to semantic variables. Component text uses text styles except where noted. Interactive components are ≥ 44 px in the hit dimension, **except the Inline CitationBadge (24×22)**, which is the only sub-44 px interactive element in the file (the Touch size is the 44 px variant). Hover/Focus/Disabled variants exist in the library but **no screen uses them** (screens only use Default/Selected/Loading/Error etc.). **[Confirmed]**

Usage counts on Screens (instances): Button 95 · CitationBadge 77 · Tag 68 · Tab 64 · NavItem 54 · Chip 33 · ChatMessage 17 · FileUploadRow 12 · AnswerOption 12 · MasteryRing 11 · ProgressBar 11 · ChatComposer 9 · Input 8 · SourceCard 8 · Notice 7 · Toggle 7 · IconButton 5 · Card 3. **Not used on any screen:** Modal, Toast, EmptyState, TableRow. **[Confirmed]**

The component property `Show icon` / `Icon` swap exists on Button; Label text is a text property on most components.

### 7.1 Button (set 6:204 — 20 variants)
- **Purpose:** every action.
- **Figma structure:** auto-layout H, centre aligned: optional Icon (instance swap) + Label text.
- **Properties:** `Variant` = Primary · Secondary · Ghost · Danger; `State` = Default · Hover · Focus · Disabled · Loading; `Label` (text); `Show icon` (boolean, default false); `Icon` (instance swap, default `icon/…`).
- **Dimensions:** height **44**, padding 0 / 16, gap 8, radius 8; width hugs (77 default for the placeholder label; Loading is 24 px wider for the spinner).
- **Typography:** `text/label` (14/20 Medium).
- **Colour by variant/state:**

| Variant / State | Fill | Stroke | Label |
|---|---|---|---|
| Primary Default | accent/default | — | on-accent |
| Primary Hover | accent/hover | — | on-accent |
| Primary Focus | accent/default | focus/ring 2 | on-accent |
| Primary Disabled | disabled/bg | — | disabled/fg |
| Primary Loading | accent/default | — | on-accent |
| Secondary Default | bg/surface | border/strong 1 | text/primary |
| Secondary Hover | bg/subtle | border/strong 1 | text/primary |
| Secondary Focus | bg/surface | focus/ring 2 | text/primary |
| Secondary Disabled | disabled/bg | border/default 1 | disabled/fg |
| Ghost Default | none | — | accent/fg |
| Ghost Hover | accent/subtle | — | accent/fg |
| Ghost Focus | none | focus/ring 2 | accent/fg |
| Ghost Disabled | none | — | disabled/fg |
| Danger Default | danger/solid | — | on-accent |
| Danger Hover | danger/fg | — | on-accent |
| Danger Focus | danger/solid | focus/ring 2 | on-accent |
| Danger Disabled | disabled/bg | — | disabled/fg |

- **States used on screens:** Primary/Secondary/Ghost/Danger **Default**, and Primary **Loading** (one instance: the Send button inside the `Chat / Loading` composer, label “Answering…”; Loading = 16 px spinner at x16 + label, 101 px wide).
- **Content rules:** sentence case, 1–4 words ("Check answer", "Retry wrong answers"); verbs first. Label must be real text.
- **Interaction:** click; Loading shows spinner (`icon/loader`) and the button should be non-interactive **[Recommendation]**; Disabled non-interactive.
- **Responsive:** may stretch to full width inside cards (Mobile 324/358, Exam preview 330, Details panel 291).
- **Accessibility:** native `<button>`; visible focus ring 2 px outside; disabled uses `disabled` attribute; Loading `aria-busy`.

### 7.2 Input (set 6:250 — 6 variants)
- **Purpose:** text field with label, field and optional helper/error.
- **Structure:** vertical auto layout, gap 8: Label (`text/label`) → Field (44 high, radius 8) → Helper (`text/body-sm`). Default component is 320×100; on screens it stretches to the column (358, 710).
- **Properties:** `State` = Default · Hover · Focus · Filled · Disabled · Error; `Label` text.
- **Text colours:** label `text/primary`; value `text/primary` (Filled/Error) or placeholder `text/tertiary`; helper `text/secondary`, `danger/fg` in Error; Disabled all `disabled/fg`.
- **Field (44 high, radius 8, padding 0/16, text `text/body`) per state:** Default fill `bg/surface`, stroke `border/strong` 1, placeholder `text/tertiary` · Hover stroke `text/tertiary` 1 · Focus stroke `focus/ring` **2** · Filled stroke `border/strong` 1, value `text/primary` · Disabled fill `disabled/bg`, stroke `border/default` 1, label/value/helper all `disabled/fg` · Error stroke **`danger/solid` 2**, value `text/primary`, a **trailing 20 px icon** inside the field, and the helper becomes a row (gap 4) with a **leading 16 px icon** + message in `danger/fg`. Label is always `text/label` `text/primary` (Disabled `disabled/fg`). **[Confirmed]**
- **Helper visibility:** the helper line can be hidden; the Sign-in Password input is 72 high (no helper) while others are 100. Settings fields show no helper.
- **Placeholders seen:** "name@university.edu", "Your password", "At least 12 characters".
- **Interaction:** standard text input; Error shows message below field. Password show/hide control is **not drawn**.
- **Accessibility:** `<label for>`, `aria-describedby` for helper, `aria-invalid` in Error; error text is text, not colour only.

### 7.3 Tab (set 6:264 — 5 variants)
- **Purpose:** switch between sections (course tabs; auth Sign in / Create account).
- **Structure:** H, padding 0 / 16, height 44, one Label.
- **Properties:** `State` = Default · Hover · Focus · Selected · Disabled; `Label`.
- **Style:** Default label `text/secondary`; Hover fill `bg/subtle` radius 8; Focus 2 px ring radius 8; **Selected = label `accent/fg` plus 2 px bottom border `accent/default`** (stroke weight mixed: bottom only); Disabled `disabled/fg`.
- **Width** hugs label + 32: Overview 96, Summary 96, Chat 64, Quiz 63, Analytics 94, "Sign in" 78, "Create account" 135.
- **Accessibility:** `role=tablist/tab`, `aria-selected`; or links if tabs are routes **[Recommendation]**.
- Note: auth uses Tab for Sign in / Create account which are **different pages** in Figma.

### 7.4 Chip (set 6:300 — 8 variants)
- **Purpose:** filter and multi-select (course filter, topic selection, number of questions, question types, theme).
- **Structure:** outer 44 high hit box (no fill) containing a **Pill** 36 high, radius 999, padding horizontal; Selected adds a 16 check icon (`icon/check`) before the label.
- **Properties:** `Selected` = False · True; `State` = Default · Hover · Focus · Disabled; `Label`.
- **Style:** Unselected pill fill `bg/surface`, stroke `border/strong` 1, label `text/primary`; **Hover** fill `bg/subtle`; **Focus** stroke `focus/ring` 2; **Disabled** fill `disabled/bg`, stroke `border/default`, label `disabled/fg`. Selected pill fill `accent/subtle`, stroke `accent/default` 1, label `accent/fg`; **Hover** fill `accent/subtle-border`; Disabled as above with a `disabled/fg` check. Label starts 13 px from the pill edge (unselected) or after a 16 px check + 4 px gap (selected).
- **Width:** label + 26 (unselected); +20 more for the check when selected.
- **Behaviour in file:** course filter = single-select (one Selected); Exam topics = multi-select; question count (10 / 20 / 30) = single-select; question types = multi-select; theme (Light / Dark / Match system) = single-select. Topic chips in the workspace details panel are **non-selected** chips (selection behaviour **Not verified**).
- **Accessibility:** radio group or checkbox group semantics matching behaviour; selected state exposed (`aria-pressed` / `aria-checked`).

### 7.5 Tag (set 6:314 — 5 variants)
- **Purpose:** status label (never a button).
- **Structure:** H, height **24**, padding 0 / 8, radius **4**, one label `text/caption-strong` (+0.2%).
- **Properties:** `Tone` = Neutral · Accent · Success · Warning · Danger; `Label`.
- **Colour:** Neutral bg/subtle + text/secondary; Accent accent/subtle + accent/fg; Success success/bg + success/fg; Warning warning/bg + warning/fg; Danger danger/bg + danger/fg. No border.
- **Strings seen (tone):** Indexed (Success) · Extracting (Accent) · Uploading 62% (Accent) · Failed (Danger) · Weak topic (Danger) · Learning (Warning) · Mastered · 94% (Success) · Proficient · 78% (Accent) · Weak · 32% (Danger) · Not started (Neutral) · Incorrect (Danger) · Correct (Success) · Partly correct (Warning).
- **Accessibility:** status is always text (the label), so colour is never the only signal.

### 7.6 CitationBadge (set 7:41 — 8 variants)
- **Purpose:** the clickable `[n]` that links a statement to its source.
- **Structure:** outer hit box + Pill + Index text. **Inline** = 24×22 box, pill 24×22, radius 4. **Touch** = 44×44 hit box with a 32×32 pill, radius 4.
- **Properties:** `Size` = Inline · Touch; `State` = Default · Hover · Focus · Active; `Index` text default "[1]".
- **Style:** Default pill fill `accent/subtle`, stroke `accent/subtle-border` 1, text `accent/fg` (`text/caption-strong`). **Active** pill fill `accent/default`, stroke `accent/default`, text `on-accent`. **Hover**: pill fill `accent/subtle-border`, stroke `accent/default` 1, text `accent/fg`. **Focus**: pill fill `accent/subtle`, stroke `focus/ring` 2. Touch Active: 32×32 pill centred in the 44×44 hit box, solid accent.
- **Content:** literal brackets in the text: `[1]`.
- **Interaction:** click/Enter opens the source (side panel on desktop, bottom sheet on mobile). Only Inline appears on screens; Touch is for mobile.
- **Accessibility:** `<button>` with accessible name such as "Source 1: Lecture 4, page 12" **[Recommendation]**; Inline size is < 44 px — Figma says use Touch where 44 px is needed; **which size mobile frames should use is Not verified** (M5/M6 use Inline).

### 7.7 ProgressBar (set 7:63 — 9 variants)
- **Purpose:** upload/quiz progress.
- **Structure:** track 320×8 radius 999 fill `bg/subtle`; Fill rectangle (accent/default for Active; Success/Error variants recolour the fill).
- **Properties:** `Status` = Active · Success · Error; `Value` = 25 · 60 · 100 (three **fixed** widths: 80 / 192 / 320 of 320).
- **Caveat:** the fill is a fixed-width rectangle per variant, not a continuous value. Implement as `<progress>`/role=progressbar with a continuous width. **[Confirmed + Recommendation]**
- Used in the quiz bar (1368×8, absolutely positioned under the bar) and in FileUploadRow.
- **Accessibility:** `role="progressbar"` with `aria-valuenow/min/max` and a text equivalent ("Question 6 of 10").

### 7.8 MasteryRing (set 7:110 — 10 variants)
- **Purpose:** circular mastery indicator.
- **Structure:** Track ellipse (fill `bg/subtle`, arc 0→2π, inner radius 0.78) + Value ellipse (fill `color/mastery/<level>`, arc from −π/2 clockwise) + Percent text (`text/caption-strong` for Sm; Lg also has a level caption below the % in `text/caption` `text/secondary`, and the % is `text/h2`).
- **Properties:** `Level` = Not started · Weak · Learning · Proficient · Mastered; `Size` = Sm (56×56) · Lg (112×112).
- **Caveat:** the Value arc in each variant is a **sample sweep** (Weak Sm ≈ 32%). Instances on screens only overwrite the text, so a 74% ring is drawn with the proficient colour and whatever sweep the variant has. **The sweep must be computed from data in code.** **[Confirmed]**
- **Colour per level:** mastery tokens (4.1.3).
- **Thresholds used by the design copy:** ≥ 90 Mastered · 70–89 Proficient · 50–69 Learning · 1–49 Weak · 0 Not started. (e.g. 94% Mastered, 78% / 71% Proficient, 56% Learning, 32–48% Weak). **[Confirmed from sample data; the thresholds are not written in Figma → treat as Open Question]**
- **Accessibility:** expose `role="img"` or text: "Mastery 74%, Proficient"; never colour only (percentage and level word always present on Lg; Sm shows the percentage plus a neighbouring Tag/label).

### 7.9 Card (set 7:146 — 5 variants)
- **Purpose:** course card on the Dashboard.
- **Structure:** V, padding 24, gap 12, radius 16, fill `bg/surface`, stroke `border/default` 1. Children: Title (`text/title`), Description (`text/body-sm`, `text/secondary`), status line (`text/caption-strong`, `success/fg`) and meta (`text/caption`, `text/secondary`).
- **Properties:** `Title`, `Description` (text); `State` = Default · Hover · Focus · Selected · Loading. Hover shadow = `shadow/md`.
- **States:** Hover stroke `border/strong` + shadow; Focus 2 px ring; Selected 2 px `accent/default` stroke; **Loading** = three skeleton bars (`bg/subtle`, radius 4: 200/280/240 × 16) and height 122.
- **Dashboard instances** are 344 wide (stretch) and 162 tall; the status line colour is **`success/fg`** for “All indexed” and **`accent/fg`** for “1 processing” (Queueing Theory card); meta line `text/secondary`.
- **Interaction:** whole card is a link to the course workspace **[Recommendation: not drawn]**.

### 7.10 SourceCard (set 7:223 — 4 variants)
- **Purpose:** shows the exact passage behind a citation.
- **Structure:** V, padding 16, gap 12, radius 12, 360 wide: header row (index badge `[n]` + file name `text/label`), location line `text/caption` (e.g. "Page 3 · 1.1 Cross-cutting concerns"), passage text (14 px, `text/primary`), link "Open in file" (`text/label`, `accent/fg`).
- **Properties:** `File`, `Location` (text); `State` = Default · Hover · Focus · Selected.
- **Style:** Default fill `bg/surface` stroke `border/default`; Hover stroke `border/strong` + `shadow/sm`; Focus 2 px ring; **Selected fill `accent/subtle`, 2 px `accent/default` stroke, badge becomes solid (on-accent text)**.
- **Known issue:** the passage text uses **raw 14 px (no text style)**; map to `text/body-sm`. **[Confirmed]**
- **Instances:** 331 wide in the panel (297/276 tall depending on passage); 358 wide on mobile; 670 wide in quiz review.
- **Accessibility:** "Open in file" is a link/button; passage is plain text.

### 7.11 IconButton (set 8:65 — 4 variants)
- 44×44, radius 8, one 20 icon (instance swap, default close). `State` = Default · Hover (fill `bg/subtle`) · Focus (2 px ring) · Disabled. Used for the close button of the source panel and sheet (the default close icon is `icon/x2`/`icon/x`; the icon on screens was **not re-read**). Needs `aria-label` (e.g. "Close source").

### 7.12 TableRow (set 8:102 — 5 variants)
- 880 wide. `Type` = Header · Row; `State` = Default · Hover · Selected · Focus. Header 40 high fill `bg/subtle`, `text/caption-strong` in `text/tertiary`; Row 56 high fill `bg/surface`, bottom border `border/default`; Hover `bg/subtle`; Selected `accent/subtle`; Focus 2 px ring. Cells: body-strong name, a Warning-tone tag, body, body-sm secondary. **Not used on any screen**; the real tables in the screens (topic lists) are bespoke frames. Treat as **reserved**.

### 7.13 Toast (set 8:138 — 4 variants)
- 440×54, radius 12, padding 4/4/4/16, gap 12, shadow. `Tone` = Info · Success · Warning · Danger; fill = tone `/bg`, stroke = tone `/border` (Info uses accent subtle + subtle-border). Contents: tone icon 20 + Message (`text/body-sm`, `text/primary`) + 44×44 IconButton close. Default message "File added.". **Not used on any screen.** `role="status"` (or `alert` for Danger) **[Recommendation]**. Auto-dismiss timing **Not verified in Figma**.

### 7.14 Modal (set 8:177 — 2 variants)
- 480×218, radius 16, fill `bg/raised`, stroke `border/default`, shadow, padding 24, gap 16. Header (Title `text/h3` + IconButton close), Body (`text/body`, `text/secondary`), Footer (Cancel = Secondary Button, confirm = Primary or Danger).
- **Default** vs **Destructive**; Destructive sample: title "Delete this course?", body "This removes 12 files, their summaries, chat history and quiz results. This can’t be undone.", buttons "Cancel" / "Delete course" (Danger). Default-variant copy not re-read.
- **Not used on any screen** and **not wired in the prototype**; scrim for the modal is **not drawn** (the mobile scrim uses `bg/scrim` at 45%). Focus trap, Esc and return-focus are required by WCAG but not drawn. **[Recommendation]**

### 7.15 EmptyState (set 8:207 — 2 variants)
- `Size` = Page (560×384, padding 64) · Panel (340×344, padding 32). Contents: 64 icon bubble (`bg/subtle`, icon 28), Title `text/h3` ("No materials yet"), Body `text/body` secondary ("Upload lecture slides, notes or papers (PDF, Word, PowerPoint). Summaries, chat and quizzes will be built only from these files."), Primary Button with icon ("Upload files"). **Not used on any screen.** Empty states for other modules were **not designed**.

### 7.15b Notice (set 9:230 — 3 variants)
(Numbered 7.15b only to keep set order readable.)
- **Purpose:** inline message block.
- 560×98 default (stretches to 648 / 330 / 358 / 760 / 1080), H, padding 16, gap 12, radius 12, 1 px border; leading icon + Title (`text/label`, `text/primary`) + Body (`text/body-sm`, `text/secondary`).
- `Tone` = **Info** (accent/subtle + subtle-border) · **Warning** (warning/bg + warning/border) · **Neutral** (bg/subtle + border/default). Info and Warning are used on screens (7 instances).
- `role="status"`; not dismissible in Figma.

### 7.16 FileUploadRow (set 8:442 — 14 variants)
- **Purpose:** one file in the upload list with a live status.
- **Structure:** H, padding 12, gap 12, radius 12, 1 px border, 680 wide (1080 on the Upload screen), items centred vertically. Left: **40×40 icon tile** (radius 8) holding a 20 px file icon — tile fill `accent/subtle` (Uploading), `success/bg` (Indexed), `danger/bg` (Failed); the other statuses were not individually read. Middle: **Details** (V, gap 4, fills the row): **Name row** (H, gap 8: file name `text/label` fills + a Tag 24 px high) → status text `text/body-sm` `text/secondary` → a **ProgressBar 320×8** (Uploading only; whether Extracting shows one is **unverified**). Right: a **Button instance** — **Ghost** for Cancel / Open / Remove, **Secondary** for Failed “Retry”. Row Hover = fill `bg/subtle`.
- **Properties:** `File name` text; `Status` = Uploading · Extracting · Indexed · Failed · OCR · Unsupported · Empty; `State` = Default · Hover (fill `bg/subtle`).
- **Heights:** Uploading 86 · Extracting 86 · Indexed 74 · Failed 74 · OCR 106 · Unsupported 94 · Empty 74.
- **Border colour:** `border/default` for Uploading/Extracting/Indexed/OCR; **`danger/border`** for Failed/Unsupported/Empty.
- **Status text colour:** accent/fg (Uploading, Extracting, OCR), success/fg (Indexed), danger/fg (Failed, Unsupported, Empty).
- **Copy per status (from the Upload screen):**
  - Uploading — "Uploading", "Uploading · 62% of 4.8 MB", action **Cancel**
  - Extracting — "Extracting", "Extracting text and structure…", **Cancel**
  - OCR — "OCR", "Scanned PDF detected. Reading pages with OCR — this can take a few minutes and some words may be misread.", **Cancel**
  - Indexed — "Indexed", "48 pages · indexed just now", **Open**
  - Unsupported — "Not supported", "This file type isn’t supported. Upload PDF, Word (.docx) or PowerPoint (.pptx).", **Remove**
  - Empty — "Empty", "This file has no readable text, so there is nothing to index.", **Remove**
  - Failed — not used on the Upload screen; library copy: “Couldn’t read this file. It may be password-protected.” with Secondary button **Retry** (the workspace file list shows a Failed tag plus a `text/link` “Retry” text instead). Library Indexed detail reads “48 slides · indexed 2 min ago” (the Upload screen reads “48 pages · indexed just now”).
- **Interaction:** whole row is the click target in the prototype (Indexed row → Summary).
- **Accessibility:** each status announced via text; progress via `role=progressbar`; live region for status changes **[Recommendation]**.

### 7.17 NavItem (set 9:205 — 4 variants)
- 232×44 (231 on screens), H, padding 0 / 12, gap 12, radius 8, Icon 20 + Label.
- `State` = Default (label text/secondary) · Hover (fill bg/subtle, label text/primary) · Focus (2 px ring) · **Selected (fill accent/subtle, label accent/fg, `text/body-strong`)**. Properties `Label`, `Icon` (swap).
- **Inconsistency:** Selected uses Medium 16/24 (`body-strong`) while others use Medium 14/20 (`label`) → label text changes size when selected. Replicate as drawn, or confirm (open question). **[Confirmed]**
- `aria-current="page"` when selected.

### 7.18 Toggle (set 9:252 — 6 variants)
- 56×44 hit box; Track 44×24 radius 999; Thumb 20×20 circle fill `bg/surface`. `Value` = Off (track `text/tertiary`) · On (track `accent/default`); `State` = Default · Focus (2 px ring on the track) · Disabled. Thumb position left/right per Value. **Thumb position:** Off = x 0, On = x 24 inside the 44 px track (20 px thumb, 2 px inset each side); Disabled = track `disabled/bg`, thumb `disabled/fg`; Focus = 2 px `focus/ring` stroke on the track.
- Used with a title + description row (Settings, Exam builder). `role="switch"`, `aria-checked`, label tied to the row text.

### 7.19 AnswerOption (set 9:284 — 7 variants)
- **Purpose:** quiz answer choice and answer review row.
- H, padding 12 / 16, gap 12, radius 12; default width 640 (stretches to 720 / 670). Leading indicator + Label (`text/body`).
- `State`: Default (fill surface, stroke border/strong 1) · Hover (bg/subtle) · Focus (2 px ring) · Selected (accent/subtle fill, 2 px accent stroke) · **Correct** (success/bg fill, 2 px success/solid, trailing "Correct" `caption-strong` success/fg) · **Incorrect** (danger/bg fill, 2 px danger/solid, trailing "Incorrect" danger/fg) · Disabled (disabled/bg).
- Correct and Incorrect are 76 high at default width (two-line); on the 720 column the text may wrap to make heights 56 / 76.
- Indicator: **Radio** 20×20 circle, 2 px stroke (`border/strong` Default; `accent/default` Selected with a 10 px `accent/default` dot). **Correct / Incorrect** replace the radio with a 20 px icon (success / danger) and add the right-aligned verdict word in `text/caption-strong` (`success/fg` / `danger/fg`). Label `text/body` fills the middle (gap 12). Disabled: fill `disabled/bg`, stroke `border/default`, label `disabled/fg`.
- The review state never relies on colour alone: it shows the words "Correct"/"Incorrect".
- `role="radio"` within `radiogroup` in the quiz; static list in review.

### 7.20 ChatComposer (set 9:337 — 4 variants)
- 760×102, V, padding 12 / 12 / 12 / 16, gap 8, radius 16, fill `bg/surface`, stroke `border/strong` 1.
- Children: Input text (`text/body`; placeholder in `text/tertiary`), Toolbar (H): scope icon 16 + Scope text (`text/caption`, `text/secondary`: "Searching all 12 files in this course") + **Send** Button (Primary, 91×44, icon `icon/send`).
- `State` = Default · Focus (2 px ring, height 104) · **Loading** (placeholder "Searching your materials…", text `disabled/fg`, Send label **"Answering…"**) · Disabled (fill `disabled/bg`, all text `disabled/fg`).
- Multiline growth behaviour **Not verified in Figma** (the field is a single drawn line).
- `<textarea>` with associated label; Enter to send is **not specified** (open question).

### 7.21 ChatMessage (set 11:388 — 6 types)
- 760 wide, V, gap 16, no fill.
- `Type` = **User** (right-aligned bubble, 520 wide, fill `bg/subtle`, radius 12, padding 12/16, `text/body`) · **Answered** · **Refused** · **Partial** · **Loading** · **Low confidence**.
- Assistant types share a **header** (H, gap 8, centred): **28×28 circular avatar** (fill `accent/subtle`, 16 px icon) + name “IntelliStudy” (`text/label`, `text/primary`) + status caption (`text/caption`, `text/tertiary`).
- **Answered** — caption “Answered from n files”; one **Sentence** row per statement (H, gap 4: `text/body` text + inline CitationBadge(s), wraps with the text); then the **Sources** row (H, gap 16): “SOURCES” (`text/caption-strong`, `text/tertiary`) + one group per source (gap 4: badge + `text/caption` `text/secondary` label such as “Lecture 4 · p. 12”).
- **Refused** — caption “Not found in your materials”; a **Refusal note** card (760 wide, fill `bg/subtle`, 1 px `border/default`, radius 12, padding 16, gap 12) containing: title row (20 px icon + `text/title` “I couldn’t find this in your materials”), body (`text/body`, `text/secondary`), a SourceCard (surface, 360 wide) for the closest material, “TRY ASKING” (`text/caption-strong`, `text/tertiary`) and a row of two Chip instances (gap 8).
- **Partial** — caption “Partly answered from 1 file”; Sentence rows with badges; a **Notice (Info tone)** instance (760 wide: `accent/subtle` fill, `accent/subtle-border`) titled “Only part of your question is covered”; Sources row.
- **Loading** — caption “Working”; three skeleton lines (`bg/subtle`, radius 4, 16 high: widths 560 / 480 / 320); a Status row (spinner 16 + “Searching 12 files…” `text/body-sm`, `text/secondary`). Skeleton pulse animation is not specified.
- **Low confidence** — caption “Answered from 2 files”; Sentence rows with badges; a **Notice (Warning tone)** instance (760×78: `warning/bg` fill, `warning/border`) titled “Low confidence” with body “The two sources describe this a little differently. Check the cited passages before relying on this answer.”; Sources row.
- Heights: User 48, Answered 186, Refused 494, Partial 260, Loading 160, Low confidence 240.
- Avatar and icon glyphs inside the avatar / notes were not individually read (icon name **unverified**).
- `aria-live="polite"` for Loading → result **[Recommendation]**.

### 7.22 Icons (30 components, 24×24, stroke 2)
See section 11.

### 7.23 Patterns that are NOT components in Figma (build as shared compositions) **[Confirmed]**
These recur on several screens but are plain frames; build them once.

| Pattern | Spec read from Figma |
|---|---|
| Wordmark | H gap 12: 32×32 mark (radius 8, fill `accent/default`, `icon/book` 18 in on-accent) + “IntelliStudy” `text/title`. Block 132×56 in Sidebar, 132×32 on Auth; Rail shows the mark only (32×56 block). |
| Avatar | 36×36 circle, fill `accent/subtle`, initials `text/caption-strong` `accent/fg` centred. Chat assistant avatar: 28×28, same fill, 16 px icon. |
| User card (Sidebar) | 231×60, H gap 12, padding 12: avatar 36 + V text (name `text/label`; “Computer Science · Year 3” `text/caption` secondary). Not interactive in Figma. |
| Stat card | V gap 4, padding 24, radius 16, `bg/surface`, 1 px `border/default`: label (`caption-strong`, tertiary) → value (`h2`) → note (`caption`, secondary). **Ring variant**: H gap 16, 56 ring + V gap 4 (label + level word `h3`); height 106 vs 122. Widths: Workspace 205, Analytics 258, mobile 173. |
| Dashboard weak-topic row | H gap 16, padding 8/0: ring Sm 56 · V text (name `body-strong`, wraps; course `caption` secondary) · Tag · Ghost Button “Practise” (87×44). Row height 80 when the name wraps to 2 lines, 72 otherwise. |
| Activity row | H gap 12, padding 12/0: 36×36 tile (`bg/subtle`, radius 8, 18 px icon) · text `body` (fills) · time `caption` tertiary. Row height 60 (72 if the text wraps). |
| Workspace file item | V, radius 8, padding 8/12: name row (H gap 8: 20 px file icon + `label` name, wraps) → status row indented 28 px (Tag; plus `caption` secondary text or `label` link “Retry”). Heights 60 / 80 / 82 by wrapping. **Selected** = fill `accent/subtle` + 1 px `accent/subtle-border`; unselected fill/stroke **not read** (render none). |
| Summary section (accordion) | V, radius 12, `bg/surface`, 1 px `border/default`. Header H, height 60, padding 8/16/8/8: **44×44 toggle target** (20 px chevron: right = collapsed, down = expanded) + title `text/title` (fills) + count `caption` secondary. Body (expanded) V gap 12, padding 4/24/24/64: bullet rows H gap 12 = 6×6 dot (`text/tertiary`, in a 6×14 wrapper) + statement (H gap 4: `body` text + inline badges). |
| Topic result row (Analytics / Exam results) | H gap 16, padding 12/0: name `body` (fills) · [results only: “n / m” `label` secondary] · bar track 160×8 (Analytics) or 200×8 (Results), fill `border/default`, fill bar = % of track in `mastery/<level>` · % `label` right-aligned · 96 px tag cell holding a Tag. |
| Weak topic item (Analytics) | V gap 4, padding 16, radius 12, fill `danger/bg`, stroke `danger/border` 1: row (name + % `label` `danger/fg`) + reason line. |
| Recommended action (Analytics) | V gap 8, padding 16, radius 12, fill `bg/subtle`: row (20 px icon + title `label`) + body `body-sm` secondary + Button. |
| Settings/Exam toggle row | H gap 16: V text (title `label`, description `caption` secondary; fills) + Toggle 56×44. |
| Data row / Principle row | H gap 16, padding 12/0: [Principle: 20 px icon] + V text (title `label`; description `body-sm` secondary) + [Data: Secondary Button]. |
| Exam field (Course / Topics / …) | V gap 12: field head (V: title `label`; helper `caption` secondary) + Chips row (H gap 8, wraps). |
| Source panel | V gap 16, padding 32/24, fill `bg/surface`, 1 px left border; head H gap 8, height 44 (title `title` + IconButton). |
| Mobile bottom sheet | 390×416, V gap 12, padding 8/16/24/16, fill `bg/surface`, radius 16 (top), `shadow/lg`; grabber 40×4 (`border/strong`); head 44 high; over a full-screen scrim (`bg/scrim` @ 45%). |
| Quiz bar | H gap 24, padding 16/40, 77 high, `bg/surface`, 1 px bottom border: Secondary Button “Exit quiz” (icon `x`) · title block (V) · right-aligned “Question n of 10”. |
| Mobile App bar / Tab bar | App bar 61 high (H gap 8, padding 8, bottom border); Tab bar 69 high (padding 8, top border; 4 TabItems 94×52, icon 20 + `caption` label). |

---
## 8. Module-by-Module Specification

Conventions for every module below:
- "Visual structure" lists regions top→bottom / left→right with exact strings read from Figma.
- "Frontend behaviour" and "Backend integration" are **[Recommendation]** unless a Figma fact is cited; the file contains **no** behaviour specs, only pictures.
- Endpoint names are illustrative; no API exists in Figma. Data names refer to the models in section 13.
- "Acceptance criteria" are testable statements of fidelity to the frames.
- Shared nav: see section 6. Shared component rules: see section 7.

---

### 8.1 Authentication

**8.1.1 Purpose** — Let a student sign in or create an account with a university email; tell them why to trust the product.

**8.1.2 Figma frames** — `01 Auth / Sign in` (12:2), `01 Auth / Sign up` (12:55); both 1440×900. No mobile frame.

**8.1.3 Entry points** — App start when unauthenticated; "Create account" / "Sign in" tabs switch between the two frames. Entry from Terms / Privacy links or "Forgot your password?" has **no destination frame**.

**8.1.4 Visual structure** (both frames: H split, canvas background)
- **Brand panel** 640×900, fill `accent/subtle`, V, padding 80, gap 32:
  - Wordmark (mark 32×32 radius 8, fill `accent/default`, `icon/book` 18 white; "IntelliStudy" `text/title`).
  - Headline "Study from your own materials." `text/display` (40/48 Bold).
  - Subcopy "Upload your slides, notes and papers. IntelliStudy turns them into summaries, quizzes and answers — and shows exactly where every answer comes from." `text/body-lg`.
  - Trust points (3 rows, icon 20 + `text/body`): `icon/book` "Answers come only from your files." · `icon/file` "Every claim links to a page, slide or section." · `icon/lock` "Your files are private and isolated to your account."
- **Form side** 800×900, centred **Auth card** 440 wide, padding 40, gap 24, radius 16, fill `bg/surface`, stroke `border/default` 1, two shadows:
  - Tabs row: Tab "Sign in" (78) + Tab "Create account" (135). Selected differs per frame.
  - **Sign in**: heading "Welcome back" `text/h2`; Input "University email" (placeholder "name@university.edu", helper "Use the address your university gave you"); Input "Password" (placeholder "Your password", no helper, 72 high); Primary Button "Sign in" full width (358×44); text link "Forgot your password?" (`text/body-sm`, `text/link`, centred).
  - **Sign up**: heading "Create your account"; Input "Full name" (Filled, "Layla Hassan"); Input "University email" in **Error** state with value "layla.hassan@cairo-uni.com" and message "Enter an address ending in .edu"; Input "Password" (placeholder "At least 12 characters", helper "Use 12 or more characters. A phrase works well."); Primary Button "Create account"; legal line "By creating an account you agree to the Terms and the Privacy Policy. Your files stay private to you."

**8.1.5 Actions** — Switch tab; type; submit; "Forgot your password?" (no destination).

**8.1.6 UI states** — Drawn: Sign in Default; Sign up with Filled + Error + Default inputs. **Not drawn:** loading (Button Loading exists in the library), server error, wrong password, success/redirect, email verification, password reset, Terms/Privacy pages. → **Not verified in Figma**.

**8.1.7 Data requirements** — `User{ id, name, email }`; credentials. Validation rule shown: email must end in `.edu` (copy "Enter an address ending in .edu"); password min 12 characters (copy). Whether non-.edu universities are allowed is an **Open Question**.

**8.1.8 Frontend behaviour** — Validate on blur/submit; show Error state with message text; disable repeat submit while Loading; on success navigate to Dashboard (route not drawn). Keep Sign in / Sign up as two routes.

**8.1.9 Backend integration** — `POST /auth/signup`, `POST /auth/login`, session/token handling, `POST /auth/forgot-password` (no screen). Password policy server-side must match the 12-character copy. Email-domain rule server-side if confirmed.

**8.1.10 Responsive** — **Not verified in Figma.** The brand panel (640) cannot fit at 390; no mobile design exists.

**8.1.11 Accessibility** — Labels bound to inputs; error text `aria-describedby` + `aria-invalid`; tab order: tabs → fields → submit → forgot link; focus ring 2 px; 44 px targets; brand-panel trust list is decorative-plus-text (text must be readable).

**8.1.12 Acceptance criteria**
- Card is 440 wide, padding 40, radius 16 with two shadows.
- Error input shows the exact message "Enter an address ending in .edu" below the field in `danger/fg`.
- Primary button is 358×44 inside the card.
- Both frames reuse identical brand-panel content.

---

### 8.2 Dashboard

**8.2.1 Purpose** — Landing page: greet the student, recommend the next action, show streak, courses, weakest topics and recent activity.

**8.2.2 Figma frames** — `02 Dashboard` (12:123), 1440×1086. No mobile frame.

**8.2.3 Entry points** — After sign-in; Sidebar "Dashboard"; mobile Tab bar "Home" (no mobile frame).

**8.2.4 Visual structure** — Sidebar (Dashboard selected) + Main (V, padding 40/48/48/48, gap 32, 1080 content):
1. **Header**: greeting `text/h1` "Good afternoon, Layla"; subtitle `text/body` "Thursday, 22 October · 3 days to your Queueing Theory midterm"; Primary Button "Upload files" (136×44).
2. **Row A** (gap 24, 250 high):
   - **Next recommended action** (716 wide, fill `accent/subtle`, stroke `accent/subtle-border`, radius 16, padding 24): eyebrow `icon/target` + "NEXT RECOMMENDED ACTION"; title `text/h3` "Practise “Weaving: compile-time vs run-time”"; body "You answered 2 of 6 weaving questions correctly in your last two quizzes. A 10-question set built from Lecture 6 should help."; caption "Based on Quiz 3 and Quiz 4 · Aspect-Oriented Programming"; actions: Primary "Start 10-question quiz" + Ghost "Why this?".
   - **Study streak** (340 wide, surface card): `icon/flame` + "6-day streak" `text/h3`; "Your best is 9 days. Study today to keep it going."; week row F S S M T W T — 32×32 dots, **six filled `accent/default` dots with a check icon; the first (F) is an unfilled dot with a 1 px `border/strong` stroke (not studied)**; letters `text/caption`.
3. **Your courses**: heading "Your courses" `text/h2` + Ghost Button "New course"; three **Card** instances (344×162):
   - "Aspect-Oriented Programming" / "Pointcuts, advice and weaving across 12 lectures." / "All indexed" / "12 files · 74% mastery"
   - "Queueing Theory" / "M/M/1 queues, Little’s Law and network models." / "1 processing" / "9 files · 61% mastery"
   - "Operating Systems" / "Scheduling, memory management and file systems." / "All indexed" / "15 files · 82% mastery"
4. **Row C** (gap 24):
   - **Weakest topics** (528 wide card): title `text/h3`; 3 topic rows (MasteryRing Sm + name `text/body-strong` + course `text/caption` + Tag + Ghost Button "Practise"):
     - "Weaving: compile-time vs run-time" · Aspect-Oriented Programming · ring Weak 32% · Tag "Weak topic" (Danger)
     - "M/M/c queues and server utilisation" · Queueing Theory · Weak 41% · "Weak topic"
     - "Little’s Law applications" · Queueing Theory · Learning 56% · Tag "Learning" (Warning)
   - **Recent activity** (528 wide, 362 high): title `text/h3`; 4 rows (36×36 icon tile radius 8 + text `text/body` + time `text/caption`): `icon/quiz` "Quiz · Queueing Theory — 7 of 10" · 2 hours ago; `icon/layers` "Summary generated · Lecture 6 — Weaving" · Yesterday; `icon/message` "Asked 3 questions · Aspect-Oriented Programming" · Yesterday; `icon/upload` "Uploaded 4 files · Operating Systems" · 2 days ago.

**8.2.5 Actions** — Upload files; Start 10-question quiz; Why this? (explanation UI **not drawn**); New course (creation flow **not drawn**); open a course card; Practise (starts a topic quiz — flow not drawn); activity rows (clickable? **Not verified**).

**8.2.6 UI states** — Only the populated state is drawn. **Not drawn:** first-run/empty (no courses), loading, error, streak hidden (a Settings toggle hides it), no recommendation.

**8.2.7 Data requirements** — `User`, `Course[]` (+ file counts, processing flag, mastery %), `Recommendation`, `TopicMastery[]` (weakest 3), `ActivityItem[]` (type, text, time), streak `{current, best, days[7]}`, exam countdown ("3 days to your … midterm" → needs an exam date per course; where it comes from is an **Open Question**). Date and time-of-day greeting are computed client-side.

**8.2.8 Frontend behaviour** — Greeting by local time; relative times ("2 hours ago"); Card = link to workspace; Practise → starts targeted quiz; hide streak card if Settings "Show streak on dashboard" is Off.

**8.2.9 Backend integration** — `GET /dashboard` (aggregate) or the individual resources: courses, recommendations, weakest topics, activity, streak.

**8.2.10 Responsive** — **Not verified in Figma** (no mobile frame). 3-card course row and 2-column rows are 1080 wide.

**8.2.11 Accessibility** — One `h1`; sections as `h2`/`h3`; week dots need text ("Studied Saturday") because colour/shape alone is not enough; ring + tag text give level; buttons have specific names ("Practise Weaving: compile-time vs run-time").

**8.2.12 Acceptance criteria**
- Row A heights 250; recommendation card 716 wide, streak 340.
- Three Cards 344×162 with exact strings above.
- Weak rings use `mastery/weak` for 32% and 41%, `mastery/learning` for 56%.
- Streak shows 7 dots, 6 filled.

---

### 8.3 Course Workspace

**8.3.1 Purpose** — One course's hub: files and their processing status, course stats, topics and mastery, selected-file details.

**8.3.2 Figma frames** — `03 Course workspace` (15:158) 1440×900; mobile `M3 Course workspace` (22:1467) 390×844.

**8.3.3 Entry points** — Dashboard course card; Sidebar/Rail "Courses"; tab "Overview" from any course tab; "Ask your materials" button leaves to Chat.

**8.3.4 Visual structure (desktop)** — Rail (Courses selected) + Main (H):
- **File list** 300 wide, V, padding 24/16, gap 16, right border: head "Materials" `text/title` + "7 files" `text/caption`; Secondary Button "Add files" (267×44); 7 **file items** (radius 8, padding 8/12; selected = fill `accent/subtle` + stroke `accent/subtle-border`): icon `icon/file` + name `text/label` (wraps to 2 lines), status row indented 28:
  1. Lecture 1 — Introduction.pdf · Indexed (Success)
  2. Lecture 2 — Cross-cutting concerns.pdf · Indexed
  3. **Lecture 4 — Aspect-Oriented Programming.pdf · Indexed (selected)**
  4. Lecture 5 — AspectJ in practice.pptx · Indexed
  5. Lecture 6 — Weaving.pdf · Extracting (Accent) + "Reading pages…"
  6. Lecture 7 — Proxies.pdf · "Uploading 62%" (Accent)
  7. Exam notes.docx · Failed (Danger) + "Retry" (`text/label`)
- **Center** 728 wide, V, padding 32/40/40/40, gap 24: breadcrumb "Courses  /  Aspect-Oriented Programming"; title row H1 + Primary Button "Ask your materials" (180×44); Tabs (Overview selected); **Stats** row of 3 cards (205 wide): "Files indexed" `4 of 7` "2 processing · 1 failed"; "Topics found" `18` "across 4 indexed files"; "Course mastery" ring Sm 74% + "COURSE MASTERY" "Proficient" (`text/h3`); **Notice (Info)** "Scanned PDF detected in “Lecture 6 — Weaving.pdf”" / "We’re reading the pages with OCR. This can take a few minutes and some words may be misread."; **Topics card** (radius 16) header "Topics found in your materials" + "Mastery" and 5 rows: Cross-cutting concerns [Mastered · 94%] · Join points and pointcuts [Proficient · 78%] · Advice: before, after, around [Proficient · 71%] · Weaving: compile-time vs run-time [Weak · 32%] · AspectJ annotations [Not started].
- **File details** 340 wide, left border, padding 32/24: "SELECTED FILE"; name (`text/h3`) "Lecture 4 — Aspect-Oriented Programming.pdf"; Tag Indexed; meta rows (Pages 48 · Size 3.1 MB · Indexed 2 minutes ago · Topics found 6); buttons (full width 291): Primary "Open summary", Secondary "Ask about this file", Secondary "Generate quiz"; "TOPICS IN THIS FILE" + 4 chips (Join points, Pointcuts, Advice, Weaving).

**Mobile M3**: App bar (Back + "Aspect-Oriented Programming"); Body: Tabs (Overview selected); Stat course mastery (ring 74%, "COURSE MASTERY" "Proficient" "4 of 7 files indexed"); Notice Info "Reading a scanned PDF" / "“Lecture 6 — Weaving.pdf” is being read with OCR. This can take a few minutes."; Files head "Materials" + Secondary "Add" (86×44); 5 file items (358 wide; Lecture 4 pdf, Lecture 5 pptx, Lecture 6, Lecture 7, Exam notes) — Lecture 1 and 2 are **omitted** on mobile; Tab bar.

**8.3.5 Actions** — Select file; Add files (→ Upload flow); Ask your materials (→ Chat); Open summary (→ Summary); Ask about this file; Generate quiz; Retry (failed file); click a topic row (**Not verified**); switch tabs.

**8.3.6 UI states** — Drawn: mixed processing states within one course. **Not drawn:** empty course (EmptyState "No materials yet" exists as a component, not placed), loading skeleton (Card Loading exists but not for this), no file selected in details panel, error loading.

**8.3.7 Data requirements** — `Course`, `CourseMaterial[]` (name, type, status, progress %, page count, size, indexedAt, topicsCount, topics[]), `ProcessingStatus`, course stats (indexedCount/total, processing, failed, topicsFound), `TopicMastery[]` with level + %.

**8.3.8 Frontend behaviour** — Poll or stream status updates for files in progress; file selection drives the details panel; Tag text pattern "Uploading 62%".

**8.3.9 Backend integration** — `GET /courses/{id}`, `GET /courses/{id}/materials`, status updates (polling/SSE/WebSocket — **Open**), `POST /materials/{id}/retry`.

**8.3.10 Responsive** — Desktop 3 panes → mobile single column (see 5.2). The details panel on mobile and the Lecture 1/2 rows are **Not verified**.

**8.3.11 Accessibility** — File list as a listbox/list with `aria-selected`; Tags include text; status changes announced politely; Notice `role=status`.

**8.3.12 Acceptance criteria**
- Panes are 300 / 728 / 340 wide at 1440.
- Selected file item uses accent subtle fill + border.
- Stats read "4 of 7", "18", ring 74% Proficient.
- Mobile shows exactly 5 file items and the OCR notice.

---

### 8.4 Upload Flow

**8.4.1 Purpose** — Add PDF/DOCX/PPTX files and watch each file move through upload → extraction/OCR → indexed, with honest failure states.

**8.4.2 Figma frames** — `04 Upload flow` (15:393) 1440×1168; Prototype `P1 Upload` (22:1972). No mobile frame.

**8.4.3 Entry points** — Dashboard "Upload files"; workspace "Add files"/"Add"; EmptyState button.

**8.4.4 Visual structure** — Sidebar (Courses selected) + Main (padding 40/48/48/48, gap 32):
- Breadcrumb "Courses  /  Aspect-Oriented Programming  /  Add materials".
- Header: H1 "Add materials"; "PDF, Word (.docx) and PowerPoint (.pptx). Summaries, chat and quizzes are built only from these files."
- **Dropzone** 1080×248, fill `accent/subtle`, **2 px dashed (8 / 6) `accent/default` stroke, aligned inside**, radius 16, padding 32, centred: 56 circle (`bg/surface`) with `icon/upload` 24; "Drag files here, or choose from your computer" `text/title`; "Up to 100 MB per file · text, tables and images with text are read" `text/body-sm`; Primary Button "Choose files" (139×44).
- List head: "6 files" `text/h3` + "1 indexed · 3 in progress · 2 need attention" `text/body-sm`.
- Six **FileUploadRow** (1080 wide, gap 12): Uploading ("Lecture 7 — Queueing Networks.pdf"), Extracting ("Lecture 6 — Weaving.pdf"), OCR ("Scanned handout — Week 6.pdf"), Indexed ("Lecture 4 — Aspect-Oriented Programming.pdf"), Unsupported ("Lab recording.mp4"), Empty ("Blank template.pdf"). Copy per status in 7.16.
- Privacy note: `icon/lock` 16 + "Files are processed in your private account space and are never shared with other students." (`text/body-sm`).

**8.4.5 Actions** — Drag & drop; Choose files; Cancel (uploading/extracting/OCR); Open (indexed → Summary); Remove (unsupported/empty); Retry (failed — row not drawn here).

**8.4.6 UI states** — Seven row statuses exist (Failed only in the library). Not drawn: dropzone drag-over/hover, empty list, upload error toast, offline, duplicate file, file-size exceeded (100 MB figure is a **placeholder → Open**), page limit.

**8.4.7 Data requirements** — `UploadItem{ id, fileName, mimeType, size, status, progress, detail, pageCount }`, `ProcessingStatus` enum: uploading, extracting, ocr, indexed, failed, unsupported, empty.

**8.4.8 Frontend behaviour** — Validate type client-side (.pdf/.docx/.pptx); unsupported → row with "Not supported"; chunked/resumable upload **Open**; list summary counts computed ("1 indexed · 3 in progress · 2 need attention" counts uploading+extracting+OCR = 3 in progress; unsupported+empty = 2 need attention).

**8.4.9 Backend integration** — `POST /courses/{id}/materials` (multipart), status endpoint/stream, `DELETE /materials/{id}`, cancel; backend must expose OCR detection and empty-text detection to drive the OCR/Empty statuses.

**8.4.10 Responsive** — **Not verified in Figma.**

**8.4.11 Accessibility** — Dropzone is a button + keyboard-accessible file input; each row announces status text; progress via role=progressbar; error rows state the reason in text.

**8.4.12 Acceptance criteria**
- Dropzone shows a 2 px dashed (8/6) accent stroke and exact copy.
- All six statuses render with the border colours in 7.16.
- Indexed row is clickable (prototype goes to Summary).
- "100 MB" is displayed only if confirmed (otherwise remove from copy and log an Open Question).

---

### 8.5 Summary

**8.5.1 Purpose** — Structured summary of a file, every statement with a citation; open the exact source passage.

**8.5.2 Figma frames** — `05 Summary` (15:606) 1440×900; mobile `M5 Summary` (22:1580); Prototype `P2 Summary` (22:2015).

**8.5.3 Entry points** — Workspace "Open summary"; Upload row "Open"; tab "Summary".

**8.5.4 Visual structure (desktop)** — Rail + Main: **Center** 988 wide (padding 32/48/48/48, gap 24) + **Source panel** 380:
- Breadcrumb "Courses  /  Aspect-Oriented Programming  /  Lecture 4".
- Title row: H1 "Summary: Aspect-Oriented Programming"; meta: Tag Indexed + "Lecture 4 — Aspect-Oriented Programming.pdf · 48 pages · generated 2 minutes ago" (`text/body-sm`); Secondary Button "Regenerate" (136×44).
- Tabs (Summary selected).
- Intro "Every statement links to the page it came from. Select a badge to see the exact passage."
- **5 collapsible sections** (892 wide, radius 12, 1 px border; header 60 high = 44×44 toggle target + title `text/title` + count caption):
  1. Cross-cutting concerns · "3 sources" · **expanded** (3 bullets: "Concerns such as logging, security checks and transactions are scattered across many classes." [1]; "This scattering and tangling makes code harder to change and test." [1][2]; "An aspect modularises such a concern in one place instead of repeating it." [3])
  2. Join points and pointcuts · "2 sources" · **expanded** ("A join point is a well-defined point in program execution, such as a method call or field access." [4]; "A pointcut is an expression that selects a set of join points." [4][5])
  3. Advice: before, after, around · "2 sources" · collapsed
  4. Weaving: compile-time vs run-time · "3 sources" · collapsed
  5. Key terms · "6 terms" · collapsed
- **Source panel** (fill surface, left border, padding 32/24, gap 16): head "Source [1]" `text/title` + IconButton close; SourceCard **Selected** ("[1]", "Lecture 4 — Aspect-Oriented Programming.pdf", "Page 3 · 1.1 Cross-cutting concerns", "Logging, security checks and transaction handling are typical cross-cutting concerns: their code is scattered across many classes and tangled with the business logic of each one.", "Open in file"); "ALL SOURCES IN THIS SUMMARY" + 5 rows (badge + text): [1] Page 3 · 1.1 Cross-cutting concerns (Active) · [2] Page 4 · 1.2 Tangling · [3] Page 6 · 2.1 What is an aspect? · [4] Page 12 · 3.1 Join points · [5] Page 14 · 3.2 Pointcuts.

**Mobile M5**: App bar "Summary"; H1-ish "Summary: Aspect-Oriented Programming"; meta Tag Indexed + "48 pages · 2 min ago"; sections (Cross-cutting concerns expanded with 2 statements — "Concerns such as logging and security are scattered across many classes." [1] / "An aspect modularises such a concern in one place." [2]; Join points and pointcuts; Advice: before, after, around; **Weaving** — collapsed, chevronRight; expanded uses chevronDown); **scrim** (390×844, `bg/scrim` @45%) + **Source sheet** 390×416 (grabber 40×4, "Source [1]" + IconButton, SourceCard Selected with shorter passage, Secondary Button "Open page 3 in file" 358×44). No tab row on mobile Summary and no Regenerate.

**8.5.5 Actions** — Expand/collapse section; click citation badge → source panel/sheet updates and badge becomes Active; "Open in file" / "Open page 3 in file" (document viewer **not drawn**); Regenerate; close source.

**8.5.6 UI states** — Drawn: loaded, source open. Not drawn: generating/loading, regenerating, failed generation, summary for a file with OCR warnings, no source selected (panel empty state), citation to a missing page.

**8.5.7 Data requirements** — `Summary{ id, materialId, generatedAt, sections[] }`, `SummarySection{ id, title, sourceCount, statements[], collapsed }`, statements with `Citation[]`, `Citation{ index, materialId, fileName, locator(page/slide/section), title, passage }`, `SourcePassage` (passage + surrounding text). Section "Key terms" has a term count ("6 terms") not "sources" → term list model **Open**.

**8.5.8 Frontend behaviour** — One citation active at a time; panel always shows its list of all sources; section toggle target 44×44 is the whole header's left control; expansion state local.

**8.5.9 Backend integration** — `GET /materials/{id}/summary`, `POST …/summary/regenerate`, `GET /citations/{id}` (passage + context). Summaries must be produced with citations or not shown.

**8.5.10 Responsive** — Panel → bottom sheet (5.2).

**8.5.11 Accessibility** — Sections as disclosure widgets (`aria-expanded`); citation badges are buttons with names; sheet is a dialog with focus trap and a close button; scrim click closes **[Recommendation]**.

**8.5.12 Acceptance criteria**
- Sections 1–2 expanded, 3–5 collapsed at load.
- Active badge `[1]` is solid accent in both statement and source list.
- Mobile sheet is 390×416 over a 45% scrim.

---

### 8.6 Chat

**8.6.1 Purpose** — Ask questions that are answered only from the course materials, with visible honesty states and cited sources.

**8.6.2 Figma frames** — Desktop: `06 Chat / Answered` (17:482), `… / Answered — source open` (17:615), `… / Refused` (17:780, 1440×1060), `… / Partial` (17:927), `… / Loading` (17:1048), `… / Low confidence` (17:1147). Mobile: `M6 Chat` (22:1682). Prototype: `P3 Chat — answered`, `P4 Chat — source open`.

**8.6.3 Entry points** — "Ask your materials" (workspace), "Ask about this file", tab "Chat", Rail.

**8.6.4 Visual structure (desktop, all states)** — Rail + **Chat column** (V, full 1368 wide or 988 when source panel open):
- **Header** (padding 24/40/0/40, gap 16, bottom border): breadcrumb "Courses  /  Aspect-Oriented Programming"; title row (title in **`text/h2`**, not h1) + Secondary Button "New conversation" (179×44); Tabs (Chat selected, 413 wide).
- **Messages** (padding 40, gap 32): a `ChatMessage / User` (right-aligned 520-wide bubble inside the message column) then an assistant ChatMessage of the state's Type; the 760-wide message column is **centred** in the chat column (x = 304 of 1368; centred in 988 when the panel is open — computed, not read).
- **Composer area** (padding 16/40/24/40, gap 8, top border, fill `bg/canvas`): ChatComposer (760×102) + disclaimer `text/caption` "Answers come only from your uploaded files. Check the cited page before relying on them."
- Per-state content (exact):
  - **Answered** — User: "What is the difference between a join point and a pointcut?" · caption "Answered from 2 files" · "A join point is a point in program execution, such as a method call." [1] · "A pointcut is an expression that selects a set of join points." [2] · "Advice then runs at every join point the pointcut matches." [1][2] · SOURCES: [1] Lecture 4 · p. 12 · [2] Slides 7 · Pointcuts.
  - **Answered — source open** — same conversation; chat column narrows to 988; Source panel (380): head "Source [1]" + close; "EXACT PASSAGE"; SourceCard Selected ("Lecture 4 — Aspect-Oriented Programming.pdf", "Page 12 · 3.1 Join points", "A join point is a well-defined point in the execution of a program, such as a method call, a field access or the handling of an exception."); **Context** block (fill `bg/subtle`, padding 16) "SURROUNDING TEXT · PAGE 12" + "Aspect-oriented languages need a model of where aspects can attach. In AspectJ this model is built on join points; a pointcut selects the join points where advice should run."; Source nav: Secondary "Previous" (116×44, with a **right-pointing** `icon/chevronRight`; Show icon = true) + Secondary "Open page 12" (151×44) — **no "Next" button**; "ALL SOURCES IN THIS ANSWER" + rows [1] Lecture 4 · Page 12 · Join points (Active) / [2] Slides 7 · Pointcuts.
  - **Refused** — User: "How does Rust’s macro system expand code at compile time?" · caption "Not found in your materials" · title "I couldn’t find this in your materials" · "Your files for “Aspect-Oriented Programming” don’t mention Rust macros, so I won’t guess. Here is the closest material I found:" · SourceCard ([1] "Lecture 6 — Weaving.pdf", "Page 4 · Compile-time weaving", "Weaving inserts advice into the program at compile time, load time or run time, depending on the weaver.", "Open in file") · "TRY ASKING" + chips "Weaving at compile time", "Join points vs pointcuts".
  - **Partial** — User: "How can a pointcut match methods by name or signature?" · caption "Partly answered from 1 file" · "A pointcut can match method calls by name, signature or annotation." [1] · "Wildcards let one pointcut select many methods at once." [1] · block "Only part of your question is covered" / "Your materials explain how pointcuts match methods, but not how they match fields. I haven’t added anything beyond what the lecture says." · SOURCES [1] Lecture 4 · p. 14.
  - **Loading** — User: "Why is compile-time weaving faster than run-time weaving?" · "IntelliStudy" · "Working" · "Searching 12 files…"; composer in Loading state (placeholder "Searching your materials…", button "Answering…").
  - **Low confidence** — User: "Is compile-time weaving always faster than run-time weaving?" · caption "Answered from 2 files" · "Weaving at compile time produces faster code than run-time weaving." [1] · "Run-time weaving allows aspects to be added without rebuilding." [2] · warning block "Low confidence" / "The two sources describe this a little differently. Check the cited passages before relying on this answer." · SOURCES [1] Lecture 6 · p. 4 · [2] Slides 9 · Weavers.

**Mobile M6**: App bar "Chat · Aspect-Oriented Programming"; Body with user bubble (300 wide, `bg/subtle`, padding 12/16) and the **Answered** message (402 wide frame); Composer area (padding 12/16/16/16) with ChatComposer 358×102. **Defect:** the Body frame is 434 px wide inside a 390 px frame (content overflows by 44 px). Do not reproduce the overflow. **No Tab bar** on M6.

**8.6.5 Actions** — Type + send; click citation badge/source chip → open source panel (desktop) / sheet (mobile, **not drawn**); Open in file; Previous (source navigation); suggestion chips ("TRY ASKING") send a prefilled question; New conversation; copy/regenerate/feedback **not drawn**.

**8.6.6 UI states** — Answered, Refused, Partial, Loading, Low confidence (all drawn); Composer Default/Loading. **Not drawn:** empty conversation (first visit), error/timeout, offline, conversation history list, long answers, streaming text, stop-generation control, per-file scoped chat ("Ask about this file" scope text), mobile versions of states other than Answered.

**8.6.7 Data requirements** — `ChatConversation{ id, courseId, messages[] }`, `ChatMessage{ id, role, state (ChatAnswerState), text blocks, citations[], notice?, suggestions[], filesSearched, filesUsed }`, `ChatAnswerState` = answered | refused | partial | loading | low_confidence. Also `Citation` and `SourcePassage` for the panel. Scope text counts ("12 files") **vs** other counts in the file (7, 9) — **Open**.

**8.6.8 Frontend behaviour** — Show Loading immediately after send ("Searching N files…"); replace with final state; citations clickable; panel opens beside the chat and shrinks the chat column to 988; composer disabled-looking Loading state prevents double send; disclaimer always visible.

**8.6.9 Backend integration** — `POST /courses/{id}/chat` returning a structured answer: state, paragraphs with citation indexes, sources, optional notice text, suggestions. The refusal/partial/low-confidence decision is **backend logic**; the UI only renders the state. Never invent citations.

**8.6.10 Responsive** — Mobile M6 answered only; panel → bottom sheet by analogy with M5 (**Not verified**).

**8.6.11 Accessibility** — Message list `role="log"`/`aria-live=polite`; each state's caption is text; badges named; refused/low-confidence icons/labels are text-first; composer label "Ask a question about your materials".

**8.6.12 Acceptance criteria**
- Five assistant states render with the exact copy above.
- Source-open frame shows chat column 988 + panel 380, no "Next" button.
- Composer disclaimer text is present in every desktop chat frame.
- Mobile body does not exceed 390 px.

---

### 8.7 Quiz

**8.7.1 Purpose** — Answer generated questions one at a time (multiple choice or short answer) without distractions.

**8.7.2 Figma frames** — `07 Quiz / Question (multiple choice)` (18:1013), `07 Quiz / Short answer` (18:1095); Prototype `P5 Quiz — question` (22:2237). Review is module 8.8. No mobile frame.

**8.7.3 Entry points** — Tab "Quiz"; "Generate quiz"; "Start 10-question quiz"; "Start quiz"; "Practise".

**8.7.4 Visual structure** — Rail (not Sidebar) + Main (V, 1368 wide):
- **Quiz bar** 77 high (padding 16/40, gap 24, fill surface, bottom border): Secondary "Exit quiz" (115×44); title block "Quiz · Aspect-Oriented Programming" + "Advice and weaving · 10 questions"; right text "Question 6 of 10" (7 of 10 on Short answer).
- **ProgressBar** 1368×8 Active **Value=60** directly under the bar (both frames).
- **Quiz column** 720 wide, centred, padding 48/0, gap 24.
  - **Multiple choice**: eyebrow "MULTIPLE CHOICE"; question in `text/h2` "Which statement best describes “around” advice in AspectJ?"; "Choose one answer."; 4 AnswerOptions (gap 12): "It runs only after a join point has completed normally." · **Selected:** "It can run code before and after a join point, and decide whether the original code runs at all." · "It selects the set of join points that an aspect applies to." · "It copies the advice code into every class at design time."; Actions: Ghost "Skip question" (123×44), spacer, Primary "Check answer" (152×44).
  - **Short answer**: eyebrow "SHORT ANSWER"; "In your own words, explain what weaving means in aspect-oriented programming."; hint "Two or three sentences are enough. Your answer is compared with your uploaded materials."; **Answer field** 720×160 (fill surface, **2 px accent stroke** = focused, radius 12, padding 16) containing "Weaving is the process of inserting the advice from aspects into the base program at the join points selected by pointcuts. It can happen at compile time, at load time or while the program runs."; counter row "Saved as a draft" (left) / "196 / 600" (right); same Actions.

**8.7.5 Actions** — Select an option; type answer; Skip question; Check answer (→ Review in prototype); Exit quiz (confirm dialog **not drawn**).

**8.7.6 UI states** — Drawn: option Default + Selected; short-answer focused with text. **Not drawn:** per-question feedback immediately after Check (Settings has "Show answer explanations right away" — the immediate-feedback state is not designed), timer, first question, last question, submitting, error, resumed-draft, exit confirmation, loading questions.

**8.7.7 Data requirements** — `Quiz{ id, courseId, title, topics, questions[] }`, `Question{ id, type (multiple_choice|short_answer), prompt, options[], hint, topicId, source }`, `QuizAttempt{ answers, progress }`. Short-answer limit **600 characters** is shown in the counter (treated as product copy; confirm → Open). Draft auto-save text "Saved as a draft".

**8.7.8 Frontend behaviour** — One question per screen; progress "Question n of N"; draft autosave for short answer; selected option keeps 2 px accent border.

**8.7.9 Backend integration** — `POST /courses/{id}/quizzes` (generate), `GET /quizzes/{id}`, `PUT /attempts/{id}/answers/{questionId}`, `POST /attempts/{id}/submit`. Short-answer grading is "compared with your uploaded materials" → backend semantic grading (details **Open**).

**8.7.10 Responsive** — **Not verified in Figma.**

**8.7.11 Accessibility** — `radiogroup` for options; question is the group label; counter `aria-live` off; progress bar text equivalent; Exit has a confirm dialog **[Recommendation]**.

**8.7.12 Acceptance criteria**
- Quiz column is 720 wide with 12 px gap between options.
- Selected option has accent subtle fill and 2 px accent border.
- Both frames show the 8 px progress bar at Value 60 (known inconsistency with "Question 7 of 10" on the short-answer frame; see section 16).

---
### 8.8 Quiz Review

**8.8.1 Purpose** — After a quiz: show the score, which questions were wrong, why, and the cited source.

**8.8.2 Figma frames** — `07 Quiz / Review` (18:1165) 1440×1280; Prototype `P6 Quiz — review` (22:2279). No mobile frame.

**8.8.3 Entry points** — "Check answer" / quiz completion (in the prototype Check answer jumps straight here from question 6). How a real finished quiz arrives here is **not drawn**.

**8.8.4 Visual structure** — Rail + Main (1368): Quiz bar (title block "Quiz · Aspect-Oriented Programming" + "Answer review"; right text "Review"), ProgressBar Value=100, **Quiz column** 720 (padding 48/0, gap 24):
- **Result summary** card (720×162, padding 24, gap 24): MasteryRing Lg (Proficient, "70%", "Proficient"); text "7 of 10 correct" (`text/h2`) + "Strong on pointcuts. Review weaving and advice order before the next attempt." ; Secondary Button "Retry wrong answers" (200×44).
- **Question review** card (720×634, padding 24, gap 16): head Tag "Incorrect" (Danger) + "Question 6 of 10"; question "Which statement best describes “around” advice in AspectJ?"; AnswerOption **Incorrect (your answer)** "It runs only after a join point has completed normally." + "Incorrect"; AnswerOption **Correct** "It can run code before and after a join point, and decide whether the original code runs at all." + "Correct"; **Explanation** block (fill `bg/subtle`, padding 16): "WHY" + "Around advice wraps the join point: it can call proceed() to run the original code, skip it or change its result." + badge [1]; **SourceCard** Default ([1] "Lecture 5 — AspectJ in practice.pptx", "Slide 9 · Advice kinds", "Around advice surrounds the join point. It decides whether and how the original computation executes by calling proceed().", "Open in file").
- **Collapsed question rows** (720×58, padding 16/24, border, chevron right): Tag "Correct" — "Question 7 · What does a pointcut select?"; Tag "Partly correct" (Warning) — "Question 8 · Name one advantage of run-time weaving."; Tag "Correct" — "Question 9 · Which tool weaves classes at load time?". Questions 1–5 and 10 are not shown (list continuation **not drawn**).

**8.8.5 Actions** — Retry wrong answers; expand a collapsed question; badge/"Open in file"; Exit (bar button not shown on review).

**8.8.6 UI states** — Drawn: one expanded wrong answer + collapsed others. **Not drawn:** perfect score, zero score, all-correct (no "Retry"), short-answer review, partially-correct expanded, loading results.

**8.8.7 Data requirements** — `QuizAttempt{ score, total, level }`, `QuestionResult{ questionId, status (correct|incorrect|partial), selected, correctAnswer, explanation, citation }`, `TopicMastery` summary line ("Strong on pointcuts…" is generated advice text).

**8.8.8 Frontend behaviour** — One question expanded at a time **[Recommendation]**; Retry creates a new attempt with wrong/partial questions; ring colour/label from the score level (70% → Proficient).

**8.8.9 Backend integration** — `GET /attempts/{id}/results`; `POST /attempts/{id}/retry-missed`.

**8.8.10 Responsive** — **Not verified in Figma.**

**8.8.11 Accessibility** — Correct/Incorrect shown with words + colour; collapsed rows are disclosure buttons; explanation citation is a button.

**8.8.12 Acceptance criteria**
- Ring reads 70% / Proficient / "7 of 10 correct".
- Incorrect answer uses danger tokens, correct uses success tokens, both with text labels.
- Row 8 uses the Warning tone "Partly correct".

---

### 8.9 Analytics

**8.9.1 Purpose** — Show mastery per topic, weak topics, trends and recommended actions for a course (or all courses).

**8.9.2 Figma frames** — `08 Analytics` (20:1139) 1440×1244; mobile `M8 Analytics` (22:1742); Prototype `P7 Analytics` (22:2339).

**8.9.3 Entry points** — Sidebar/Rail "Analytics", course tab "Analytics", mobile Tab bar, prototype last step.

**8.9.4 Visual structure (desktop)** — Sidebar (Analytics selected) + Main (padding 40/48/48/48, gap 32):
- Page header: H1 "Analytics"; "Based on your quizzes and exams in Aspect-Oriented Programming."; Primary Button "Build personalised exam" (219×44).
- **Course filter** (Chip row): "Aspect-Oriented Programming" (Selected) · "Queueing Theory" · "Operating Systems" · "All courses".
- **Stats** (4 cards 258 wide, gap 16): Overall mastery (ring Sm 72% + "OVERALL MASTERY" "Proficient"); "QUIZZES TAKEN" 14 "last 30 days"; "AVERAGE SCORE" 76% "+8 points since September"; "STUDY STREAK" "9 days" "best: 12 days".
- **Grid** (gap 24): **Left column** 656:
  - **Mastery per topic** card (440): head "Mastery per topic" + "Sorted weakest first"; 6 rows (name / 160×8 bar / % / 96-wide Tag cell):
    Weaving: compile-time vs run-time 32% [Weak] · Advice: order of execution 48% [Weak] · AspectJ annotations — [Not started] · Advice: before, after, around 71% [Proficient] · Join points and pointcuts 78% [Proficient] · Cross-cutting concerns 94% [Mastered]. Bar track fill `border/default`; bar fill colour `color/mastery/<level>` (verified for Weak).
  - **Score history** card (362): head "Score history" + "Last 8 quizzes and exams"; bar chart 606×240 with 8 columns (each 69 wide, bar 32 wide): Sep 14 52% · Sep 21 58% · Sep 28 61% · Oct 3 64% · Oct 9 70% · Oct 14 68% · Oct 18 74% · Oct 21 78%; each column = value label above, bar, date below; footnote "Darker bars are at or above the 70% proficiency threshold." (bar height = value × 1.6 px, i.e. 100% = 160 px of the 240 px area; fill `accent/default` for values ≥ 70 (Oct 9, Oct 18, Oct 21) and `accent/subtle-border` for values < 70). Topic-row bar fills: width = % × 160 px (min 4 px for “Not started”), colour = `color/mastery/<level>` (weak ×2, not-started, proficient ×2, mastered)..
- **Right column** 400: **Weak topics** card (surface card; the two inner items use fill `danger/bg` + stroke `danger/border`): title "Weak topics"; item "Weaving: compile-time vs run-time" 32% "3 of 4 questions missed"; item "Advice: order of execution" 48% "Missed in the last 2 quizzes". **Recommended next** card: title "Recommended next"; 3 action tiles (fill `bg/subtle`, padding 16): `icon/layers` "Re-read the Weaving summary" / "Starts with pages 4–9 of Lecture 6, where you missed 3 questions." / Primary "Open summary"; `icon/quiz` "Take a 10-question quiz on advice order" / "Targets the two weakest topics. About 12 minutes." / Secondary "Start quiz"; `icon/target` "Build a personalised exam" / "Mixes all topics and weights weak ones higher." / Secondary "Build exam".

**Mobile M8**: App bar "Analytics" (41 high, no back); Course filter (2 chips visible: AOP Selected, Queueing Theory; wraps, 96 high); Stats 2 cards (Overall mastery ring 72%; Average score 76% "+8 pts since Sep"); "Mastery per topic" 4 rows (Weaving 32% Weak · Advice: order of execution 48% Weak · AspectJ annotations Not started · Join points and pointcuts Proficient; row = name + Tag, then bar); "Recommended next": "Re-read the Weaving summary. You missed 3 questions on pages 4–9." + Primary "Open summary" (324×44); Tab bar.

**8.9.5 Actions** — Change course filter (filters all numbers); Build personalised exam (→ Exam builder); recommendation buttons; row/bar click (**not drawn**).

**8.9.6 UI states** — Populated only. **Not drawn:** no data yet ("Not started" everywhere), loading, error, "All courses" view, tooltips on bars, empty score history.

**8.9.7 Data requirements** — `AnalyticsSummary{ overallMastery, quizzesTaken (30 days), averageScore, deltaSince, streak{current,best} }`, `TopicMastery[]`, score history `[{date, scorePct}]` (8 items), weak topics with a reason line, `Recommendation[]` (icon, title, body, action).

**8.9.8 Frontend behaviour** — Sort topics weakest first with Not started placed after the Weak ones as drawn (sort rule **Open**); bar fill width = % of 160; thresholds map to Tag words (≥ 90 Mastered, 70–89 Proficient, 50–69 Learning, below 50 Weak, none Not started — **Open**); chart bars scale 0–100% against 240 px height area.

**8.9.9 Backend integration** — `GET /analytics?courseId=` (or `all`), derived from quiz and exam attempts; recommendation generation is backend/ML (**Open**).

**8.9.10 Responsive** — See 5.2: Score history, Weak topics, and 2 of 3 recommendations are dropped on mobile.

**8.9.11 Accessibility** — Charts need a text/table alternative (values are already printed above bars); bars carry text labels; Tag words convey level; ring has text equivalent.

**8.9.12 Acceptance criteria**
- Left 656 / right 400 with 24 gap; four 258 stat cards.
- Topic order and values exactly as listed.
- Chart shows 8 columns with the listed dates and values.
- Known data mismatch: overall mastery 72% vs 74% elsewhere (section 16).

---

### 8.10 Personalised Exam Builder

**8.10.1 Purpose** — Configure a practice exam from a course's indexed files, with weak topics pre-selected.

**8.10.2 Figma frames** — `09 Exam / Builder` (20:1384) 1440×1000. No mobile.

**8.10.3 Entry points** — Sidebar "Personalised exam"; Analytics "Build personalised exam" / "Build exam".

**8.10.4 Visual structure** — Sidebar (Personalised exam selected) + Main: page header H1 "Personalised exam" + "Build a practice exam from your own materials. Questions always cite their source."; **Grid** (gap 24): **Exam settings** card (676 wide, padding 24, gap 24, radius 16):
- Field **Course**: "Course" / "Questions come only from this course’s indexed files."; chips AOP (Selected) · Queueing Theory · Operating Systems.
- Field **Topics**: "Topics" / "Weak topics are pre-selected and weighted higher."; chips (multi): Weaving: compile-time vs run-time ✔ · Advice: order of execution ✔ · Advice: before, after, around ✔ · Join points and pointcuts · Cross-cutting concerns · AspectJ annotations ✔.
- Field **Number of questions**: chips 10 · **20 (Selected)** · 30.
- Field **Question types**: chips Multiple choice ✔ · Short answer ✔.
- Toggle row "Timed exam" / "45 minutes. The timer is visible but never blocks you from finishing." (On).
- Toggle row "Focus on weak topics" / "About 60% of questions come from topics under 50% mastery." (On).
- **Exam preview** card (380 wide, padding 24, gap 16): "Exam preview"; rows Questions **20** · Time **45 minutes** · Topics **4 selected** · Weak-topic share **about 60%** · Sources **9 indexed files**; Notice Info "Generated from your files" / "Each question links back to the page it came from, so you can check it yourself."; Primary "Start exam"; Ghost "Save settings for later".

**8.10.5 Actions** — Choose course; toggle topics; choose count; toggle types; toggle Timed/Focus; Start exam (exam-taking screen **not drawn**; reuses the quiz screens? **Open**); Save settings for later.

**8.10.6 UI states** — Default only. **Not drawn:** zero topics selected (disabled Start), generating, no indexed files, error, saved confirmation (Toast exists as component).

**8.10.7 Data requirements** — `PersonalizedExam{ courseId, topicIds[], questionCount, questionTypes[], timed, timeLimitMinutes, focusWeak, weakShare }`, topics with mastery (to pre-select Weak), indexed-file count per course. Time and weak-share (45 min, 60%) are **placeholder copy → Open**. Whether time scales with question count is **not drawn**.

**8.10.8 Frontend behaviour** — Preview rows update live from selections (Questions = count; Topics = "n selected"; Time shown only if Timed); weak topics pre-selected on load.

**8.10.9 Backend integration** — `POST /exams` (generate), `POST /exam-presets` (save), `GET /courses/{id}/topics`.

**8.10.10 Responsive** — **Not verified in Figma.**

**8.10.11 Accessibility** — Chip groups with group labels; toggles as switches with descriptions; preview as a labelled region with live updates polite.

**8.10.12 Acceptance criteria**
- Settings 676 + preview 380, gap 24.
- Four topics selected ⇒ "4 selected"; 20 questions ⇒ "20".
- Selected chips show check + accent tint.

---

### 8.11 Exam Results

**8.11.1 Purpose** — Show a finished personalised exam: score, per-topic breakdown, next step, mastery update.

**8.11.2 Figma frames** — `09 Exam / Results` (20:1576) 1440×1100. No mobile.

**8.11.3 Entry points** — After an exam (flow not drawn).

**8.11.4 Visual structure** — Sidebar (Personalised exam selected) + Main: header H1 "Exam results" / "Personalised exam · Aspect-Oriented Programming · 20 questions · 38 minutes" + Secondary "Download summary" (191×44); **Score row** (gap 24): **Score** card (528×162; ring Lg 75% Proficient; "15 of 20 correct" + "Up 11 points from your last personalised exam."); **Next step** card (528×190): "Recommended next" + "Review the five questions you missed on weaving and advice order, then retake only those." + Primary "Retake missed questions" (223×44) + Secondary "Review answers" (167×44). **Results by topic** card (padding 24): rows (name · "n / m" · 200×8 bar · % · Tag): Weaving: compile-time vs run-time 2 / 5 · 40% [Weak] · Advice: order of execution 3 / 4 · 75% [Proficient] · Advice: before, after, around 4 / 5 · 80% [Proficient] · AspectJ annotations 3 / 3 · 100% [Mastered] · Join points and pointcuts 3 / 3 · 100% [Mastered]. **Notice (Info)** "Your mastery scores were updated" / "Weaving moved from 32% to 40%. Analytics now reflects this exam."

**8.11.5 Actions** — Download summary (format **Open**); Retake missed questions; Review answers (review screen for exams **not drawn**; may reuse Quiz Review).

**8.11.6 UI states** — Single populated state. Not drawn: loading/grading, perfect/zero, short-answer pending grading, exam abandoned/time out.

**8.11.7 Data requirements** — `QuizAttempt`/exam result (score 15/20, duration 38 min, delta +11 vs previous), per-topic `{correct,total,pct,level}`, mastery delta per topic. Sample data sums: 2+3+4+3+3 = 15 correct of 5+4+5+3+3 = 20.

**8.11.8 Frontend behaviour** — Tag/ring colours from percentage level; bar width = % of 200; Notice text derived from mastery delta.

**8.11.9 Backend integration** — `GET /exams/{id}/results`; mastery update is a backend side-effect; `POST /exams/{id}/retake-missed`.

**8.11.10 Responsive** — **Not verified in Figma.**

**8.11.11 Accessibility** — Ring and bars have text; table as a real table/grid; Notice `role=status`.

**8.11.12 Acceptance criteria**
- Counts add to 15/20 and the five topic rows match above.
- Ring 75% Proficient; score row two 528-wide cards.

---

### 8.12 Settings

**8.12.1 Purpose** — Profile, study preferences, appearance, notifications.

**8.12.2 Figma frames** — `10 Settings` (21:1349) 1440×1320. No mobile (the mobile Tab bar has a Settings tab, but no frame).

**8.12.3 Entry points** — Sidebar/Rail "Settings"; mobile Tab bar.

**8.12.4 Visual structure** — Sidebar (Settings selected) + Main: header H1 "Settings" / "Manage your profile, study preferences and notifications."; **Content** column 760 (gap 24), four cards (padding 24, radius 16, surface, border):
- **Profile** (482): title; Inputs (Filled, 710 wide): "Full name" "Layla Hassan" · "University email" "l.hassan@university.edu" · "Programme" "Computer Science · Year 3"; Primary "Save changes" (150×44).
- **Study preferences**: toggle rows (title `text/label` `text/primary`; description `text/caption` `text/secondary`): "Daily study reminder" / "A quiet nudge at 6:00 PM. Never more than one per day." (On) · "Show streak on dashboard" / "Hide it if streaks add pressure." (On) · "Show answer explanations right away" / "Otherwise explanations appear after you finish the quiz." (On).
- **Appearance**: chips "Light" (Selected) · "Dark" · "Match system".
- **Notifications**: "Email me when files finish processing" / "Only for files larger than 20 MB." (Off) · "Weekly progress summary" / "Sent on Sundays." (On).

**8.12.5 Actions** — Edit profile fields; Save changes; toggle preferences (immediate vs requires save **not drawn**); choose theme; change password/email verification **not drawn**.

**8.12.6 UI states** — Default only. **Not drawn:** unsaved changes, saving, saved Toast, validation error, reminder time picker, dark-theme application.

**8.12.7 Data requirements** — `User` + `UserSettings{ dailyReminder, reminderTime ("6:00 PM" placeholder), showStreak, explanationsImmediate, theme (light|dark|system), emailOnProcessed, emailThresholdMB (20 placeholder), weeklySummary }`.

**8.12.8 Frontend behaviour** — Theme chip switches between `Color/Light` and `Color/Dark` token sets; "Match system" follows `prefers-color-scheme`; "Show streak" hides dashboard card; "Show answer explanations right away" changes quiz feedback timing (the immediate-feedback UI itself is not drawn).

**8.12.9 Backend integration** — `GET/PATCH /me`, `GET/PATCH /me/settings`; email jobs for processing/weekly summary.

**8.12.10 Responsive** — **Not verified in Figma.**

**8.12.11 Accessibility** — Toggle rows are one label + description per switch; chips = radio group; Save button disabled until dirty **[Recommendation]**.

**8.12.12 Acceptance criteria**
- Four cards at 760 wide, in the listed order.
- Toggle values On/On/On, Off/On as listed.
- Theme chip "Light" selected.

---

### 8.13 Data & Privacy

**8.13.1 Purpose** — Explain how data is used and let the student delete or export it.

**8.13.2 Figma frames** — `10 Data & privacy` (21:1493) 1440×1211. No mobile.

**8.13.3 Entry points** — Sidebar/Rail "Data & privacy"; links from auth legal line (not drawn).

**8.13.4 Visual structure** — Sidebar (Data & privacy selected) + Main: header H1 "Data & privacy" / "You decide what IntelliStudy keeps. Your files are private to your account."; **Content** 760 (gap 24):
- Notice (Info): "Your files are private and isolated" / "Only your account can read your uploads. Summaries, chat answers and quizzes are built only from your own files and never from other students’ files."
- **How your data is used** card: three principle rows (icon 20 + title + text): `icon/lock` "Stored privately" / "Each student’s files live in a separate, access-controlled space." · `icon/search` "Answers cite your files" / "The chatbot answers only from your materials and shows the page it used." · `icon/shield` "You stay in control" / "Delete a file and its summaries, quizzes and chat citations are removed with it."
- **Your data** card: rows (text + Secondary Button): "Uploaded files" / "12 files · 84 MB across 3 courses" → "Delete files"; "Summaries and quizzes" / "46 summaries · 14 quiz attempts" → "Delete"; "Chat history" / "31 conversations" → "Clear history"; "Mastery and analytics" / "Scores per topic and exam history" → "Reset".
- **Export and delete** card: Secondary "Export all my data" (179×44) + **Danger** "Delete my account and data" (244×44); note "Deleting is permanent and removes every file, summary, quiz and score within 30 days." — **"30 days" is an unconfirmed placeholder.**

**8.13.5 Actions** — Delete files / Delete / Clear history / Reset (each needs confirmation — the Modal component, Destructive, exists but is **not placed**); Export all my data; Delete account.

**8.13.6 UI states** — Default only. **Not drawn:** confirmation dialogs, in-progress export, export ready, deletion scheduled, errors, zero-data states.

**8.13.7 Data requirements** — counts/sizes per data type (files, MB, courses, summaries, quiz attempts, conversations), export job status, deletion retention period (**Open**).

**8.13.8 Frontend behaviour** — Each destructive button opens a confirmation Modal (copy for these dialogs is **not designed**; only "Delete this course?" sample exists); final account deletion should require re-authentication **[Recommendation / Open]**.

**8.13.9 Backend integration** — `GET /me/data-summary`, `DELETE /materials`, `DELETE /chats`, `POST /me/analytics/reset`, `POST /me/export`, `DELETE /me`. Cascade rule per copy: deleting a file removes its summaries, quizzes and chat citations.

**8.13.10 Responsive** — **Not verified in Figma.**

**8.13.11 Accessibility** — Destructive actions named specifically ("Delete uploaded files"); Danger button has text + colour; confirmation dialog focus trap.

**8.13.12 Acceptance criteria**
- Four cards + Notice at 760 wide in listed order.
- Only the last button is Danger variant.
- Copy matches exactly, including "within 30 days" flagged as placeholder in code comments/spec.

---
## 9. Prototype and Navigation Flow

### 9.1 Confirmed prototype wiring (the only interactions in the file)
Flow starting point: **`P1 Upload`** (22:1972), flow name "Upload → Summary → Chat → Quiz → Analytics". All 7 reactions are: trigger **On click**, action **Navigate to**, animation **Smart animate**, easing **Ease out**, duration **0.25 s**. **[Confirmed]**

| # | From frame | Trigger | UI element | To frame | Transition |
|---|---|---|---|---|---|
| 1 | P1 Upload | On click | `FileUploadRow / Indexed` (instance, "Lecture 4 — Aspect-Oriented Programming.pdf") | P2 Summary | Smart animate, ease out, 0.25 s |
| 2 | P2 Summary | On click | `Tab / Chat` (instance) | P3 Chat — answered | Smart animate, ease out, 0.25 s |
| 3 | P3 Chat — answered | On click | first `CitationBadge` (instance) | P4 Chat — source open | Smart animate, ease out, 0.25 s |
| 4 | P4 Chat — source open | On click | `Tab / Quiz` (instance) | P5 Quiz — question | Smart animate, ease out, 0.25 s |
| 5 | P4 Chat — source open | On click | `IconButton` (source panel close) | P3 Chat — answered | Smart animate, ease out, 0.25 s |
| 6 | P5 Quiz — question | On click | `Button / Check answer` (instance) | P6 Quiz — review | Smart animate, ease out, 0.25 s |
| 7 | P6 Quiz — review | On click | `RailItem / Analytics` (frame) | P7 Analytics | Smart animate, ease out, 0.25 s |

Nothing is wired from P7. Nothing is wired on any Desktop or Mobile frame. No hover, press, scroll, overlay, modal, or delay interactions exist. **[Confirmed]**

Prototype device/viewport and background settings: **Not verified in Figma.**

### 9.2 Intended screen-to-screen map (implied by the UI; NOT wired in Figma)
Use these as route intent only. Each row is **[Recommendation]** derived from visible controls:

| From | UI element | To |
|---|---|---|
| Sign in / Sign up | Tab "Create account" / "Sign in" | the other auth frame |
| Sign in | Primary "Sign in" | Dashboard |
| Sign up | Primary "Create account" | Dashboard (or onboarding — **Open**) |
| Dashboard | Primary "Upload files" | Upload flow |
| Dashboard | Course Card | Course workspace |
| Dashboard | "Start 10-question quiz", "Practise" | Quiz question |
| Dashboard | "Why this?" | (explanation not drawn) |
| Dashboard | "New course" | (creation flow not drawn) |
| Sidebar/Rail | any NavItem | Dashboard / Courses (course list, not drawn) / Analytics / Exam builder / Settings / Data & privacy |
| Course workspace | "Add files" / mobile "Add" | Upload flow |
| Course workspace | "Ask your materials", "Ask about this file", tab Chat | Chat |
| Course workspace | "Open summary", tab Summary | Summary |
| Course workspace | "Generate quiz", tab Quiz | Quiz |
| Course workspace | tab Analytics | Analytics (course-scoped) |
| Upload flow | Indexed row / "Open" | Summary |
| Summary | citation badge | source panel (desktop) / bottom sheet (mobile) |
| Summary / Chat source | "Open in file", "Open page n", "Open page 3 in file" | document viewer (**not drawn**) |
| Chat | citation badge / source chip | Chat source open |
| Chat | "New conversation" | empty Chat (**not drawn**) |
| Quiz | "Check answer" | per-question feedback (**not drawn**) / Review |
| Quiz | "Exit quiz" | back to the course (confirmation **not drawn**) |
| Quiz Review | "Retry wrong answers" | Quiz |
| Analytics | "Build personalised exam", "Build exam" | Exam builder |
| Analytics | "Open summary" | Summary |
| Analytics | "Start quiz" | Quiz |
| Exam builder | "Start exam" | exam-taking (**not drawn**) |
| Exam results | "Retake missed questions" | exam / quiz of missed items |
| Exam results | "Review answers" | answer review (**not drawn**) |
| Settings | "Save changes" | stays; success feedback not drawn |
| Data & privacy | destructive buttons | confirmation Modal (**not drawn**) |

### 9.3 Notes on transitions
- Smart animate between differing frames (e.g. P3 → P4 where the chat column narrows from 1368 to 988 and the source panel appears) implies a panel slide/width transition of ~250 ms ease-out. **[Recommendation]** Respect `prefers-reduced-motion`.
- No animation is specified for tab changes, accordion expand/collapse, toggle thumb movement, progress, or the loading dots. → **Not verified in Figma.**

---

## 10. Content and Copy Inventory

Rule: copy in Figma is the **source for UI strings**. Strings that are sample data (names, counts, dates, file names) are marked *(sample)* and must come from data in production. Full per-screen copy is in section 8; this section groups strings by type. Typographic detail: Figma uses curly apostrophes (’) and curly quotes (“ ”), the middle dot (·) as a separator, the em dash (—) in file names and the ellipsis character (…). Keep them. **[Confirmed]**

### 10.1 Navigation and shell
Dashboard · Courses · Analytics · Personalised exam · Settings · Data & privacy · Home (mobile) · IntelliStudy (wordmark) · "Layla Hassan" *(sample)* · "Computer Science · Year 3" *(sample)* · "LH" *(sample initials)* · Tabs: Overview · Summary · Chat · Quiz · Analytics · Auth tabs: Sign in · Create account · Breadcrumbs "Courses  /  Aspect-Oriented Programming" (two spaces around the slash).

### 10.2 Button and link labels (complete list)
Sign in · Create account · Forgot your password? · Upload files · Start 10-question quiz · Why this? · New course · Practise · Add files · Add · Ask your materials · Ask about this file · Open summary · Generate quiz · Choose files · Cancel · Open · Remove · Retry · Regenerate · Open in file · Previous · Open page 12 · Open page 3 in file · New conversation · Send · Answering… (loading label) · Exit quiz · Skip question · Check answer · Retry wrong answers · Build personalised exam · Build exam · Start quiz · Start exam · Save settings for later · Download summary · Retake missed questions · Review answers · Save changes · Delete files · Delete · Clear history · Reset · Export all my data · Delete my account and data · (Modal sample) Cancel / Delete course.

### 10.3 Status, tag and level words
Indexed · Extracting · Uploading 62% · Failed · Not supported · Empty · OCR · Weak · Weak topic · Learning · Proficient · Mastered · Mastered · 94% · Proficient · 78% · Not started · Correct · Incorrect · Partly correct · Low confidence · Working · Answered from n files · Partly answered from 1 file · Not found in your materials.

### 10.4 Helper text, placeholders, field labels
- Labels: University email · Password · Full name · Programme · Course · Topics · Number of questions · Question types.
- Placeholders: "name@university.edu" · "Your password" · "At least 12 characters" · "Ask a question about your materials…" · "Searching your materials…" (loading).
- Helpers: "Use the address your university gave you" · "Use 12 or more characters. A phrase works well." · "Questions come only from this course’s indexed files." · "Weak topics are pre-selected and weighted higher."
- Error: "Enter an address ending in .edu".
- Draft/counter: "Saved as a draft" · "196 / 600".

### 10.5 Trust, honesty and privacy copy
Brand panel (headline, subcopy, three trust points) — 8.1.4 · Composer disclaimer: "Answers come only from your uploaded files. Check the cited page before relying on them." · Upload privacy: "Files are processed in your private account space and are never shared with other students." · Refused/Partial/Low-confidence blocks — 8.6.4 · Source panel labels: "EXACT PASSAGE", "SURROUNDING TEXT · PAGE 12", "ALL SOURCES IN THIS ANSWER", "ALL SOURCES IN THIS SUMMARY" · "TRY ASKING" · "SOURCES" · "WHY" · Data & privacy copy — 8.13.4 · Auth legal line — 8.1.4.

### 10.6 Empty, loading, error copy
Drawn: Searching 12 files… / Working · Reading pages… · Extracting text and structure… · "Scanned PDF detected…" (OCR) · EmptyState (component): "No materials yet" + "Upload lecture slides, notes or papers (PDF, Word, PowerPoint). Summaries, chat and quizzes will be built only from these files." · Toast sample "File added." · Modal sample "Delete this course?".
**Not drawn / copy does not exist:** generic error pages, network errors, 404, session expiry, empty dashboard, empty analytics, empty chat, empty quiz list, export-ready message, form-saved message, unsaved-changes prompt.

### 10.7 Numbers and rules shown in copy that need confirmation (placeholders)
| String | Where | Status |
|---|---|---|
| "Up to 100 MB per file" | Upload dropzone | **Placeholder — Open** |
| ".edu" email rule | Sign up | **Open** |
| "At least 12 characters" | Sign up | **Open** (policy) |
| "within 30 days" | Data & privacy | **Unconfirmed placeholder** |
| "45 minutes" timer | Exam builder | **Placeholder — Open** |
| "About 60% of questions come from topics under 50% mastery" | Exam builder | **Placeholder — Open** |
| "70% proficiency threshold" | Analytics footnote | **Open** (mastery thresholds) |
| "6:00 PM" reminder | Settings | **Placeholder — Open** |
| "Only for files larger than 20 MB" | Settings | **Placeholder — Open** |
| "600" character limit | Short answer counter | **Open** |
| "Sent on Sundays" | Settings | **Placeholder — Open** |
| "Never more than one per day" | Settings | product promise — **Open** |
| "last 30 days" (quizzes taken) | Analytics | **Open** |
| Reset (mastery), Export, Delete semantics | Data & privacy | **Open** |

### 10.8 Sample data strings (do not hard-code)
Course names (Aspect-Oriented Programming, Queueing Theory, Operating Systems), file names, topic names, mastery numbers, dates (Sep 14 … Oct 21), counts ("12 files", "7 files", "9 indexed files", "6 files"), user name, quiz/question text, passages and page numbers. They are consistent only within a frame; see inconsistencies in section 16.

---

## 11. Icon Inventory

All icons are components named `icon/<name>`, 24×24 grid, **2 px stroke**, no fill (outline style), placed at 16, 18, 20, 24 or 28 px; colour is set by the parent's token (`text/secondary`, `accent/fg`, `on-accent`, `success/fg`, etc.). Counts are instances across the Screens page (including Prototype copies). **[Confirmed]**

| Icon | Instances | Where it is used (confirmed by inspecting each instance's parent) |
|---|---|---|
| icon/book | 75 | Wordmark mark (on-accent, 18); NavItem/RailItem “Courses”; Auth trust point 1 |
| icon/home | 28 | NavItem/RailItem “Dashboard”; mobile Tab “Home” |
| icon/chart | 28 | NavItem/RailItem “Analytics”; mobile Tab “Analytics” |
| icon/target | 31 | NavItem/RailItem “Personalised exam”; Dashboard eyebrow; Analytics action 3 |
| icon/sliders | 28 | NavItem/RailItem “Settings”; mobile Tab “Settings” |
| icon/shield | 26 | NavItem/RailItem “Data & privacy”; privacy principle “You stay in control” |
| icon/file | 22 | File items (workspace, mobile); Auth trust point 2; icon tile of Extracting row (assumed — only Uploading, OCR, Indexed, Unsupported, Empty tiles were read) |
| icon/lock | 5 | Auth trust point 3; Upload privacy note; privacy principle “Stored privately” |
| icon/check | 22 | Selected Chip (16); streak “studied” dots; Button icons on “Check answer” and “Save changes” |
| icon/checkCircle | 4 | Indexed row icon tile; AnswerOption **Correct** |
| icon/x2 | 2 | AnswerOption **Incorrect** |
| icon/x | 10 | IconButton close (source panel, mobile sheet; also default Toast/Modal close); Button icon on “Exit quiz” |
| icon/alert | 7 | Input **Error** (trailing 20 px in field + leading 16 px in helper); icon tiles of **Unsupported** and **Empty** rows; Notice in **Low confidence** |
| icon/info | 6 | Notice (Info tone) leading icon (workspace, Partial message, Exam preview/results, Privacy, mobile) |
| icon/scan | 2 | OCR row icon tile |
| icon/upload | 10 | Buttons “Upload files”, “Add files”, “Choose files”, mobile “Add”; dropzone bubble (24); Uploading row tile; Dashboard activity “Uploaded 4 files” |
| icon/plus | 9 | Buttons “New course” (Dashboard) and “New conversation” (Chat) |
| icon/retry | 5 | Buttons “Regenerate”, “Retry wrong answers”, “Retake missed questions” |
| icon/external | 15 | “Open in file” inside every SourceCard; Buttons “Open” (Indexed row), “Open page 12”, “Open page 3 in file”, “Download summary”, “Export all my data” |
| icon/trash | 1 | Danger Button “Delete my account and data” |
| icon/send | 8 | Composer Send button |
| icon/loader | 2 | Chat Loading status row; Composer Loading button spinner |
| icon/search | 2 | Refused message title row; privacy principle “Answers cite your files” |
| icon/chevronRight | 17 | Collapsed accordion toggles; collapsed quiz-review rows; Button “Previous” (right-pointing — see defect 24) |
| icon/chevronDown | 8 | Expanded accordion toggles; mobile Back (rotated −90°) |
| icon/layers | 7 | Dashboard activity “Summary generated”; Analytics action “Re-read the Weaving summary” |
| icon/quiz | 6 | Dashboard activity “Quiz · …”; Analytics action “Take a 10-question quiz” |
| icon/message | 3 | Dashboard activity “Asked 3 questions” |
| icon/flame | 1 | Dashboard streak |
| icon/user | 0 | Defined; **not used** on any screen |

**Buttons that carry an icon (Show icon = true):** Upload files · Add files · Choose files · Add (mobile) · New course (plus) · New conversation (plus) · Regenerate (retry) · Exit quiz (x) · Check answer (check) · Retry wrong answers (retry) · Retake missed questions (retry) · Save changes (check) · Download summary (external) · Export all my data (external) · Open page 12 / Open page 3 in file / Open (external) · Delete my account and data (trash) · Previous (chevronRight) · Send (send). All other buttons are text only. Icon in Button = 16 px, gap 8 before the label. **[Confirmed for the listed instances]**

Glyph shapes are **not** described in text: export the 30 `icon/*` components from Figma as SVG (24×24 viewBox, `stroke="currentColor"`) and treat them as the source. Stroke cap/join style and whether strokes scale with instance size (16/18/20/24/28) were **not read** (see section 16.3).

---

## 12. Frontend Architecture Blueprint
Everything in this section is **[Recommendation]**; Figma has no code constraints.

### 12.1 Stack
React + TypeScript, Vite (or equivalent), React Router, Tailwind CSS with design tokens as CSS variables, TanStack Query for server state, a small client-state store only where needed (theme, open source panel), React Hook Form + Zod for forms, a typed API client generated from FastAPI's OpenAPI schema, Vitest + Testing Library + Playwright, axe for accessibility checks.

### 12.2 Tokens → Tailwind
- Emit the **Primitives** only in a generated tokens file (never used directly in components, per the Foundations note).
- Emit **semantic tokens** as CSS custom properties on `:root` (Light) and `[data-theme="dark"]` (Dark): `--color-bg-canvas`, `--color-bg-surface`, `--color-accent-default`, etc. Tailwind theme colours reference these variables (e.g. `bg-canvas`, `bg-surface`, `text-primary`, `border-default`, `accent`, `accent-subtle`).
- Spacing scale = the 12 spacing values; radius scale sm/md/lg/xl/full; font sizes + line heights from the Type variables; add the 12 text styles as utility classes (`text-display`, `text-h1`, … `text-caption-strong`) that set size, line-height, weight and letter-spacing.
- Shadows `shadow-sm/md/lg` from the three effect styles.
- Control heights `h-control-md` (44), `h-control-lg` (48), min touch `min-h-touch`/`min-w-touch` (44).

### 12.3 Proposed folder structure
```
src/
  app/            routes, providers, layout shells (SidebarShell, RailShell, MobileShell, AuthShell)
  design-system/  tokens, primitives (Button, Input, Tab, Chip, Tag, …), icons
  features/
    auth/ dashboard/ courses/ materials-upload/ summary/ chat/
    quiz/ analytics/ exam/ settings/ privacy/
  lib/            api client, query keys, formatters (relative time, bytes)
  types/          shared models (section 13)
```
Each feature owns its pages, components, hooks, and API calls.

### 12.4 Routes (derived from the frame list; paths illustrative)
`/signin` · `/signup` · `/` (Dashboard) · `/courses` (list — **no frame**) · `/courses/:id` (Overview) · `/courses/:id/upload` · `/courses/:id/materials/:materialId/summary` · `/courses/:id/chat` · `/courses/:id/quiz` · `/quizzes/:attemptId` (question) · `/quizzes/:attemptId/review` · `/analytics` · `/exam/new` · `/exams/:id/results` · `/settings` · `/privacy`.

### 12.5 Component mapping (Figma → React)
One React component per Figma component set (22) with a `variant`/`tone`/`state` prop mirroring the Figma property names. Interaction states (Hover, Focus, Disabled) come from CSS pseudo-classes / ARIA, **not** from props; `Loading`, `Selected`, `Error`, `Correct`, `Incorrect` are props. Compose, don't clone: `Rail` and `Sidebar` share a `NavItem` model; `AuthShell` hosts both auth pages.

### 12.6 State and data
- Server state in TanStack Query; long-running file processing via polling or SSE (**Open**).
- URL holds: active course, active tab, selected file, open source (`?source=2`), analytics course filter.
- Local UI state: expanded summary sections, selected quiz option, short-answer draft (persist draft per the "Saved as a draft" copy).
- Theme: `data-theme` on `<html>`, persisted in settings, "Match system" via media query.

### 12.7 Backend (FastAPI) boundary
Resource groups matching the modules: auth, users/settings, courses, materials (upload, status, retry, delete), summaries (+citations), chat (structured answer with state), quizzes/attempts/results, analytics, exams, privacy (data summary, export, delete). Response shapes follow section 13. The chat endpoint returns a **state enum** and structured citations; the UI never derives refusal/partial/low-confidence from free text.

### 12.8 Cross-cutting rules
- All strings in one i18n-ready catalogue seeded from section 10 (English only in Figma).
- Dates/relative times via a formatter ("2 hours ago", "Yesterday", "Sep 14").
- Error boundary and toast host are not designed; build with the Toast/Notice components when needed and log as open items.
- Respect `prefers-reduced-motion` and keep focus management for the source panel, sheets and modals.

---
## 13. Shared Data Models

Derived from what the UI displays. **[Recommendation]** — Figma contains no schema. Types are TypeScript-style names for readability only; `?` = optional. Field names are suggestions; keep semantics.

### 13.1 User
`id` · `name` ("Layla Hassan") · `email` (university, `.edu` rule — Open) · `programme` ("Computer Science · Year 3") · `initials` (derived) · `settings: UserSettings` (see 8.12.7).

### 13.2 Course
`id` · `title` · `description` · `fileCount` · `indexedCount` · `processingCount` · `failedCount` · `masteryPct` · `masteryLevel` · `topicsFound` · `statusLabel` ("All indexed" / "1 processing" — derive from counts) · `examDate?` (for "3 days to your … midterm" — source Open).

### 13.3 CourseMaterial
`id` · `courseId` · `fileName` · `fileType` (pdf|docx|pptx) · `sizeBytes` · `pageCount?` (pages or slides) · `status: ProcessingStatus` · `progressPct?` · `detail?` (status sentence) · `indexedAt?` · `topicIds[]` / `topicCount` · `ocrApplied: boolean`.

### 13.4 ProcessingStatus
Enum: `uploading` · `extracting` · `ocr` · `indexed` · `failed` · `unsupported` · `empty`. Display labels: Uploading, Extracting, OCR, Indexed, Failed, Not supported, Empty. Tone mapping: indexed→Success; uploading/extracting/ocr→Accent; failed/unsupported/empty→Danger.

### 13.5 UploadItem
Client-side wrapper: `clientId` · `file: File` · `status: ProcessingStatus` · `progressPct` · `bytesUploaded` · `totalBytes` · `message?` · `materialId?` (after creation) · `canCancel` · `canRemove` · `canOpen`.

### 13.6 Summary
`id` · `materialId` · `title` · `generatedAt` · `pageCount` · `sections: SummarySection[]` · `sources: Citation[]` (all sources list).

### 13.7 SummarySection
`id` · `title` · `kind` (`statements` | `terms`) · `statements[]: { text, citationIndexes[] }` · `sourceCount` · `termCount?` (for "Key terms", "6 terms") · `defaultExpanded` (sections 1–2 expanded in Figma).

### 13.8 Citation
`index` (1-based, shown as `[n]`) · `materialId` · `fileName` · `locatorType` (page | slide | section) · `locatorLabel` ("p. 12", "Slide 9", "Pointcuts") · `title?` ("3.1 Join points") · `shortLabel` ("Lecture 4 · p. 12") · `passageId`.

### 13.9 SourcePassage
`id` · `materialId` · `locatorLabel` · `sectionTitle?` · `passage` (exact text) · `surroundingText?` · `pageNumber?` · `prevPassageId?` / `nextPassageId?` (Previous navigation; Next not drawn).

### 13.10 ChatConversation
`id` · `courseId` · `materialId?` (scoped chat) · `title?` · `messages[]` · `scopeFileCount` ("Searching all 12 files").

### 13.11 ChatMessage
`id` · `role` (user|assistant) · `state?: ChatAnswerState` · `text?` (user) · `blocks[]` (assistant paragraphs, each `{ text, citationIndexes[] }`) · `filesUsed?` · `filesSearched?` · `notice?` `{ title, body }` (partial / low-confidence block) · `refusal?` `{ title, body, closestSourceCitation }` · `suggestions[]` · `citations[]` · `createdAt`.

### 13.12 ChatAnswerState
Enum: `answered` · `refused` · `partial` · `loading` · `low_confidence`. Captions: "Answered from n files" · "Not found in your materials" · "Partly answered from n file(s)" · "Working" · "Answered from n files" (+ Low confidence block).

### 13.13 Quiz
`id` · `courseId` · `title` · `topicLabel` ("Advice and weaving") · `questionCount` · `questions: Question[]` · `createdAt`.

### 13.14 Question
`id` · `type` (`multiple_choice` | `short_answer`) · `prompt` · `hint?` ("Choose one answer." / short-answer guidance) · `options[]: { id, text }` · `topicId` · `maxLength?` (600 — Open) · `explanation?` · `citation?`.

### 13.15 QuizAttempt
`id` · `quizId` · `startedAt` · `finishedAt?` · `currentIndex` · `answers[]: { questionId, selectedOptionId? | text?, skipped, draftSavedAt? }` · `scoreCorrect` · `scoreTotal` · `scorePct` · `level` · `durationMinutes?` · `kind` (quiz | personalised_exam).

### 13.16 QuestionResult
`questionId` · `status` (`correct` | `incorrect` | `partial`) · `selectedOptionId? | answerText?` · `correctOptionId? | modelAnswer?` · `explanation` · `citation: Citation` · `sourcePassage?`. Labels: Correct / Incorrect / Partly correct.

### 13.17 TopicMastery
`topicId` · `courseId` · `title` · `masteryPct?` (null for Not started) · `level` (`not_started` | `weak` | `learning` | `proficient` | `mastered`) · `questionsMissed?` · `reason?` ("3 of 4 questions missed") · `delta?` (e.g. 32→40). Level thresholds: **Open** (design samples imply ≥ 90 / 70–89 / 50–69 / 1–49 / none).

### 13.18 AnalyticsSummary
`courseId | "all"` · `overallMasteryPct` · `overallLevel` · `quizzesTaken` (+ window "last 30 days") · `averageScorePct` · `averageDelta` (+8 since September) · `streak {current, best}` · `topics: TopicMastery[]` · `scoreHistory: [{ date, label ("Sep 14"), scorePct }]` (8 entries) · `weakTopics[]` · `recommendations: Recommendation[]`.

### 13.19 Recommendation
`id` · `kind` (summary | quiz | exam | practise) · `icon` (layers | quiz | target) · `title` · `body` · `ctaLabel` · `target` (route + params) · `basedOn?` ("Based on Quiz 3 and Quiz 4 · …") · `courseId`.

### 13.20 PersonalizedExam
`id?` · `courseId` · `topicIds[]` · `questionCount` (10|20|30) · `questionTypes[]` · `timed` · `timeLimitMinutes?` (45 — Open) · `focusWeakTopics` · `weakShareTarget?` (60% — Open) · `indexedFileCount` · `status` · `result?: { scoreCorrect, scoreTotal, durationMinutes, deltaVsLast, byTopic[{topicId, correct, total, pct, level}], masteryUpdates[] }`.

### 13.21 Other display models implied by frames (not in the required list)
`ActivityItem { id, kind (quiz|summary|chat|upload), text, occurredAt }` · `StreakWeek { days[7]: { label, studied } }` · `SettingsToggle`s · `DataSummary { fileCount, totalMB, courseCount, summaryCount, quizAttemptCount, conversationCount }`.

---

## 14. Implementation Rules for the Coding Agent

1. **Do not redesign.** Reproduce the frames. If something looks wrong, implement as drawn, log it in section 16, and ask.
2. **Source priority:** frame > component/variable values > this file > product requirements > assumptions. Never silently override a frame with this document.
3. **Tokens only.** No raw hex, px colours or one-off shadows in components. Every fill/stroke/text colour = a semantic token. Primitives are never referenced in components.
4. **Both themes.** Build semantic tokens for Light and Dark, even though only Light is drawn. Do not invent dark-mode details beyond the token values; mark visual QA for dark as Not verified.
5. **One component per Figma component set,** with Figma property names (`variant`, `state`, `tone`, `selected`, `size`, `type`, `level`, `status`). Do not rebuild composed UI as a one-off if a component exists.
6. **Interactive states** (Hover, Focus, Disabled) exist in the component library: implement them with CSS pseudo-classes + ARIA so they match the library variants. Do not add states Figma does not define.
7. **Copy is data.** Use the exact strings from section 8/10 (including ’ “ ” — …). Sample data comes from the API; placeholders flagged in 10.7 must not ship as product claims until confirmed.
8. **Honest states are mandatory.** Chat must render all five answer states from a backend state enum. Never show an answer without citations; never fabricate a source.
9. **Citations:** every `[n]` is a button that opens its source (panel on desktop, sheet on mobile). Source list and statements share the same index.
10. **Accessibility is part of done:** WCAG 2.2 AA; targets ≥ 44×44 (use the Touch citation badge where the Inline badge is too small); visible 2 px focus ring on everything focusable; status never colour-only; keyboard operability; focus management for panels, sheets, and modals.
11. **Do not invent features** beyond the module list (no sharing, flashcards, social, extra file types, calendar, etc.).
12. **Do not invent limits.** Don't hard-code max file size, character limits, timer length, thresholds, retention periods. Put them in configuration and resolve via Open Questions.
13. **Do not copy known Figma defects:** the 434-px mobile chat body overflow; fixed-width progress fills; static mastery-ring sweeps; the NavItem selected size change should be confirmed first.
14. **Layout fidelity:** use the column widths in 4.4; fixed desktop widths with `max-width`; do not stretch content to fill ultra-wide screens.
15. **Missing designs:** where a state or screen is not drawn (empty, loading, error, mobile for 8 modules, tablet, dark screens, modals for destructive actions), implement a minimal version using existing components and tokens only, and register it in the Open Questions list for design sign-off.
16. **No application code was written in this document;** the architecture in section 12 is guidance, not a constraint.
17. **Ask rather than guess** when a decision changes behaviour (grading, thresholds, retention, scope of "Reset").

---

## 15. Visual QA Checklist

Use against the frame in Figma at 1440 (desktop) and 390 (mobile).

**Global**
- [ ] Page background = `bg/canvas`; cards = `bg/surface` with 1 px `border/default`.
- [ ] Text styles match section 4.2 (size, line-height, weight, letter-spacing).
- [ ] Radii: tag 4, control 8, row/notice/answer 12, card/panel 16, chip/toggle/ring 999.
- [ ] Focus ring 2 px `color/focus/ring` on every focusable element.
- [ ] All interactive controls ≥ 44 px.
- [ ] Main content padding 40/48/48/48 and 32 gaps on Sidebar screens.
- [ ] Sidebar 264 / Rail 72 and correct selected item.
- [ ] Light/Dark tokens swap without hard-coded colours.

**Components**
- [ ] Button heights 44; paddings 0/16; variants and states per 7.1.
- [ ] Tabs: Selected has 2 px accent bottom border and `accent/fg` label.
- [ ] Chip: 36 px pill inside 44 px hit box; Selected shows check.
- [ ] Tag: 24 px high, caption-strong, tone colours.
- [ ] Citation badge Inline 24×22 / Active solid accent.
- [ ] MasteryRing arc computed from data; colour by level; label visible.
- [ ] FileUploadRow border colours: danger for Failed/Unsupported/Empty.
- [ ] AnswerOption Correct/Incorrect show words, not colour only.
- [ ] Toggle 44×24 track, 20 thumb.

**Per module (compare to frame)**
- [ ] Auth: 640/800 split, card 440, exact copy, Error input.
- [ ] Dashboard: 716+340 row, 3 cards 344×162, weak rows with rings, 4 activity rows, 7 streak dots.
- [ ] Workspace: 300 / 728 / 340; 7 file items; stats; notice; topic list; details panel.
- [ ] Upload: dropzone 2 px accent border; six row statuses; privacy note.
- [ ] Summary: five sections (2 open); source panel 380 with 5 sources.
- [ ] Chat: five states, exact copy, composer + disclaimer; source-open layout 988 + 380.
- [ ] Quiz: bar 77 + progress 8; column 720; 4 options; short-answer field with counter.
- [ ] Review: result card, expanded Q6, three collapsed rows.
- [ ] Analytics: 4 stats; 6 topic rows; 8 score bars; weak topics; 3 recommendations.
- [ ] Exam builder/results: settings 676 + preview 380; results rows add to 15/20.
- [ ] Settings/Privacy: 760 column; toggles/chips; destructive Danger button only at the end.
- [ ] Mobile M3/M5/M6/M8: app bar, tab bar, sheet 390×416 with 45% scrim, no horizontal overflow.

**Prototype parity**
- [ ] The 7 transitions exist as routes/interactions (ease-out ~250 ms where animation is used).

---

## 16. Confirmed / Not Verified / Open Questions

### 16.1 Confirmed in Figma (re-inspected 2026-11-10)
- File structure, page/section/frame names and sizes (section 3).
- All 5 variable collections and their values; 12 text styles; 3 effect styles (section 4).
- All 22 component sets with their variant properties, sizes, fills, strokes, radii, paddings and text styles (section 7); 30 icon components with usage counts.
- Full text content of all 20 desktop frames and 4 mobile frames (section 8).
- The 7 prototype reactions and flow start (section 9).
- Component usage on screens (Modal, Toast, EmptyState, TableRow unused).
- Chat answer states (Answered, Answered–source open, Refused, Partial, Loading, Low confidence); Upload row statuses (6 used, 7 exist).
- Mobile frames exist only for Course workspace, Summary (with source sheet), Chat (answered), Analytics.

### 16.2 Inconsistencies found in the Figma file (implement as drawn unless told otherwise; flag them)
1. NavItem **Selected** uses `text/body-strong` (16/24) while other states use `text/label` (14/20).
2. SourceCard passage text uses **raw 14 px** instead of a text style.
3. MasteryRing arcs are sample sweeps; only the % text is edited per instance.
4. ProgressBar fills are fixed-width variants (25/60/100 only).
5. Quiz **Short answer** shows "Question 7 of 10" but its progress bar is Value=60 (same as question 6); progress at question 6 of 10 = 60% implies question 7 = 70%.
6. Aspect-Oriented Programming mastery is **74%** (Dashboard card, Workspace ring, mobile M3) but **72%** on Analytics (desktop and mobile).
7. File counts disagree: course card "12 files"; Workspace "7 files", "4 of 7"; Chat scope "12 files"; Exam builder "9 indexed files"; Upload "6 files"; Data & privacy "12 files … across 3 courses" while the Dashboard's three courses total 36 files.
8. Streak disagrees: Dashboard "6-day streak, best 9"; Analytics "9 days, best: 12 days".
9. Mobile **M6 Chat** body frame is **434 px wide** in a 390 px frame (overflow).
10. Mobile app-bar height 61 (M3, M5, M6) vs 41 (M8, no Back).
11. Mobile M3 omits Lecture 1 and Lecture 2 from the file list (desktop shows 7, mobile 5).
12. Mobile section name "Weaving" vs desktop "Weaving: compile-time vs run-time".
13. In "Chat / Answered — source open" the panel header and list badge [1] are **Active**, but the badges inside the answer message are all **Default** (the selected citation is not highlighted in the message).
14. Source panel has a "Previous" button but **no "Next"**.
15. Prototype frames are **copies**; their rail items are plain frames and may differ from the Desktop frames. P1 uses `FileUploadRow` instance; P6's Analytics link is on a frame, not an instance.
16. Chat message "Answered from 2 files" caption appears on Low confidence too (the state differs only by its warning block).
17. Mobile Back uses `icon/chevronDown` rotated −90° (resolved: points left).
18. Exam/Results, Settings, etc. use the **Sidebar**, while Workspace/Summary/Chat/Quiz use the **Rail**; the reason is not documented.
19. Two different shells for the same destinations (Sidebar vs Rail) are separate components in Figma (Rail items are not NavItem instances).
20. Tag in the Dashboard weak-topic row says "Weak topic" while Analytics and Workspace say "Weak".
21. Analytics "Not started" row shows a 4 px bar fill and "—" as the percentage.
22. Exam builder shows "4 selected" topics: consistent with 4 selected chips.
23. Dashboard Card default component width is 320, instances are 344.
24. The Source panel “Previous” button carries a **right-pointing** chevron (`icon/chevronRight`).
25. The Chat frames render the course title in `text/h2` while other course-level pages (Workspace, Summary) use `text/h1`; mobile Summary uses `text/h2`.
26. The component library’s Indexed FileUploadRow reads “48 slides · indexed 2 min ago” while the Upload screen reads “48 pages · indexed just now” (both sample copy).
27. Dashboard “Weakest topics” lists a 56% “Learning” topic although the Exam builder copy defines weak as “under 50% mastery”.
28. Workspace shows 5 topics with a 4-of-7 file index; the Topics card says “18 topics across 4 indexed files” while the file panel says “Topics found 6” for the selected file (sample data, not contradictory by itself).

### 16.3 Not verified in Figma (after the audit pass)
- Tablet layout; dark-theme screens; mobile frames for Auth, Dashboard, Upload, Quiz, Review, Exam, Settings, Data & privacy; mobile versions of chat states other than Answered; mobile sizing modes (FIXED/FILL) of any frame.
- Empty, loading, error and offline states for nearly all modules; Modal, Toast, EmptyState and TableRow placement; drag-over state; hover/focus rendering on screens (library variants exist).
- Glyph shapes, stroke caps/joins and stroke scaling of icons; the icon in the Extracting row tile; the Toast/Modal default close glyph name; fills of the Extracting/OCR/Unsupported/Empty icon tiles; whether Extracting shows a ProgressBar.
- Unselected file-item fill/stroke in the workspace list; bar-track corner radius in topic rows; mobile Tab row overflow; prototype device/viewport settings.
- Copy of the Prototype frames compared with their Desktop twins; where `size/control-lg` (48) is applied; behaviour between 391 and 1439 px.
- Everything behavioural (click, hover, keyboard, timing) beyond the 7 prototype reactions.

### 16.4 Open questions (not answered here)

> Revision 2: the full per-issue list (IDs A1–I14, with status) is in **# Developer Assumptions To Eliminate** below. Every 🔴 row there is an open question; every 🟡 row has an adopted default in section 18 or 19 that still needs sign-off.

**Product & policy**
1. Maximum file size ("Up to 100 MB per file" is a placeholder) and page/slide limits?
2. Is sign-up restricted to `.edu` addresses? What about universities with other TLDs?
3. Password policy: is "at least 12 characters" final? Is there SSO?
4. Deletion window: "within 30 days" is an unconfirmed placeholder — what is the real retention policy?
5. What exactly do "Reset" (mastery), "Delete" (summaries and quizzes), and "Export all my data" (format, delivery) do?
6. Mastery level thresholds (≥ 90 / 70–89 / 50–69 / below 50 / none) and the "70% proficiency" line — final values? How is a topic's mastery calculated (recency, weighting)?
7. How are short answers graded and what does "Partly correct" require?
8. Exam defaults: time limit (45 min), weak-topic share (60%), allowed counts (10/20/30), does time scale with question count?
9. Where does "3 days to your Queueing Theory midterm" come from — user-entered exam dates?
10. Streak rules, "best" definition, and which reminder time ("6:00 PM") / email threshold ("20 MB") / weekly day ("Sundays") are configurable vs fixed?
11. Short-answer character limit (600) final?
12. Is chat history per course, per file, or global? Is there a conversation list?
13. What triggers Refused vs Partial vs Low confidence (retrieval score thresholds)? Who tunes them?
14. What does "Open in file" open (in-app viewer, download)? Does it need to render PPTX slides?
15. What is the Courses list page (no frame)? How are courses created ("New course")?
16. What is the exam-taking screen — reuse Quiz screens? Is there an exam review?

**Design & responsive**
17. Mobile designs for Auth, Dashboard, Upload, Quiz, Review, Exam builder/results, Settings, Data & privacy — and mobile entry points for Personalised exam and Data & privacy (not in the Tab bar).
18. Tablet behaviour (Sidebar vs Rail vs bottom bar) between 391 and 1439 px.
19. When is Rail used vs Sidebar (a rule, or per-screen)?
20. Dark theme: confirm tokens and add dark frames (components bind to tokens already).
21. Missing states: empty course, empty dashboard/analytics/chat, loading skeletons, errors, offline, confirmation dialogs for destructive actions, unsaved changes.
22. NavItem selected typography (body-strong) — intentional?
23. Which citation size (Inline 24×22 vs Touch 44×44) on mobile?
24. Should the source panel offer "Next" as well as "Previous"?
25. Inconsistent sample numbers (mastery 74 vs 72, file counts, streaks) — which are canonical for QA fixtures?

**Technical**
26. Status transport for file processing: polling, SSE or WebSocket?
27. Authentication mechanism (cookie session vs token) and CSRF approach.
28. File storage and virus scanning; OCR engine and languages ("some words may be misread").
29. Real-time vs batch generation of summaries/quizzes; regeneration limits.
30. Analytics scope "All courses" aggregation rules.

---

*End of context.md. Source of truth is the Figma file; this document records what was verified there on 2026-11-10.*


---

# Developer Assumptions To Eliminate

Result of the implementation-readiness audit of `context.md` v1, run against the live Figma file on 2026-11-10.

**How to read this section**
- Every row = one place where a developer would otherwise guess.
- **Status** values:
  - ✅ **Resolved** — fixed inside this document in revision 2 (pointer given). The developer no longer needs to guess.
  - 🟡 **Default** — Figma is silent; a default is adopted in section 18 or 19 so work can proceed. The default is **not a Figma fact** and needs owner sign-off.
  - 🔴 **Owner decision** — cannot be defaulted safely (product, policy or copy). Blocks the listed feature; build behind a flag or stub.
- "Figma-silent" means the file has no frame/variant for it. The audit does not redesign anything.

**Totals:** 167 issues — ✅ 55 resolved in this document · 🟡 74 defaulted (sections 18–19) · 🔴 38 need an owner decision.

---

## A. Missing visual details (pixel-perfect gaps)

| ID | Location | Problem | Why it is ambiguous | Recommended clarification | Status |
|---|---|---|---|---|---|
| A1 | 7.2 Input | Per-state field strokes/fills and Error icons were not recorded | Developer would invent hover/error colours | Recorded: Hover stroke `text/tertiary`, Focus 2 px ring (inside), Error 2 px `danger/solid` + 20 px trailing icon + 16 px helper icon | ✅ |
| A2 | 7.4 Chip, 7.6 CitationBadge | Hover/Focus/Disabled fills missing | No pixel source for interactive states | Recorded in 7.4 and 7.6 | ✅ |
| A3 | 4.5 / 8.4 Upload dropzone | "Dashed or solid?" unknown | Border style changes the look of the hero element | Dashed 8 px dash / 6 px gap, 2 px, inside, `accent/default` | ✅ |
| A4 | 7.21 ChatMessage, 8.6 | v1 said desktop user message is plain text; internals of Refused/Partial/Low-confidence undocumented | Would produce wrong bubble and wrong notes | Corrected: 520 px right-aligned bubble; Refusal note card; Partial = Info Notice; Low confidence = Warning Notice; 28 px avatar | ✅ |
| A5 | 7.16 FileUploadRow | Icon tile, button variants and Failed copy missing | Layout of the most state-heavy component | Recorded: 40×40 tile; Ghost vs Secondary buttons; Failed copy | ✅ |
| A6 | 7.19 AnswerOption | Indicator glyphs unspecified | Radio vs check vs x | Recorded: radio 20 / dot 10; checkCircle / x2 + verdict word | ✅ |
| A7 | 4.2 Typography | Styles listed but not which element uses which | Wrong style choices are the commonest pixel error | New 4.7 text-style usage map | ✅ |
| A8 | 11 Icons | Glyph shapes cannot be described in text; stroke caps/joins and stroke scaling at 16/18/20/28 px unknown; Extracting-row tile icon unknown | Visual mismatch of every icon | Export all 30 `icon/*` components as SVG from Figma and commit them; designer to confirm scaling rule (strokes scale or stay 2 px) and the Extracting tile icon | 🔴 |
| A9 | 11 Icon placements | Placement of alert/retry/checkCircle/trash/plus/x2 was unverified | Wrong icon on wrong control | Rewritten from instance-level inspection incl. "Buttons that carry an icon" list | ✅ |
| A10 | 7.7 ProgressBar / 7.8 MasteryRing | Fill and arc are static samples | Developer may copy fixed widths/sweeps | Specified: fill width = value % of track; ring arc starts −90° (top), sweeps clockwise by value × 360°, inner radius 0.78 | ✅ |
| A11 | 7.8 MasteryRing | Arc end caps (round vs flat) and animation | Ring ends look different | Figma uses flat ellipse arcs (no caps). Build flat; no animation | 🟡 (D-14) |
| A12 | 4.5 Focus ring | "Outside" vs "inside" ring | Box sizes shift by 2 px | Outside for Button/Chip/Card/Tab; **inside** for Input field | ✅ |
| A13 | 4.5 Shadows | Figma shadow styles not given as CSS | Spread/colour errors | `rgb(13 18 23 / α)` values in 4.5 | ✅ |
| A14 | 4.2 Letter-spacing | Stored in percent | CSS needs em | Conversion in 4.2 | ✅ |
| A15 | Summary accordion body | Bullet dot, indent, count placement missing | Visible on every summary | 7.23: 6 px dot (`text/tertiary`), body padding 4/24/24/64, count `caption` right | ✅ |
| A16 | Quiz bar / progress | v1 said bar overlaid; it sits below | 8 px layout shift | 5.4: ProgressBar directly below the 77 px bar (y = 77) | ✅ |
| A17 | Chat message column | v1 said left-aligned; it is centred (x = 304) | Whole chat screen misaligned | 5.4 and 8.6.4 corrected | ✅ |
| A18 | Chat/Analytics/Exam/Settings column alignment | Alignment of fixed columns | Centred vs left | 5.4: Quiz 720 centred, Chat 760 centred, Auth card centred, Settings/Privacy 760 left | ✅ |
| A19 | Bar-track corner radius, unselected file-item fill/stroke | Not read | Small but visible | Default: track radius 999 (matches progress bar); unselected file item has no fill/stroke | 🟡 |
| A20 | Dark theme | No dark frames | Contrast/elevation (shadows on dark) unverified | Build with `Color/Dark` tokens; shadows reused; request dark frames for QA | 🟡 (D-24) |
| A21 | Skeleton / spinner / loading motion | No animation spec | Pulse speed, spinner rotation | Default in D-14 | 🟡 |
| A22 | Raster assets | Do any images/illustrations exist? | Dev may wait for assets | Confirmed: **none**; the only brand mark is the 32 px tile with `icon/book` | ✅ |
| A23 | Fonts | Loading/hosting, optical sizes, tabular figures | Number alignment in charts/tables | Default: self-host Inter 400/500/600/700; no OpenType features beyond defaults (Figma sets none) | 🟡 (D-26) |
| A24 | Mobile text/spacing | Mobile styles not mapped | Mobile H1 is smaller | 4.7: mobile page title `h2`, app bar `title`, tab labels `caption` | ✅ |

## B. Components lacking sizing, spacing, typography or state definitions

| ID | Location | Problem | Why it is ambiguous | Recommended clarification | Status |
|---|---|---|---|---|---|
| B1 | 7.12 TableRow | Defined (880 px) but unused; real tables are bespoke rows | Developer may build a table that no screen uses | Treat as reserved; build Topic result row etc. from 7.23. Do not implement TableRow until a screen needs it | ✅ |
| B2 | 7.13 Toast | No position, stacking, duration, dismissal | Placement affects every confirmation | Default: bottom-centre stack, 5 s auto-dismiss (Danger persists), `role=status`/`alert` (D-16) | 🟡 |
| B3 | 7.14 Modal | No scrim, no Default-variant copy, no mobile form | Focus/overlay behaviour undefined | Default: centred, scrim `bg/scrim` @ 45% (as the mobile sheet), focus trap, Esc closes (D-17). Copy for each destructive dialog 🔴 (see D9) | 🟡 |
| B4 | 7.15 EmptyState | Only the "No materials yet" copy exists | Empty dashboard/analytics/chat/quiz copy unwritten | Copy to be written by owner; layout from the component | 🔴 |
| B5 | 7.3 Tab | Overflow when tabs exceed width (5 tabs = 413 px vs 358 px mobile) | Wrap vs scroll vs shrink | Default: single row, horizontal scroll without scrollbar, selected tab scrolled into view (D-3) | 🟡 |
| B6 | 7.6 CitationBadge | Inline 24×22 is below the 44 px rule; Touch variant unused | A11y vs fidelity conflict | Default: render Inline exactly as drawn and extend the hit area to 44×44 with transparent padding (no visual change); do not use Touch variant until design says so | 🟡 (D-6) |
| B7 | 7.10 SourceCard | Long passages / file names | Clamp vs grow | Figma truncates nothing → grow in height; no clamp | ✅ |
| B8 | 7.2 Input | Password reveal, textarea, error icon behaviour; disabled use | Not drawn | Build only the 6 drawn states; no extra affordances | ✅ |
| B9 | 7.9 Card | Whole-card click target, focus ring on keyboard | Link semantics unspecified | Default: card is a single link to the course workspace (D-5) | 🟡 |
| B10 | Workspace "TOPICS IN THIS FILE" chips | Chip instances 44 px high, selection not drawn | Interactive or decorative? | Owner decision. Interim: render non-interactive (not focusable) until defined | 🔴 |
| B11 | 7.20 ChatComposer | Multiline growth, max height, character limit, attachments | Only a one-line field is drawn | Owner decision on limit; default: field grows with content and the composer grows with it (min 102 px), no attachments | 🟡 (D-7) |
| B12 | 7.5 Tag | Long text / wrapping | Tag is a fixed 24 px pill | Default: never wraps (`white-space: nowrap`) | 🟡 |
| B13 | 7.15b Notice | Dismissible? Which icon per tone | Info uses `icon/info`, Warning uses `icon/alert` (confirmed); Neutral icon unknown | Not dismissible (no close drawn). Neutral tone: no icon until designed | ✅ |
| B14 | 7.18 Toggle | Thumb travel, disabled colours | Animation | Recorded positions (x0 → x24). Transition 150 ms? not specified → no animation beyond D-15 | ✅ |
| B15 | Avatar / Wordmark / User card | Not components | Re-implemented inconsistently | Specified in 7.23 as shared compositions | ✅ |
| B16 | Avatar initials rule | Only "LH" shown | Multi-word / single-word / non-Latin names | Default: first letter of first and last word, uppercase; single word → first two letters (D-21) | 🟡 |
| B17 | 7.17 NavItem | Selected label switches to 16/24 Medium (body-strong) vs 14/20 others | Text width jump on selection | Implement as drawn but reserve width (render both weights) only if design confirms the jump is a bug | 🔴 |
| B18 | Source panel "Previous" without "Next" | Asymmetric navigation, chevron points right | Which direction? Is there Next? | Owner decision; until then render as drawn and flag | 🔴 |
| B19 | Stat card, Topic row, Section, etc. | Un-componentised patterns | Different sizes per screen | 7.23 table | ✅ |
| B20 | Button Loading | Only one instance (composer Send "Answering…") | Loading look for other buttons | Reuse the Loading variant: 16 px spinner at left, label stays | ✅ |
| B21 | 7.7 / Quiz bar ProgressBar | Library has 3 fixed values; quiz bar uses Value=60 on both Q6 and Q7 | Which value at which question? | Value = (current question − 1) / total? Figma shows 60 at Q6 of 10 → progress = (current) / total ... see C-note in D-12 | 🟡 |
| B22 | Rail items | No labels, no tooltips | Accessible name/hover tooltip | Add `aria-label` = NavItem label; tooltip not designed → none | 🟡 |
| B23 | Breadcrumb | Plain text, not links | Navigation expectation | Default: parent segments are links styled identically (D-5) | 🟡 |
| B24 | Chip | Unselected/selected widths | Keep 36 pill in 44 hit box | Specified in 7.4 | ✅ |

## C. Screens where layout is ambiguous

| ID | Location | Problem | Why it is ambiguous | Recommended clarification | Status |
|---|---|---|---|---|---|
| C1 | 5.3 (v1) | v1 said "`max-width` = listed widths", contradicting Figma FILL sizing | Fluid vs capped content | Corrected: follow 5.4 FILL/FIXED table; no content cap | ✅ |
| C2 | All desktop screens | Frames have fixed heights (900–1320) | Scroll model unknown (frame clip, no scroll settings) | Default: document scroll; Sidebar/Rail/panels sticky, full viewport height; Sidebar spacer pushes user card to bottom (D-1) | 🟡 |
| C3 | 8.5 Summary | Content of collapsed sections (Advice, Weaving, Key terms) not drawn | Developer must invent bullets and "6 terms" layout | Owner to supply a Key-terms layout (term + definition?) and one expanded example | 🔴 |
| C4 | 8.3 Workspace | Selected-file panel has no mobile equivalent; M3 omits Lecture 1–2 | How does mobile reach file details/actions? | Owner decision; default: tapping a file item opens a bottom sheet with the same actions (D-4) | 🔴 |
| C5 | 8.9 Analytics "All courses" | Chip exists, view not drawn | Aggregated layout/ranking unknown | Owner decision | 🔴 |
| C6 | 8.10 Exam builder | Preview sticky? Behaviour when many topics | Long chip lists make page tall | Default: preview card is not sticky (no sticky behaviour in Figma) | 🟡 |
| C7 | 8.6 Chat with source panel | Chat column narrows to 988 and message column re-centres | Computed, not drawn for all states | Apply same rule to all five states | 🟡 |
| C8 | 8.6 mobile M6 | Body 434 px in 390 px frame | Overflow replicated? | Do not replicate; use 358 px content width | ✅ |
| C9 | 8.6 Mobile chat — other states, source sheet | Not drawn | Layout of Refused/Partial on 358 px | Reuse components at 358 px width; citation → bottom sheet like M5 (D-4) | 🟡 |
| C10 | Mobile for Auth, Dashboard, Upload, Quiz, Review, Exam, Settings, Data & privacy | 8 modules with no mobile frame | Entire layouts must be invented | Default stacking rules in D-4 (no new visual language); designer review recommended | 🟡 |
| C11 | Mobile nav | Tab bar has Home/Courses/Analytics/Settings only | Where are Personalised exam and Data & privacy? | Owner decision (Analytics already links to Exam builder; Privacy link location unknown) | 🔴 |
| C12 | Tablet 768–1439 | No frames | Sidebar vs rail vs bottom bar | Default breakpoints in D-3 | 🟡 |
| C13 | Quiz Review | Only Q6 expanded and Q7–9 collapsed; Q1–5, Q10 not shown | List composition unclear | Default: all 10 rows in order; wrong/partial expanded? (only one expanded at a time, first wrong answer open) (D-12) | 🟡 |
| C14 | Dashboard Row A | 716 + 24 + 340 = 1080 fixed? | Fluid growth of left card only | 5.4: left FILL, streak FIXED 340 | ✅ |
| C15 | Analytics grid | Right column 400 fixed, left fills | Collapse order below desktop width | Default: stack below 1024 px: left column then right | 🟡 |
| C16 | Auth below 1440 | Brand panel 640 fixed | When does it hide? | Default: hide brand panel below 1024 px, show only the card; trust points move below the card? Owner design preferred | 🔴 |
| C17 | Page header + sticky | Is the header or tabs sticky? | Not drawn | Default: not sticky (D-1) | 🟡 |
| C18 | Upload list ordering | Drawn order is by status, not time | Sorted by what? | Default: newest first, stable order thereafter (D-13) | 🟡 |
| C19 | Dashboard week dots | Always 7 days starting 6 days ago? | Labels F S S M T W T end on today (Thu) | Default: last 7 days ending today, oldest first; empty dot = not studied | 🟡 |

## D. Interactions that would force assumptions

| ID | Location | Problem | Why it is ambiguous | Recommended clarification | Status |
|---|---|---|---|---|---|
| D1 | Composer | Enter vs Shift+Enter | Send behaviour | Default: Enter sends, Shift+Enter newline; empty or Loading disables send (D-7) | 🟡 |
| D2 | Citation open/close | Focus management, URL state | Back button, sharing | Default: `?source=n`, Esc/close returns focus to the badge; sheet traps focus (D-8) | 🟡 |
| D3 | Summary accordion | Multi-open? default open? | Two sections open in Figma | Multi-expand; first two open by default; state not persisted | ✅ |
| D4 | Quiz Check answer | Feedback timing; next-step label not drawn | Prototype jumps to Review | With Settings "Show answer explanations right away" On: reveal Correct/Incorrect + explanation inline; Off: record and advance. Button label after reveal ("Next question") **not drawn → copy needed** | 🔴 |
| D5 | Skip question | Counts as wrong? Can return? | Scoring | Owner decision; default: skipped = unanswered, scored incorrect, shown in Review as Incorrect with "Skipped" tag? Tag copy not drawn | 🔴 |
| D6 | Exit quiz | Save progress? confirm? | Data loss | Default: confirm Modal, progress saved as draft (matches "Saved as a draft") — copy needed | 🔴 |
| D7 | Retry wrong answers | New attempt scope, scoring link to old attempt | Analytics double-count | Default: creates a new attempt containing the incorrect/partial questions | 🟡 |
| D8 | "Why this?" | Content/pattern (popover? panel?) | Not drawn | Owner decision | 🔴 |
| D9 | Destructive buttons (Delete files, Delete, Clear history, Reset, Delete account) | Confirmation copy and re-auth | Only one sample Modal copy | Owner to write 5 dialogs; default pattern Modal Destructive | 🔴 |
| D10 | Settings save model | Save button only on Profile | Do toggles save instantly? | Inferred from Figma: toggles and chips save immediately; Profile uses "Save changes" | ✅ |
| D11 | Theme chips | Apply instantly? persist? | Same as D10 | Instant, persisted in settings; "Match system" follows `prefers-color-scheme` | ✅ |
| D12 | Tabs | Routes vs local state; Analytics tab scope | Deep links | Default: each tab is a route (D-5); "Analytics" tab is course-scoped | 🟡 |
| D13 | Chips | Selection rules and minimum selection | Exam builder Topics could be empty | Default: Course/Count/Theme single-select (cannot deselect); Topics/Types multi, min 1; Start exam disabled otherwise (D-6) | 🟡 |
| D14 | Upload | Concurrency, folders, duplicates, cancel semantics | Not drawn | Default: multi-file, parallel; Cancel aborts and removes row; duplicates by name allowed — owner confirm | 🟡 |
| D15 | Regenerate summary | Replaces silently? Rate limit? | Data loss of old summary | Default: replaces; shows summary Loading state | 🟡 |
| D16 | Dashboard Practise | How many questions? | Recommendation uses 10 | Default: 10 questions on that topic | 🟡 |
| D17 | "New course" / Courses list | No frames | Flow unknown | Owner decision (Courses nav destination has no screen) | 🔴 |
| D18 | "Open in file" | Opens what | Viewer unknown | Owner decision (viewer, download, or deep link) | 🔴 |
| D19 | File list "Retry" | Same pipeline | Presumably | Default: re-queues the file | 🟡 |
| D20 | Sidebar user card | Menu/sign-out | Nowhere to sign out | Owner decision; until then non-interactive | 🔴 |
| D21 | Chip topic click in chat suggestions | Sends prefilled question | Presumably | Default: sends the chip text as the user message | 🟡 |
| D22 | Keyboard model | Tabs (arrow keys), radio groups, accordions | Not documented | Default WAI-ARIA patterns (D-6) | 🟡 |
| D23 | Hover on rows | No hover shown for list rows | Whether rows react | Default: no hover unless the component library defines it | 🟡 |
| D24 | Prototype only 7 links | Developer may think others are intended | See 9.2 | 9.2 is labelled recommendation | ✅ |
| D25 | Auth | Remember me, SSO, email verification, reset | Not drawn | Do not build until designed | ✅ |
| D26 | Animations | Only 250 ms ease-out smart-animate on 7 links | Panel/accordion/toggle timing | Default D-15 | 🟡 |
| D27 | Settings > email threshold | "Only for files larger than 20 MB" | Setting or copy? | Owner decision (see E-section) | 🔴 |

## E. Backend-facing behaviour not clearly specified

| ID | Location | Problem | Why it is ambiguous | Recommended clarification | Status |
|---|---|---|---|---|---|
| E1 | Whole app | No API contract | Frontend/backend drift | Contract defaults in section 19 | 🟡 |
| E2 | 8.4 | Processing pipeline states and legal transitions | UI states need a state machine | 19.2 state machine | 🟡 |
| E3 | 8.3/8.4 | How status changes reach the UI | Polling vs push | Default: poll while any item is non-terminal (D-19) | 🟡 |
| E4 | 8.6 | Chat response shape and state decision | UI must not infer state from text | 19.4 response fields; state enum decided server-side | 🟡 |
| E5 | 8.6 | Refusal / Partial / Low-confidence criteria | Retrieval thresholds | Owner decision (model/retrieval policy) | 🔴 |
| E6 | 8.9 / 13.17 | Mastery calculation and thresholds | Rings, tags, sorting all depend on it | Owner decision; proposed thresholds in D-20 | 🔴 |
| E7 | 8.9 | Recommendation generation | Rule-based vs model | Owner decision | 🔴 |
| E8 | 8.7 | Short-answer grading and "Partly correct" | Core quiz logic | Owner decision | 🔴 |
| E9 | 8.7/8.10 | Quiz/exam generation: sync or async, latency | Loading screens not drawn | Default: async job with status polling; show Loading Button state | 🟡 |
| E10 | 8.13 | Delete/Reset/Export semantics; 30-day window | Legal commitments in copy | Owner decision; copy "within 30 days" stays flagged placeholder | 🔴 |
| E11 | 8.4 | Max file size, page limits, rate limits | Copy says 100 MB | Owner decision; keep limits in config, display from config | 🔴 |
| E12 | 8.4 | OCR engine/languages, misread disclaimer | Copy promises OCR | Owner decision | 🔴 |
| E13 | 8.1 | `.edu` rule, password policy, session mechanism | Validation must match copy | Owner decision | 🔴 |
| E14 | 8.2 | "3 days to your … midterm" source | Needs exam dates | Owner decision (user-entered?) | 🔴 |
| E15 | 8.2/8.9 | Streak definition ("best") | Not defined | Owner decision; display only until defined | 🔴 |
| E16 | Isolation promise | "Never shared with other students" | Security requirement not testable | Every query scoped by authenticated user id; add negative tests (section 20) | 🟡 |
| E17 | Dates | Time zone of "Yesterday", greeting | Server vs client | Default: client time zone sent with requests; stored UTC (D-18) | 🟡 |
| E18 | Lists | Pagination of activity, conversations, uploads | Unbounded lists | Default: cursor pagination, page size configurable | 🟡 |
| E19 | Errors | Error format and user-facing messages | No error copy designed | Default: RFC 7807-style problem details; generic copy needed (owner) | 🟡 |
| E20 | Chat "Searching 12 files" | Count semantics | Indexed only? | Default: number of indexed files in scope | 🟡 |
| E21 | Analytics | "last 30 days" window; +8 points since September baseline | Baseline unknown | Owner decision | 🔴 |
| E22 | Citations | Locator model (page/slide/section) and passage addressing | Needs stable ids | 13.8/13.9 + 19.4 | 🟡 |
| E23 | Idempotency | Double submit of answers/uploads | Duplicates | Default: client-generated idempotency keys | 🟡 |

## F. Responsive behaviour that remains undefined

| ID | Location | Problem | Why it is ambiguous | Recommended clarification | Status |
|---|---|---|---|---|---|
| F1 | Breakpoints | None defined | Developer picks arbitrary values | Default D-3: mobile < 768; Rail layout 768–1023; Sidebar layout ≥ 1024 | 🟡 |
| F2 | 8 modules without mobile | See C10 | — | D-4 stacking rules | 🟡 |
| F3 | Mobile tabs overflow | See B5 | — | Horizontal scroll | 🟡 |
| F4 | Mobile keyboard / safe areas | Composer above keyboard, notch/home indicator | Not drawn | Default: composer sticks above keyboard; respect `env(safe-area-inset-*)` for Tab bar and composer | 🟡 |
| F5 | 391–1439 px | Fluid behaviour | Only 2 widths drawn | 5.4 FILL/FIXED rules; Chat/Quiz columns shrink below their fixed width? Default: `max-width` fixed value with `width: 100%` | 🟡 |
| F6 | Bottom sheet | Height at other viewport heights, drag to dismiss | Fixed 416 drawn | Default: content height, max 90% viewport, drag/Close/scrim dismiss | 🟡 |
| F7 | Chat panel at < 1280 px | Panel 380 + column 760 > viewport | Overlap or overlay? | Default: below 1280 px the source panel overlays as a right-side sheet (reuse sheet styling); owner confirm | 🟡 |
| F8 | Long names | Wrapping on mobile | Wrap everywhere (no truncation in Figma) | Wrap; no ellipsis | ✅ |
| F9 | Text scaling / zoom 200% | WCAG reflow | Fixed px frames | Use rem-based type/spacing derived from px tokens; test at 200% | 🟡 |
| F10 | Orientation / landscape | None | — | No special handling | ✅ |
| F11 | Mobile nav for Exam/Privacy | See C11 | — | Owner decision | 🔴 |
| F12 | Mobile Analytics omissions | Score history, Weak topics, 2 recommendations removed | Deliberate or oversight? | Treated as deliberate (as drawn); owner to confirm | 🔴 |

## G. Acceptance criteria that are not testable

| ID | Location | Problem | Why it is ambiguous | Recommended clarification | Status |
|---|---|---|---|---|---|
| G1 | 8.x.12 generally | "Matches the frame" has no tolerance | Pass/fail undefined | Section 20: ±1 px geometry, exact string match, token-bound colours | ✅ |
| G2 | 8.7.12 / 8.9.12 | Criteria that cite design defects ("known inconsistency") | Not a requirement | Removed from acceptance; kept in 16.2 | ✅ |
| G3 | 9.x | "ease-out ~250 ms" | No tolerance/measurement | 20.4 tolerance ±50 ms; `prefers-reduced-motion` → 0 ms | ✅ |
| G4 | 15 QA checklist | Checkbox items need measurable targets | Subjective | 20.1–20.3 tables | ✅ |
| G5 | Chat states | "Five states render" | How verified | 20.5 fixture-driven tests per state | ✅ |
| G6 | Accessibility | "WCAG AA" not operationalised | Needs tool + manual list | 20.6 | ✅ |
| G7 | Analytics sort order | "weakest first" ties/Not started placement | Not testable until rule set | Owner decision on mastery rules (E6) | 🔴 |
| G8 | Isolation | "Never shared with other students" | Needs negative tests | 20.7 | ✅ |
| G9 | Visual regression | No baseline/threshold | Flaky | 20.2 | ✅ |

## H. Contradictions inside the design documentation

| ID | Location | Problem | Why it is ambiguous | Recommended clarification | Status |
|---|---|---|---|---|---|
| H1 | 5.3 (v1) vs 4.4/5.4 | Capped vs fluid content | — | Fixed (fluid per 5.4) | ✅ |
| H2 | 7 intro (v1) vs 7.6 | "All interactive ≥ 44 px" vs Inline badge 24×22 | Rule has an exception | Documented exception + hit-area rule (B6) | ✅ |
| H3 | 4.4 `size/panel = 360` vs panels 380 / 340 | Token unused as named | Dev may use 360 for panels | `size/panel` = SourceCard width only; panels are 380 (Summary/Chat) and 340 (Workspace details) | ✅ |
| H4 | 6.4 | Course header "H1" vs Chat h2 | Style choice | Chat uses `h2` (4.7) | ✅ |
| H5 | 7.21 (v1) / 5.2 | User message plain vs bubble | — | Fixed | ✅ |
| H6 | 8.12 (v1) | Toggle row text styles (body-strong/body-sm) | Wrong | `label` + `caption` | ✅ |
| H7 | 8.7 (v1) | Quiz question style h3 | Wrong | `h2` | ✅ |
| H8 | 6.3 (v1) | Rail selected "not verified" | — | Courses always | ✅ |
| H9 | Design data | AOP mastery 74% (Dashboard, Workspace, M3) vs 72% (Analytics, M8) for the same course | Which is canonical for fixtures? | Owner decision; fixtures use 74% / 72% only if two different metrics are defined (course mastery vs overall) | 🔴 |
| H10 | Design data | File counts 12 / 7 / 9 / 6 / 36 | Fixture inconsistency | Fixtures per course derived from one dataset; copy bound to data, not literals | 🟡 |
| H11 | Design data | Streak 6 (best 9) vs 9 (best 12) | Same user | Fixture from one `streak` record; show one value | 🟡 |
| H12 | Design data | Quiz progress Value=60 for Q6 and Q7 | Library has only 25/60/100 | Continuous progress = current/total; do not copy fixed values | 🟡 |
| H13 | Design data | Weaving results: "2 of 6 correct" (Dashboard), "3 of 4 missed" (Analytics), "2 / 5" (Exam) | Different quizzes? | Treat as separate fixtures; no cross-screen assertion | 🟡 |
| H14 | Sidebar vs Rail | Same destinations, two shells, rule undocumented | Which screens use which | 6.1 table lists per screen; reason is owner decision | 🔴 |
| H15 | Weak definition | "under 50%" (Exam copy) vs Dashboard "Weakest topics" includes 56% Learning | Label vs threshold | Weakest = lowest three regardless of level | 🟡 |

## I. Places where implementation would require guessing

| ID | Location | Problem | Why it is ambiguous | Recommended clarification | Status |
|---|---|---|---|---|---|
| I1 | Date formats | "Thursday, 22 October", "Sep 14", relative times | Locale/format mix (day-month vs month-day) | D-18 formats exactly as drawn; locale en | 🟡 |
| I2 | Number formats | "3.1 MB", "84 MB", "76%", "2 / 5", "196 / 600" | MB definition, spacing | D-18: decimal MB (1 MB = 1,000,000 B)? flag; percent without space; slash with spaces | 🟡 |
| I3 | Pluralisation | "1 file / 7 files", "1 processing", "2 sources" | Singular rules | D-19 | 🟡 |
| I4 | Casing | Uppercase eyebrows | CSS vs authored | Authored uppercase, as in Figma strings | ✅ |
| I5 | Language/RTL | English only | Arabic/RTL users | Owner decision (no RTL frames) | 🔴 |
| I6 | Browser support | Not stated | Features (`:has`, container queries) | Owner decision; default evergreen last 2 versions | 🔴 |
| I7 | Z-order | Sticky nav vs panels vs sheet vs toast | Stacking bugs | D-23 ladder | 🟡 |
| I8 | Loading placeholders | Skeleton component only on Card | Other pages | Reuse `bg/subtle` skeleton bars (radius 4, 16 high) | 🟡 |
| I9 | Image of PDF pages / viewer | None | "Open in file" implies a viewer | See D18 | 🔴 |
| I10 | Test/QA fixtures | Sample data inconsistent | Developers hard-code frame data | Fixtures file per H10–H13; strings from section 10 | 🟡 |
| I11 | Component naming in code | Figma names have slashes | Mapping | Keep Figma property names (12.5) | ✅ |
| I12 | Analytics chart library | Chart is plain rectangles | Library vs DOM | Build with plain DOM/SVG (no library) to match 8 bars × 69 px | 🟡 |
| I13 | Persisted UI state | Accordion, filters | Persist? | Not persisted, except theme and settings | 🟡 |
| I14 | Draft persistence | "Saved as a draft" short answers | Where saved | Server-side attempt answer, debounced; copy shows after save | 🟡 |

---

## 18. Implementation Decisions (defaults adopted to remove guessing)

**Not Figma facts.** Each default can be overridden by a design/product decision; log overrides in section 16.

| ID | Default |
|---|---|
| D-1 | **Scroll model:** the page scrolls as a document. Sidebar/Rail and Source/Details panels are `position: sticky`, full viewport height, scrolling internally when needed. Headers/tabs are not sticky. |
| D-2 | **Fluid layout:** follow the FILL/FIXED table in 5.4 literally; no extra `max-width` on Main. |
| D-3 | **Breakpoints:** `< 768` mobile layout (M-frames); `768–1023` desktop layout with the **Rail** instead of the Sidebar; `≥ 1024` Sidebar layout; Rail-based screens always use the Rail. Below 1280 the Source panel opens as an overlay (reuse bottom-sheet styling positioned right). Auth brand panel hides below 1024 (owner to design). Tab rows scroll horizontally on overflow. |
| D-4 | **Mobile stacking for undrawn modules:** single column, 16 px padding, 16 px gap; 2-column grids collapse to 1; side panels and details become bottom sheets; stat cards 2-up (173 px) as in M8; buttons inside cards become full width; topic/result rows stack (name + Tag, then bar); App bar (Back + title) and Tab bar as in M3/M5/M8; Quiz uses no Tab bar. |
| D-5 | **Routing:** tabs and breadcrumb parents are links; Dashboard course cards are links; query param `?source=n` holds the open citation; `?course=` holds the analytics filter. |
| D-6 | **Selection semantics:** Course/Count/Theme chips = radio group (single, cannot deselect); Topics/Question types = checkbox group (≥ 1 selected); quiz options = radio group (arrow keys); tabs = `tablist` with arrow keys; accordions = disclosure buttons; Inline citation hit area extended to 44×44 with transparent padding. |
| D-7 | **Composer:** Enter sends, Shift+Enter newline; send disabled when empty or Loading; field auto-grows, composer min height 102; no attachments. |
| D-8 | **Source panel:** opening sets `?source=n` and marks that badge Active (in the panel and, as an addition to the drawn state, in the message); Esc or close button closes and returns focus to the badge; mobile sheet traps focus and closes on scrim click. |
| D-9 | **Destructive actions** open the Destructive Modal (Cancel + Danger confirm); copy supplied by the owner (4 data actions + account deletion + Exit quiz). |
| D-10 | **Settings:** toggles/chips persist immediately (optimistic UI, revert on error); only Profile has Save. |
| D-11 | **Quiz flow:** one question per screen; Skip leaves it unanswered (scored incorrect, **owner to confirm**); Check answer reveals feedback inline when the setting is On, otherwise advances; the last question leads to Review. Draft of short answer saved (debounced, server-side). |
| D-12 | **Review list:** all questions in order; the first incorrect or partial question is expanded; one expanded at a time. |
| D-13 | **Upload list:** newest first; order stable afterwards; Cancel aborts and removes the row; Remove deletes the local row and, if created, the file. |
| D-14 | **Motion:** spinner = `icon/loader` rotating 1 turn per second, linear; skeleton = static `bg/subtle` bars (no shimmer); ring/bar fills render instantly. All motion disabled with `prefers-reduced-motion`. |
| D-15 | **Transitions:** 250 ms ease-out for panel/sheet/page changes (matches the prototype); toggles, accordions and tabs change instantly. |
| D-16 | **Toast:** bottom-centre, 440 px max, 5 s auto-dismiss (Danger stays until closed), stacked 8 px apart. |
| D-17 | **Modal:** centred, scrim `color/bg/scrim` at 45%, focus trap, Esc closes, focus returns to the trigger. |
| D-18 | **Formats:** greeting date `Thursday, 22 October` (weekday, day, month; no year); chart dates `Sep 14` (month short, day); relative times "N hours ago / Yesterday / N days ago"; sizes with one decimal and "MB" (decimal units); percentages without space (`74%`); ratios with spaces (`2 / 5`, `196 / 600`); counts "n of m". Client time zone sent to the server. |
| D-19 | **Plurals and status transport:** singular/plural by count ("1 file", "7 files", "1 processing", "2 sources"); file status via polling while any item is non-terminal (interval configurable); SSE may replace it later. |
| D-20 | **Mastery levels (proposal, blocks Analytics sign-off):** Mastered ≥ 90 · Proficient 70–89 · Learning 50–69 · Weak 1–49 · Not started = no attempts — taken from the sample data and the "70% proficiency" footnote; calculation method left to the owner. Analytics sort: weakest first, Not started after Weak (as drawn). |
| D-21 | **Avatar initials:** first letter of first and last word, uppercase; single word → first two letters. |
| D-22 | **Hit areas & focus:** Inline badge 24×22 visible, 44×44 hit; focus rings per 4.5 (outside, except Input inside). |
| D-23 | **Z-index ladder:** content 0 · sticky nav/panels 10 · overlay panel/sheet 40 · scrim 40 (below its sheet) · modal 50 · toast 60. |
| D-24 | **Dark theme:** implement tokens; ship Light only until dark frames are approved, then enable via the Settings chips. |
| D-25 | **Draft/persistence:** UI state (accordion, filters, panel) is not persisted across sessions; theme and settings are. |
| D-26 | **Fonts:** self-host Inter 400/500/600/700, `font-display: swap`, no OpenType features. |
| D-27 | **Errors:** each failing request shows the closest existing pattern — inline Notice (Warning/Danger tone via Toast) with the server `detail` text; copy to be written. |

---

## 19. Backend Contract Defaults (FastAPI)

**Defaults, not Figma facts.** Purpose: remove backend guessing so frontend and API can be built in parallel. No code.

### 19.1 Conventions
- JSON over HTTPS; resource ids are opaque strings; timestamps ISO-8601 UTC.
- Auth: session cookie or bearer token (**owner decision**, E13); every endpoint is scoped to the authenticated user; accessing another user's resource returns 404.
- Errors: HTTP status + problem-details fields `type`, `title`, `status`, `detail`, `code` (stable machine code); validation errors add `errors[]` with `field` + `message`.
- Lists: cursor pagination (`limit`, `cursor`, response `next_cursor`).
- Idempotency: `Idempotency-Key` header on uploads, quiz-answer submits, exam creation.
- Limits (file size, pages, question length, rate) are **configuration values, unset until the owner decides**; the UI reads them from `GET /config`.

### 19.2 Material processing state machine
| From | To | Trigger | UI |
|---|---|---|---|
| (new) | `uploading` | upload started | Uploading row, progress % |
| `uploading` | `extracting` | upload complete, text extraction started | Extracting |
| `extracting` | `ocr` | scanned PDF detected | OCR row + workspace Notice |
| `extracting` / `ocr` | `indexed` | text indexed | Indexed row |
| `uploading` / `extracting` / `ocr` | `failed` | read/processing error | Failed row, Retry |
| `uploading` | `unsupported` | file type rejected | Not supported row, Remove |
| `extracting` / `ocr` | `empty` | no readable text | Empty row, Remove |
| `failed` | `uploading` / `extracting` | Retry | back to the active state |
| any | (deleted) | Remove / Cancel / Delete | row removed |

Terminal states: `indexed`, `failed`, `unsupported`, `empty`. Statuses carry `progress_pct` (uploading), `detail` (optional string for the row sentence) and `page_count` when known.

### 19.3 Endpoint table
| Area | Endpoint (illustrative) | Returns / does |
|---|---|---|
| Auth | `POST /auth/signup`, `/auth/login`, `/auth/logout`, `/auth/forgot-password` | session; validation errors per field |
| Me | `GET/PATCH /me`, `GET/PATCH /me/settings` | profile + settings (8.12.7) |
| Dashboard | `GET /dashboard` | greeting data, recommendation, streak, course summaries, weakest topics (3), recent activity |
| Courses | `GET/POST /courses`, `GET /courses/{id}` | course + stats |
| Materials | `GET /courses/{id}/materials`, `POST /courses/{id}/materials` (multipart), `GET /materials/{id}`, `DELETE /materials/{id}`, `POST /materials/{id}/retry`, `POST /materials/{id}/cancel` | status, progress, topics |
| Summary | `GET /materials/{id}/summary`, `POST /materials/{id}/summary/regenerate` | sections with statements + citation indexes |
| Sources | `GET /passages/{id}` | exact passage, surrounding text, locator, prev/next passage ids |
| Chat | `GET /courses/{id}/conversations`, `POST /courses/{id}/conversations`, `POST /conversations/{id}/messages`, `GET /conversations/{id}` | message with state |
| Quiz | `POST /courses/{id}/quizzes`, `GET /quizzes/{id}`, `POST /quizzes/{id}/attempts`, `PUT /attempts/{id}/answers/{qid}`, `POST /attempts/{id}/submit`, `GET /attempts/{id}/results`, `POST /attempts/{id}/retry-missed` | questions, drafts, results |
| Analytics | `GET /analytics?course_id=` | summary, topics, history (8), weak topics, recommendations |
| Exam | `GET /courses/{id}/topics`, `POST /exams`, `POST /exam-presets`, `GET /exams/{id}/results`, `POST /exams/{id}/retake-missed` | exam config/results |
| Privacy | `GET /me/data-summary`, `DELETE /me/materials`, `DELETE /me/summaries-and-quizzes`, `DELETE /me/chats`, `POST /me/analytics/reset`, `POST /me/export`, `DELETE /me` | counts; destructive actions return 202 + job where asynchronous |

### 19.4 Chat message response (fields)
`message_id` · `state` (`answered` | `refused` | `partial` | `low_confidence`; `loading` is a client state while the request is pending) · `files_searched` · `files_used` · `blocks[]` (`text`, `citation_indexes[]`) · `citations[]` (`index`, `material_id`, `file_name`, `locator_type`, `locator_label`, `short_label`, `passage_id`) · `notice` (`title`, `body`; present for partial and low_confidence) · `refusal` (`title`, `body`, `closest_citation`; present for refused) · `suggestions[]`. Invariant: `state = answered | partial | low_confidence` ⇒ every block has ≥ 1 citation; **no citation may reference a passage outside the user's materials**.

### 19.5 Quiz/result fields
Question: `id`, `type`, `prompt`, `hint`, `options[]`, `topic_id`. Attempt: `current_index`, `answers[]` (`question_id`, `option_id` | `text`, `skipped`, `saved_at`). Result per question: `status` (`correct` | `incorrect` | `partial`), `selected`, `correct_answer`, `explanation`, `citation`. Totals: `correct`, `total`, `score_pct`, `level`, `duration_minutes`.

### 19.6 Deletion cascade (from copy)
Deleting a file removes its summaries, quizzes and chat citations (privacy copy). Account deletion removes every file, summary, quiz and score "within 30 days" (**placeholder; owner**).

---

## 20. Testable Acceptance Criteria Supplement

### 20.1 Global measurable rules
- **Geometry:** every box listed in this document is within **±1 px** of its stated width/height/padding/gap at a 1440×900 viewport (desktop) or 390×844 (mobile), measured with computed styles.
- **Colour:** every computed colour equals a semantic token value (Light theme table 4.1.2); no hex literal appears in component source.
- **Type:** computed `font-size`, `line-height`, `font-weight`, `letter-spacing` match 4.2 for the element types in 4.7.
- **Copy:** visible strings equal the Figma strings character-for-character (including ’ “ ” — … ·).
- **Hit areas:** every interactive element has a ≥ 44×44 px hit box (Inline citation badge via padding).
- **Focus:** every focusable element shows a 2 px ring in `color/focus/ring` (outside; Input inside).
- **No horizontal scroll** at 390 px width on any mobile layout.

### 20.2 Visual regression
Playwright screenshots of each frame-equivalent route at 1440×900 / 390×844 compared to Figma exports (2× scale). Threshold: ≤ 0.5% differing pixels per frame after masking sample data and text anti-aliasing; any diff in layout boxes fails regardless of percentage.

### 20.3 Component checks (examples; repeat for each set)
| Component | Assertion |
|---|---|
| Button | 44 px high; padding 0/16; radius 8; Primary Default fill = `accent/default` and label = `on-accent`; Disabled uses `disabled/*` and is not focusable via click |
| Tab | Selected: label `accent/fg`, 2 px bottom border `accent/default`, `aria-selected=true` |
| Chip | 36 px pill inside a 44 px hit box; Selected shows check + `accent/subtle` fill, 1 px `accent/default` stroke |
| Tag | 24 px high, padding 0/8, radius 4, tone colours per 7.5 |
| CitationBadge | 24×22 visible, 44×44 hit; Active = solid `accent/default` with `on-accent` text |
| MasteryRing | Arc starts at 12 o'clock, sweep = value × 360°, colour = level token; text shows the % |
| FileUploadRow | Border `danger/border` for Failed/Unsupported/Empty; height equals content (74–106 px in the library) |
| AnswerOption | Correct/Incorrect show the verdict word and 2 px border in `success/solid` / `danger/solid` |
| ChatMessage | State classes render distinct structures: Refused has the title + closest SourceCard + TRY ASKING; Partial has Info Notice; Low confidence has Warning Notice |

### 20.4 Interaction checks
- Prototype parity: the 7 click paths in 9.1 succeed; animated transitions last 250 ± 50 ms and use ease-out; with `prefers-reduced-motion` they are instant.
- Citation: clicking `[1]` in an answer opens the panel with the matching passage, marks `[1]` Active, updates `?source=1`; Esc closes and returns focus.
- Composer: Enter sends; Shift+Enter inserts a newline; empty input keeps Send disabled.
- Accordion: multiple sections can be open; initial state = first two open.
- Settings: toggling a switch persists without pressing Save; "Save changes" persists the three profile fields only.

### 20.5 Chat state fixtures (each must pass)
For each of `answered`, `refused`, `partial`, `low_confidence`, and the pending `loading` state: render from a fixed API fixture; assert the caption text, the presence/absence of citations, the notice/refusal blocks, the sources row, and that **no state is chosen from free text**.

### 20.6 Accessibility
- axe-core: zero serious/critical violations on every route and every chat state.
- Contrast ≥ 4.5:1 for text, ≥ 3:1 for non-text (focus ring, mastery fills) in Light and Dark.
- Keyboard-only walkthrough of the 7-step prototype path succeeds without a mouse.
- Status is never colour-only: every Tag/Correct/Incorrect/mastery element has a text label.
- Zoom 200% and text-spacing overrides keep content reachable (no loss).

### 20.7 Backend / isolation tests
- A second test user cannot read, list or cite any resource of the first (404 on every endpoint in 19.3).
- Every answered/partial/low-confidence chat response has ≥ 1 citation and every citation resolves to a passage owned by the same user.
- Deleting a material removes its summary, quiz questions referencing it, and chat citations (fixtures assert zero remaining references).
- Status transitions obey 19.2; illegal transitions are rejected.

### 20.8 Per-module numeric checks (add to 8.x.12)
| Module | Checks |
|---|---|
| Auth | Card 440 wide, padding 40, gap 24; brand panel 640; error input border 2 px `danger/solid` with message text |
| Dashboard | Row A 716 + 24 + 340 at 1440; three course cards 344×162; 7 streak dots (6 filled) |
| Workspace | Columns 300 / 728 / 340; 7 file items; Stats 3 × 205 |
| Upload | Dropzone 1080×248, 2 px dashed (8/6); six rows with heights per 7.16 |
| Summary | Center 988 + panel 380; first two sections expanded; 5 sources listed |
| Chat | Message column 760 centred; with panel open chat column 988 + panel 380; composer 760×102 |
| Quiz | Bar 77 + progress 8; column 720 centred; options gap 12; short-answer field 720×160 with 2 px accent stroke |
| Review | Summary card 720×162; ring Lg 112; Q6 expanded, Q7–9 collapsed (58 px rows) |
| Analytics | Stats 4 × 258; grid 656 + 24 + 400; bar height = value × 1.6 px; 8 score bars 32 px wide |
| Exam builder | Settings 676 + 24 + preview 380; preview values update with selections |
| Exam results | Rows add up to 15 / 20; ring Lg 75% Proficient |
| Settings | Content 760 left-aligned; four cards in order |
| Data & privacy | Content 760; only the last button is Danger |
| Mobile | Sheet 390×416 over 45% scrim; app bar 61 (41 on Analytics); tab bar 69 (absent on Chat); no horizontal overflow |

---

*End of revision 2. Source of truth remains the Figma file; sections 18–20 are proposals and tests layered on top of it.*
