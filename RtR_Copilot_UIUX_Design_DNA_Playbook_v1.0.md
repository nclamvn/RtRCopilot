# RtR Copilot UI/UX Design DNA Playbook

## Pixel-precise product interface and experience contract

**Version:** 1.0  
**Date:** 27/07/2026  
**Status:** CANONICAL · LOCKED FOR IMPLEMENTATION  
**Product:** RtR Copilot  
**Product owner:** Nguyễn Cảnh Lâm · AI Officer · SOT Curator  
**Canonical visual reference:** `RtR_Copilot_Mockup_Aligned_v2.html`  
**Scope:** Web application, desktop-first, responsive enterprise interface  
**Primary users:** RtR employees, leadership, SOT curator, CEO/CTO  

---

## 0. How to use this playbook

This file is the normative design contract for RtR Copilot. It is not a moodboard and not a collection of optional suggestions.

The keywords below have fixed meanings:

- **MUST:** required. A build that violates it is not RtR Copilot.
- **MUST NOT:** prohibited.
- **SHOULD:** default implementation unless a documented exception exists.
- **MAY:** permitted but not required.

When this playbook, a Figma frame, and production code disagree, resolve in this order:

1. Product truth and governance principles.
2. This playbook.
3. The approved aligned HTML mock.
4. Figma implementation.
5. Production code.

Any intentional design change MUST update all of the following in the same change set:

- Design token or component rule in this playbook.
- Figma master component.
- Production component.
- Visual-regression reference image.
- Version history at the end of this file.

---

# Part I · Product and brand DNA

## 1. Product definition

### 1.1 Correct name

**RtR Copilot**

Do not present the product as:

- A generic chatbot.
- An internal ChatGPT clone.
- An AI assistant that knows everything.
- A document repository.
- A second knowledge base.

### 1.2 Product sentence

RtR Copilot is an operational interface over RtR's Source of Truth. It allows authorized employees to ask verified questions, trace every factual claim to a record, and generate deterministic documents from approved templates.

### 1.3 The three visible promises

Every major screen must reinforce at least one of these promises:

1. **Ask:** access approved knowledge in natural language.
2. **Verify:** inspect evidence, record, owner, tier, date and conflict state.
3. **Deliver:** produce controlled documents from locked facts and deterministic templates.

The external RtR rhythm `Invent. Build. Prove.` becomes the operational product rhythm:

> **Ask. Verify. Deliver.**

### 1.4 Product character

RtR Copilot must feel:

- Mission-ready.
- Engineered.
- Disciplined.
- Traceable.
- Calm under pressure.
- Premium through precision, not decoration.

It must not feel:

- Playful.
- Magical.
- Conversational for its own sake.
- Futuristic for display.
- Soft, rounded or consumer-like.
- Visually fragmented into many unrelated cards.

---

## 2. Immutable product principles

These principles govern both UX and interface behavior.

### NT-1 · Copilot is a view of the kernel

- The product reads only published knowledge packs from the SOT kernel.
- The interface MUST NOT offer arbitrary document upload into Copilot knowledge.
- An attachment control may attach user parameters to a task, but MUST NOT silently ingest them as canonical knowledge.
- The product MUST NOT become knowledge source N+1.

### NT-2 · Honest null

When no approved fact exists:

- State that the information is not present in SOT.
- Do not infer or complete the answer from model memory.
- Show the responsible domain or owner when policy permits.
- Log a knowledge gap.
- Offer a structured next action, not a fabricated answer.

### NT-3 · Every factual answer has evidence

Every answer containing factual claims MUST show:

- At least one record ID.
- Effective date or gate date.
- Access tier.
- Conflict or stale state.
- A path to full provenance.

### NT-4 · Documents are rendered deterministically

- The LLM may extract user parameters.
- The template schema validates required fields.
- The rendering service produces the file.
- Locked SOT facts cannot be manually overwritten in the document flow.
- Missing required fields block rendering with a fail-loud state.

### NT-5 · One controlled write path

- Employees may propose facts or report issues.
- Leaders may supply structured facts.
- Only the curator workflow writes to the kernel.
- The Copilot answer surface never writes directly to SOT.

---

## 3. RtR visual DNA translated into product UI

| RtR brand behavior | RtR Copilot translation |
|---|---|
| Black and graphite product world | Obsidian application shell |
| Warm yellow industrial signal | Active, verified, locked and primary action signal |
| Field proof | Record evidence, provenance and gate status |
| Large declarative statements | Decisive page and answer headings |
| Product specifications | Structured fact blocks and record tables |
| Fine technical rules | One-pixel structural grid |
| Squared engineering geometry | Low-radius or square components |
| Mission certainty | Honest-null, conflict and fail-loud behavior |
| Invent. Build. Prove. | Ask. Verify. Deliver. |

### 3.1 Visual restraint law

The interface obtains hierarchy from:

1. Alignment.
2. Space.
3. Typography.
4. Contrast.
5. One-pixel rules.
6. Yellow signal used sparingly.

It MUST NOT obtain hierarchy from:

- Gradient backgrounds.
- Glass effects.
- Neon cyan or purple.
- Glowing AI orbs.
- Decorative data particles.
- Excessive shadows.
- Large collections of floating rounded cards.

---

# Part II · Pixel system

## 4. Canonical reference canvas

### 4.1 Desktop reference

The primary design and visual QA frame is:

```text
Viewport: 1440 × 900 px
Pixel ratio for comparison: 1× CSS pixels
Minimum supported desktop height: 768 px
```

### 4.2 Reference coordinates at 1440 × 900

| Structural region | X | Y | Width | Height |
|---|---:|---:|---:|---:|
| Application | 0 | 0 | 1440 | 900 |
| Expanded sidebar | 0 | 0 | 236 | 900 |
| Sidebar brand header | 0 | 0 | 236 | 76 |
| Main application | 236 | 0 | 1204 | 900 |
| Main top bar | 236 | 0 | 1204 | 76 |
| Main body | 236 | 76 | 1204 | 824 |
| Copilot conversation at reference width | 236 | 76 | 848 | 824 |
| Evidence dock | 1084 | 76 | 356 | 824 |

### 4.3 Master alignment law

The bottom edge of the sidebar brand header and the bottom edge of the main top bar MUST occupy the same horizontal coordinate:

```text
Y = 76 px
```

This line must visually continue from the left edge of the application to the right edge without stepping up or down.

Do not create an additional competing header line inside either region.

### 4.4 Composer separation law

There MUST NOT be a full-width horizontal divider immediately above the composer.

The composer is separated from the conversation by:

- Empty space.
- Its own perimeter border.
- Subtle elevation.
- Background continuity.

The composer wrapper uses:

```css
border-top: 0;
```

An internal divider between the composer text area and its own toolbar is allowed because it belongs to the component, not to the page body.

---

## 5. Core dimension tokens

Production code SHOULD define these dimensions as semantic tokens rather than repeating literal values.

```css
:root {
  --rtr-header-h: 76px;
  --rtr-sidebar-w: 236px;
  --rtr-sidebar-w-compact: 74px;
  --rtr-evidence-w: 356px;
  --rtr-evidence-w-medium: 310px;
  --rtr-thread-max: 850px;
  --rtr-composer-max: 900px;
  --rtr-page-pad: 30px;
  --rtr-panel-head-h: 55px;
  --rtr-subhead-h: 44px;
  --rtr-filterbar-h: 48px;
  --rtr-radius-max: 8px;
}
```

### 5.1 Structural dimensions

| Element | Canonical value |
|---|---:|
| Expanded sidebar | 236 px |
| Compact sidebar | 74 px |
| Unified application header | 76 px |
| Evidence dock | 356 px |
| Medium evidence dock | 310 px |
| Evidence panel header | 55 px |
| Data page padding | 30 px |
| Conversation readable width | 850 px max |
| Composer width | 900 px max |
| Template registry | 320 px |
| Document preview column | 340 px |
| Template layout gap | 12 px |
| Standard subheader | 44 px |
| Filter bar | 48 px |

---

## 6. Spatial rhythm

### 6.1 Base system

- Base micro unit: **2 px**.
- Primary spacing unit: **4 px**.
- Primary layout rhythm: **8 px**.
- Approved exceptions exist only where specified by a component recipe.

### 6.2 Approved spacing scale

```text
2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
17, 18, 20, 24, 25, 26, 28, 30, 32, 34, 44, 46, 48, 55, 62, 76
```

Do not introduce arbitrary values outside this scale without updating this playbook.

### 6.3 Page spacing rules

- Data-heavy screens use `30px` outer padding.
- Conversation thread uses `28px 7vw 24px`.
- Composer wrapper uses `12px 5vw 18px`.
- Overview content uses `7vh 6vw`.
- Evidence body uses `14px` padding.
- Major card-to-card gaps are `9px` or `12px`.
- Micro gaps inside compact controls are `7px` to `11px`.

### 6.4 Fragmentation control

A region should normally have only:

- One outer structural border.
- One internal header divider.
- Local row dividers only where scanning requires them.

Avoid nesting a bordered card inside another bordered card unless the inner object has a distinct operational meaning.

---

## 7. Color system

### 7.1 Dark mode: canonical RtR mode

```css
:root {
  --rtr-bg: #050505;
  --rtr-sidebar: #080808;
  --rtr-panel: #0D0D0D;
  --rtr-panel-2: #121212;
  --rtr-panel-3: #171717;

  --rtr-text: #F2F1EC;
  --rtr-muted: #93938C;
  --rtr-faint: #64645F;

  --rtr-line: #292925;
  --rtr-line-2: #3A3933;

  --rtr-signal: #F0C400;
  --rtr-signal-ink: #171300;
  --rtr-success: #85B36B;
  --rtr-warning: #D0A73A;
  --rtr-danger: #D97867;
  --rtr-info: #8AA8C8;

  --rtr-shadow: 0 18px 50px rgba(0, 0, 0, 0.34);
}
```

### 7.2 Light mode: field-paper mode

```css
html[data-theme="light"] {
  --rtr-bg: #EFEEE8;
  --rtr-sidebar: #E7E5DD;
  --rtr-panel: #F9F8F3;
  --rtr-panel-2: #FFFFFF;
  --rtr-panel-3: #E9E7DF;

  --rtr-text: #12120F;
  --rtr-muted: #686760;
  --rtr-faint: #929087;

  --rtr-line: #D0CEC4;
  --rtr-line-2: #B7B4AA;

  --rtr-signal: #D5AD00;
  --rtr-signal-ink: #171300;
  --rtr-success: #4F7A3B;
  --rtr-warning: #9C7900;
  --rtr-danger: #A44F43;
  --rtr-info: #426C91;

  --rtr-shadow: 0 18px 50px rgba(25, 25, 18, 0.08);
}
```

### 7.3 Semantic use

| Token | Meaning | Use |
|---|---|---|
| Signal | RtR active control | Primary CTA, active navigation rule, record ID, locked SOT fact |
| Success | Verified/current | Sync dot, verified answer, PASS |
| Warning | Stale/reconfirm | Expired freshness, review queued |
| Danger | Conflict/fail-loud | Honest null rule, conflict, blocked render |
| Info | Neutral system information | Secondary informational state |

### 7.4 Yellow discipline

Yellow is a signal, not a background theme.

MUST use yellow for:

- One active navigation rule.
- Primary action.
- Locked SOT field indicator.
- Record IDs and critical technical markers.
- Selected technical highlight.

MUST NOT use yellow for:

- Large body backgrounds.
- Long paragraphs.
- Every icon.
- Multiple simultaneous competing CTAs.
- Decorative glow.

A normal screen should have one dominant yellow action and a small number of yellow technical markers.

---

## 8. Typography

### 8.1 Font stack

```css
font-family:
  Inter,
  ui-sans-serif,
  -apple-system,
  BlinkMacSystemFont,
  "Segoe UI",
  sans-serif;
```

When an official licensed RtR grotesk font becomes available, it may replace Inter only after testing Vietnamese diacritics, numeral widths and all component metrics.

### 8.2 Global typography

```css
font-size: 14px;
letter-spacing: -0.01em;
```

### 8.3 Type scale

| Role | Size | Weight | Line height | Tracking |
|---|---:|---:|---:|---:|
| Overview hero | `clamp(48px, 6vw, 82px)` | 650–750 | 0.92 | -0.065em |
| Page title | 30 px | 650–700 | 1.10 | -0.04em |
| Answer title | 25 px | 650–700 | 1.20 | -0.035em |
| Detail title | 19 px | 650 | 1.35 | -0.02em |
| Card title | 14 px | 600–700 | 1.35 | -0.01em |
| Main body | 14–15 px | 400–500 | 1.55–1.68 | -0.01em |
| Navigation | 12.5 px | 500–600 | 1.20 | normal |
| Compact title | 11–12 px | 600–700 | 1.35 | normal |
| Technical label | 8–10 px | 600–800 | 1.20 | 0.07–0.16em |
| Record ID | 9–10 px | 700–800 | 1.20 | 0.07em |

### 8.4 Text behavior

- Long Vietnamese text uses sentence case.
- Uppercase is reserved for short technical labels of approximately 1–4 words.
- Do not uppercase full Vietnamese sentences.
- Headlines are declarative, not promotional.
- Numerals and units must remain unbroken where possible: `56 min`, `30 lbs`, `L3`.
- Record IDs may use a monospace companion font, but all dimensions must be revalidated.

---

## 9. Geometry, borders and elevation

### 9.1 Radius

- Structural panels: `0px` default.
- Inputs and buttons: `0px` default in the canonical mock.
- Floating or exceptional surfaces: maximum `8px`.
- Status dots: circular.
- Do not introduce pill-shaped primary controls.

### 9.2 Borders

| Purpose | Specification |
|---|---|
| Default structure | `1px solid var(--rtr-line)` |
| Strong structure | `1px solid var(--rtr-line-2)` |
| Active navigation or selected evidence | `2px solid var(--rtr-signal)` on one edge |
| Honest null or fail-loud | `3px solid var(--rtr-danger)` on left edge |
| Focus | 2 px signal outline with 2 px visual offset |

### 9.3 Shadows

Shadows are reserved for objects that physically float over a continuous working plane:

- Composer.
- Document paper preview.
- Temporary menus and dialogs.

Standard panels, cards and tables MUST NOT all receive shadows.

### 9.4 Line hierarchy

- `--line` separates normal regions.
- `--line-2` marks stronger focus or component boundaries.
- Signal and danger lines have semantic meaning and must not be decorative.

---

## 10. Iconography

### 10.1 Style

- Outline icons.
- `24 × 24` viewBox.
- Stroke `currentColor`.
- Default stroke width `1.7`.
- Square line caps and restrained geometry preferred.
- Use one consistent library, such as Lucide, plus official RtR brand SVGs.

### 10.2 Canonical sizes

| Context | Visual size |
|---|---:|
| Sidebar navigation | 17 × 17 px |
| Topbar icon | 15 × 15 px |
| Quick-action arrow | 16 × 16 px |
| Workspace chevron | 14 × 14 px |
| Compact status icon | 12–14 px |

### 10.3 Hit areas

A control may show a 15–17 px icon while maintaining a larger hit area:

- Desktop minimum hit area: 36 × 36 px.
- Touch-capable layout: 44 × 44 px.

The current topbar visual button is `30 × 30 px`; production SHOULD enlarge the invisible hit area without changing visual alignment.

### 10.4 Logo rule

The CSS cross in the prototype is a layout placeholder. Production MUST use the approved official RtR mark in SVG form. Do not redraw or approximate the mark inside individual product teams.

---

# Part III · Application shell

## 11. Desktop shell

### 11.1 Grid

```css
.app {
  display: grid;
  grid-template-columns: 236px minmax(0, 1fr);
  height: 100vh;
}

.main {
  display: grid;
  grid-template-rows: 76px minmax(0, 1fr);
  min-width: 0;
}
```

### 11.2 Overflow contract

- `html` and `body` are fixed to viewport height.
- Global body does not scroll.
- Each screen owns its scroll area.
- Conversation thread scrolls independently from composer and evidence.
- Evidence body scrolls independently.
- Data pages scroll within `.section-page`.

This prevents the topbar, sidebar and composer from drifting out of alignment.

---

## 12. Sidebar

### 12.1 Dimensions and structure

```text
Width expanded: 236 px
Width compact: 74 px
Full height: 100 vh
Right border: 1 px
```

Order:

1. Brand header.
2. Workspace switcher.
3. Work navigation label.
4. Work navigation.
5. Governance label.
6. Governance navigation.
7. User identity footer.

### 12.2 Brand header

```text
Height: 76 px
Padding: 18 px 18 px 14 px
Internal gap: 12 px
Bottom border: 1 px
Mark: 34 × 34 px
```

Brand text:

- `RT ROBOTICS`: 13 px, weight 700+, tracking 0.13em.
- `COPILOT / INTERNAL`: 10 px, uppercase, tracking 0.14em, 3 px top gap.

The brand header bottom edge MUST align exactly with the main topbar bottom edge.

### 12.3 Workspace switcher

```text
Margin: 14 px 12 px 6 px
Padding: 10 px
Border: 1 px
Internal gap: 9 px
Tier badge: 26 × 26 px
Calculated outer height: 48 px
```

Content:

- Tier badge: `L3`.
- Title: `Employee Workspace`, 12 px.
- Subtitle: `Safe knowledge pack`, 10 px muted.
- Right chevron.

The switcher is a workspace/access context control, not a decorative card.

### 12.4 Navigation label

```text
Padding: 15 px 18 px 7 px
Font: 9 px / 700
Tracking: 0.16em
Color: faint
```

### 12.5 Navigation item

```text
Navigation container padding: 0 9 px
Item padding: 10 px
Icon-text gap: 11 px
Icon: 17 px
Text: 12.5 px
Active rule: 2 px left
Transition: 160 ms
```

States:

- Default: transparent, muted text.
- Hover: panel background, primary text.
- Active: panel-2 background, primary text, yellow left rule.
- Count: 10 px text, one-pixel perimeter, horizontal padding 6 px.

Do not use a rounded active pill.

### 12.6 Identity footer

```text
Top border: 1 px
Padding: 11 px 10 px 14 px
Profile padding: 8 px
Avatar: 28 × 28 px
Gap: 9 px
```

- Name: 11 px.
- Role/tier: 10 px muted.
- Identity is always visible on expanded desktop.

---

## 13. Topbar

### 13.1 Pixel specification

```text
Height: 76 px
Horizontal padding: 18 px
Internal gap: 12 px
Bottom border: 1 px
Background: application background
```

### 13.2 Content order

1. Breadcrumb.
2. Flexible spacer.
3. SOT sync/status chip.
4. Language control.
5. Theme control.
6. Command menu.

### 13.3 Breadcrumb

- Base text: 12 px muted.
- Current screen: 12 px, weight 600, primary text.
- Format: `RtR Copilot / Current screen`.

### 13.4 System chip

```text
Height: 28 px
Padding: 0 10 px
Gap: 8 px
Border: 1 px
Text: 10 px
```

The sync dot is `6 × 6 px`, success-colored, with a restrained three-pixel halo.

Canonical format:

```text
SOT SYNC  L3 · v2026.07.26
```

### 13.5 Icon button

```text
Visual box: 30 × 30 px
Border: 1 px
Background: panel
```

Hover changes border strength only. Do not animate scale or glow.

---

# Part IV · Screen architecture

## 14. Overview

### 14.1 Purpose

The Overview establishes product meaning and provides the three primary paths without becoming a dashboard of unrelated widgets.

### 14.2 Layout

```css
.home-screen {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 40%;
  height: 100%;
}
```

- Main content padding: `7vh 6vw`.
- Hero art occupies 40% of the main body width on large desktop.
- Art panel has a single left divider.

### 14.3 Hero

- Eyebrow: 10 px, yellow, uppercase, 0.15em tracking.
- Headline: `Ask. Verify. Deliver.`
- Headline size: `clamp(48px, 6vw, 82px)`.
- Line height: `0.92`.
- Tracking: `-0.065em`.
- Secondary line may use muted text, never a gradient.
- Supporting paragraph: max 610 px, 15 px, line height 1.6.

### 14.4 Quick actions

```text
Three columns
Gap: 9 px
Maximum group width: 820 px
Card padding: 16 px
Minimum height: 126 px
```

Each action contains:

- Technical index, such as `01 / ASK`.
- Direction arrow.
- 14 px title.
- 10.5 px explanation.

Hover:

- Border becomes yellow.
- Translate upward 2 px.
- No shadow burst.

### 14.5 Metrics

Metrics are plain typographic evidence, not separate boxed KPI cards.

- Group gap: 22 px.
- Top margin: 34 px.
- Label: 9 px uppercase.
- Number: 18 px.

### 14.6 Hero art

- Background: `#020202`.
- Left divider: 1 px.
- Technical grid: 44 × 44 px at 3.5% opacity.
- Grid fades vertically.
- Use product line art or approved product imagery only.
- Art label is anchored 32 px from sides and 34 px from bottom.

No generic AI brain, robot face or holographic assistant imagery.

---

## 15. Copilot conversation

### 15.1 Main layout

```css
.copilot-layout {
  display: grid;
  grid-template-columns: minmax(520px, 1fr) 356px;
  height: 100%;
}
```

The application sidebar is outside this grid. Inside the main body:

1. Conversation.
2. Evidence dock.

### 15.2 Conversation region

```text
Thread padding: 28 px 7 vw 24 px
Thread maximum readable width: 850 px
Composer wrapper: 12 px 5 vw 18 px
Composer maximum width: 900 px
```

The thread scrolls. The composer remains anchored at the bottom.

### 15.3 Thread metadata

- 10 px uppercase.
- 0.08em tracking.
- Faint color.
- 28 px bottom margin.
- A local trailing rule may follow the metadata label.

This local rule is permitted because it labels the thread section. It must not be confused with a full-width composer separator.

### 15.4 User question

```text
Alignment: right
Maximum width: 620 px
Padding: 14 px 16 px
Bottom margin: 30 px
Background: panel-2
Border: 1 px
Body: 14 px / 1.55
```

User messages do not use colored chat bubbles.

### 15.5 RtR answer anatomy

```text
Answer left padding: 46 px
Answer mark: 28 × 28 px
Answer bottom margin: 26 px
Heading bottom margin: 12 px
Paragraph bottom margin: 13 px
```

Required order:

1. RtR answer mark.
2. Trust state and effective date.
3. Direct heading.
4. Direct prose answer.
5. Structured facts when useful.
6. Citations.
7. Actions.

### 15.6 Trust header

- Verified label: 10 px uppercase, 0.08em tracking, success color.
- Effective date: 10 px faint.
- Gap between them: 9 px.
- Bottom margin: 14 px.

### 15.7 Structured fact grid

```text
Columns: 3 equal columns by default
Outer border: 1 px
Margin: 18 px 0
Cell padding: 14 px 15 px
Internal vertical divider: 1 px
Label: 9 px uppercase
Value: 18 px / weight 650
```

Use two or four columns only when content density requires it. Do not squeeze values into unreadable cells.

### 15.8 Citation chips

```text
Container gap: 8 px
Margin: 17 px 0
Chip padding: 7 px 9 px
Font: 10 px
Internal gap: 7 px
```

- Record ID is yellow and bold.
- Description is muted.
- Hover changes border to yellow.
- Clicking updates or opens the Evidence dock.

### 15.9 Answer actions

```text
Height: 29 px
Gap: 5 px
Horizontal padding: 9 px
Top margin: 17 px
```

Canonical actions:

- Copy answer.
- Use in document.
- Report issue.

Actions are secondary outlined controls, not competing primary buttons.

---

## 16. Composer

### 16.1 Component shape

```text
Maximum width: 900 px
Outer border: 1 px strong line
Background: panel-2
Elevation: standard shadow
Page separator above: none
```

### 16.2 Text area

```text
Height: 62 px
Padding: 14 px 15 px
Resize: disabled
Background: transparent
Border: none
```

Placeholder:

```text
Hỏi về spec, quy trình hoặc yêu cầu tạo tài liệu…
```

### 16.3 Toolbar

```text
Display: flex
Padding: 8 px
Internal top divider: 1 px
Send button: 32 × 28 px
```

Toolbar content:

1. Context/add action.
2. Template intent.
3. Permanent SOT constraint note.
4. Keyboard hint.
5. Send.

Permanent note:

```text
Copilot chỉ trả lời từ SOT
```

### 16.4 Attachment behavior

The plus button MUST NOT imply uncontrolled knowledge upload.

Allowed intents:

- Attach a note as user-supplied task input.
- Add parameter data to a document request.
- Reference a file for one-time extraction under explicit policy.

Disallowed behavior:

- Add the file to permanent SOT.
- Answer as if the file were approved truth.
- Hide the source class from the user.

### 16.5 Send behavior

- `⌘ Enter` submits on macOS.
- `Ctrl Enter` submits on Windows.
- Enter alone creates a new line.
- Empty input cannot be submitted.
- During processing, the send control becomes a deterministic stop/cancel control.

---

## 17. Evidence dock

### 17.1 Purpose

Evidence is part of the answer, not optional metadata. It remains visible on desktop.

### 17.2 Shell

```text
Width: 356 px
Left border: 1 px
Background: sidebar
Header height: 55 px
Header padding: 0 16 px
Body padding: 14 px
```

### 17.3 Panel header

- Title: 11 px uppercase, 0.07em tracking.
- Record count: 10 px muted, right aligned.

### 17.4 Trust card

```text
Padding: 14 px
Bottom margin: 11 px
Border: 1 px
```

Includes:

- Trust state.
- Confidence label.
- Coverage.
- Freshness.
- Access tier.
- Conflict state.

Confidence must never stand alone. It is subordinate to record coverage and provenance.

### 17.5 Confidence line

- Track: 3 px high.
- Top/bottom margin: 11 px.
- Fill color follows semantic status.
- A percentage is permitted but MUST have plain-language support.

### 17.6 Trust metadata

```text
Grid: 2 × 2
Gap: 9 px
Label: 8 px uppercase
Value: 10 px / 600
```

### 17.7 Evidence card

```text
Bottom margin: 9 px
Border: 1 px
Selected state: 2 px yellow left edge
Title padding: 12 px 12 px 9 px
Metadata padding: 8 px 12 px
```

Content:

- Record ID.
- Canonical record title.
- Domain or record type.
- Effective or gate date.
- Provenance link indicator.

### 17.8 Matched excerpt

```text
Padding: 12 px
Font: 10.5 px
Line height: 1.55
Border: 1 px
```

Matched text may use a low-opacity yellow highlight, approximately 23% mixed with transparency.

### 17.9 Compact behavior

At widths where the persistent dock is hidden:

- Citation chips open a right-side sheet or full-screen evidence view.
- The trust state remains visible in the answer header.
- Evidence may not disappear entirely.

---

## 18. Answer and system states

### 18.1 Verified

Visual:

- Success dot.
- Success text.
- Current effective date.

Behavior:

- Answer directly.
- Cite every material fact.
- Enable document reuse.

### 18.2 Needs reconfirmation

Visual:

- Warning status.
- Effective date and age.
- Owner or review queue.

Behavior:

- Answer only when policy allows stale facts.
- State that reconfirmation is needed.
- Do not present stale data as current.

### 18.3 Honest null

Visual:

```text
1 px perimeter
3 px danger left rule
14 px padding
```

Behavior:

- Say `SOT chưa có thông tin này.`
- Show domain owner when permitted.
- Log a gap.
- Offer `Gửi yêu cầu bổ sung fact`.

Do not apologize excessively and do not fill the gap from general model knowledge.

### 18.4 Restricted

Visual:

- Lock icon.
- Neutral or warning copy.
- No leaked record title or sensitive metadata.

Behavior:

- State that the information is outside the user's access tier.
- Do not confirm sensitive details through wording, record count or excerpts.

### 18.5 Conflict

Visual:

- Danger status.
- Two or more record references.

Behavior:

- Present the conflict explicitly.
- Do not silently choose a winner.
- Show owner and escalation path.
- Block deterministic document use for the conflicted field.

### 18.6 Retrieval/loading

- Use a thin yellow progress rule or small technical status line.
- No skeleton shimmer.
- No pulsing orb.
- Stages may be named: `RETRIEVE`, `CHECK TIER`, `VERIFY`, `COMPOSE`.

### 18.7 System error

- Distinguish system failure from honest null.
- Do not record infrastructure failure as a knowledge gap.
- Preserve the user's question for retry.
- Provide a trace ID.

---

## 19. Document Studio

### 19.1 Desktop layout

```css
.template-layout {
  display: grid;
  grid-template-columns: 320px minmax(480px, 1fr) 340px;
  gap: 12px;
  min-height: 670px;
}
```

Columns:

1. Template registry.
2. Parameter and fact form.
3. Rendered preview.

### 19.2 Shared panel

- One-pixel perimeter.
- Panel background.
- Square geometry.
- Standard subheader height: 44 px.

### 19.3 Template item

```text
Margin: 8 px
Padding: 12 px
Internal gap: 11 px
Document icon: 32 × 38 px
```

States:

- Default: transparent border.
- Hover: panel-2 background.
- Active: strong line border and panel-2 background.

Metadata:

- Title: 11 px.
- Description: 9.5 px / 1.4.
- Version or category: 8 px uppercase.

### 19.4 Three-step progress

```text
Columns: 3 equal
Bottom border: 1 px
Step padding: 11 px
Active underline: 2 px yellow inset
```

Canonical steps:

1. Request parsed.
2. Complete fields.
3. Review and render.

### 19.5 Field classes

#### User parameter

- Editable.
- One-pixel border.
- Panel-2 background.
- Focus border yellow.

#### Locked SOT fact

- Read-only.
- Yellow 2 px left rule.
- Record ID visible.
- Subtle yellow surface mix, approximately 4%.
- No edit affordance.

#### Derived field

- Generated from validated inputs.
- Visually identified as derived.
- Reviewable before render.

#### Required missing

- Danger helper text.
- Render button disabled.
- Field appears in error summary.
- No partial document is emitted.

### 19.6 Field dimensions

```text
Field bottom margin: 14 px
Label bottom margin: 6 px
Input padding: 10 px
Textarea height: 84 px
Helper top margin: 4 px
```

### 19.7 Document preview

Preview column background represents a physical review surface rather than a dark card.

```text
Column background: #C9C7BF
Paper width: 286 px
Paper minimum height: 404 px
Paper margin: 18 px auto 8 px
Paper padding: 26 px 24 px
Paper shadow: 0 12 px 35 px rgba(0,0,0,.24)
Top signal rule: 5 px
```

The preview MUST show:

- Template name/version.
- SOT verification stamp.
- Record IDs used.
- Draft/final state.
- Render status.

### 19.8 Render gate

Render is allowed only when:

- All required user parameters exist.
- Every locked fact resolves to a current permitted record.
- No used field has an unresolved conflict.
- Template schema passes.
- The render service returns PASS.

Gate vocabulary:

- `READY`.
- `RENDERING`.
- `PASS`.
- `FAIL-LOUD`.
- `BLOCKED BY CONFLICT`.
- `REJECTED BY TIER GATE`.

---

## 20. Source of Truth explorer

### 20.1 Purpose

This screen is a read-only record explorer. It is not a raw file browser and not a second record editor.

### 20.2 Page header

```text
Data page padding: 30 px
Header bottom padding: 18 px
Header bottom margin: 18 px
Bottom divider: 1 px
```

- Kicker: 9 px uppercase, yellow.
- Title: 30 px.
- Description: max 620 px.
- Actions align to the bottom-right of the header.

### 20.3 Summary stats

```text
Four equal columns
Gap: 9 px
Bottom margin: 16 px
Card padding: 14 px
```

- Label: 9 px uppercase.
- Number: 24 px.
- Status note: 9 px.

### 20.4 Filter bar

```text
Height: 48 px
Horizontal padding: 12 px
Gap: 8 px
Bottom border: 1 px
Search width: minimum 300 px
Search height: 30 px
Filter height: 28 px
```

### 20.5 Data table

Columns:

1. Record.
2. Fact or capability.
3. Domain.
4. Owner.
5. Effective date.
6. Status.

Dimensions:

- Header padding: 10 px 12 px.
- Body cell padding: 12 px.
- Header font: 8 px uppercase.
- Body font: 10.5 px.
- Record ID is yellow and weight 700.
- Row hover uses panel-2 background.

### 20.6 Record detail

Opening a record shows a drawer or detail pane containing:

- Canonical statement.
- Record ID.
- Source provenance.
- Effective date.
- Superseded record.
- Tier.
- Signoffs.
- Used-by answers.
- Used-by documents.
- Report issue action.

Employees may report or propose a correction. They may not edit canonical content directly.

---

## 21. Knowledge Gaps

### 21.1 Purpose

A failed answer becomes a controlled knowledge collection signal rather than a hidden model failure.

### 21.2 Layout

```css
.gap-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr);
  gap: 12px;
}
```

### 21.3 Queue row

```text
Columns: 54 px / flexible / 100 px / 90 px
Padding: 13 px
Bottom divider: 1 px
```

Content:

- Ask frequency.
- Canonical grouped question.
- Unique-user and recency summary.
- Suggested domain owner.
- Priority.

### 21.4 Frequency

- Main number: 20 px / 650.
- Unit label: 8 px muted.

### 21.5 Gap detail

- Body padding: 16 px.
- Technical labels: 8 px uppercase.
- Detail title: 19 px / 1.35.
- Observed variants appear in a one-pixel list.
- Primary action spans full panel width.

### 21.6 Ranking

The score may combine:

- Total asks.
- Unique users.
- Recency.
- Business criticality.
- Domain coverage.

Do not expose employee-level behavioral analytics outside curator permissions.

---

## 22. Audit Trail

### 22.1 Purpose

The audit trail shows immutable events from question through source, answer, document and publish gate.

### 22.2 Timeline

```text
Left line: 1 px strong line
Left margin: 18 px
Maximum width: 900 px
Item left padding: 30 px
Item bottom padding: 28 px
Node: 9 × 9 px with 2 px yellow border
```

### 22.3 Event content

- Time: 8 px uppercase.
- Title: 12 px.
- Description: 10 px / 1.5.
- Event card top margin: 9 px.
- Event card padding: 10 px.
- Gate code: 9 px, yellow.
- Actor: 9 px muted, right aligned.

### 22.4 Audit vocabulary

Use operational gate language:

- `PASS`.
- `BLOCKED`.
- `FAIL-LOUD`.
- `REJECTED BY TIER GATE`.
- `CONFLICT DETECTED`.
- `SUPERSEDED`.

Avoid vague labels such as `Something went wrong` when a precise event state exists.

---

# Part V · Components and interaction contracts

## 23. Buttons

### 23.1 Primary

```text
Height: 34 px on data screens
Horizontal padding: 13 px
Background: signal
Text: signal-ink
Border: signal
Weight: 700
```

Only one primary action should dominate a local region.

### 23.2 Secondary

- Panel background.
- Strong neutral border.
- Primary text.
- Hover translates upward at most 1 px.

### 23.3 Tertiary

- Transparent background.
- Muted text.
- Border optional according to context.
- Hover raises text contrast.

### 23.4 Disabled

- Preserve layout.
- Reduce contrast.
- Cursor communicates disabled state.
- Add plain-language reason near the control when the block is operationally important.

---

## 24. Inputs

### 24.1 Default

- One-pixel neutral border.
- Panel-2 background.
- Primary text.
- Padding 10 px in data forms.
- No inner shadow.

### 24.2 Focus

- Yellow border.
- Visible keyboard focus outline.
- Do not rely on border color alone for error states.

### 24.3 Error

- Danger helper text.
- Error icon or label.
- Associated message via accessible description.

### 24.4 Read-only and locked

Read-only is not disabled.

- Text remains fully legible.
- Locked SOT facts show yellow edge and record ID.
- Cursor and label communicate source protection.

---

## 25. Status tags

```text
Height: 20 px
Padding: 0 7 px
Border: 1 px strong line
Font: 8 px uppercase
Tracking: 0.07em
```

Statuses:

- Current: success.
- Reconfirm: warning.
- Conflict: danger.
- Restricted: muted + lock.
- Draft: neutral.

Tags are not rounded pills in the canonical system.

---

## 26. Cards and panels

### 26.1 Structural panel

- One-pixel perimeter.
- Panel background.
- No shadow.
- Square geometry.
- Optional fixed subheader.

### 26.2 Action card

- One-pixel perimeter.
- Clear action title.
- Hover may change border and move by 1–2 px.
- Entire card may be clickable if semantics are clear.

### 26.3 Evidence card

- Record-centric.
- Selected with a left signal rule.
- Never use a photo or decorative illustration.

### 26.4 Trust card

- Summarizes evidence quality.
- Cannot replace record-level evidence.

---

## 27. Tables and lists

- Tables are used for comparable records.
- Lists are used for event streams, gaps and navigation.
- Row height is determined by 12 px vertical padding in standard data tables.
- Sticky headers MAY be used on long data sets.
- Zebra striping is not part of the default visual language.
- Hover background is subtle panel-2.
- Sorting must be explicit in header controls.

---

## 28. Dialogs, drawers and sheets

### 28.1 Modal use

Use a modal only when an operation temporarily blocks the parent task, such as:

- Confirming a render or export.
- Displaying a critical conflict resolution gate.
- Confirming a destructive curator action.

Do not place ordinary record evidence in a modal on desktop.

### 28.2 Drawer use

Use a right drawer for:

- Full record detail.
- Compact-screen evidence.
- Audit event detail.

Recommended desktop drawer width: `420–520 px` depending on content.

### 28.3 Overlay

- Dark mode overlay: black at approximately 55–65%.
- No backdrop blur by default.
- Escape closes only when the operation is safe to dismiss.

---

## 29. Notifications

Use notifications for completed background actions, not for every click.

Recommended types:

- Render complete.
- Export complete.
- Fact request sent.
- Issue reported.
- Sync failed.

A notification MUST include:

- What happened.
- Status.
- Relevant object or trace ID.
- Next action when needed.

Avoid casual success language such as `Awesome!`.

---

## 30. Motion

### 30.1 Timing

| Interaction | Duration |
|---|---:|
| Hover color/border | 120–160 ms |
| Panel state | 160–180 ms |
| Drawer enter/exit | 180–220 ms |
| Route transition | 0–160 ms |

### 30.2 Easing

Use restrained standard easing:

```css
cubic-bezier(0.2, 0, 0, 1)
```

### 30.3 Permitted motion

- Border transition.
- One- or two-pixel lift.
- Drawer translation.
- Thin progress rule.
- Controlled answer streaming.

### 30.4 Prohibited motion

- Floating particles.
- Continuous ambient movement.
- Pulsing AI object.
- Animated gradients.
- Large spring/bounce effects.
- Skeleton shimmer.

### 30.5 Reduced motion

All nonessential animation MUST respect `prefers-reduced-motion`.

---

# Part VI · UX behavior

## 31. Primary Copilot intent routing

A user request is classified into one of four explicit paths:

1. **Verified question.** Retrieve, verify, answer and cite.
2. **Document request.** Parse parameters and enter Document Studio.
3. **Fact issue or correction.** Open a structured report/proposal flow.
4. **Restricted or unsupported request.** State policy without leaking content.

The user should not need to learn commands to access these paths.

---

## 32. Verified question flow

1. User submits question.
2. System detects access tier.
3. Retrieval runs only against the permitted published pack.
4. Claims are mapped to records.
5. Freshness and conflicts are checked.
6. Answer is composed.
7. Citations and evidence appear together.
8. Event is written to audit.

A factual answer is complete only when the record path is available.

---

## 33. Document request flow

1. User requests a document in natural language.
2. Copilot identifies a registered template.
3. User parameters are extracted.
4. SOT facts are resolved and locked.
5. Missing required parameters are requested.
6. User reviews values and provenance.
7. Render gate runs.
8. Preview appears.
9. User exports or revises parameters.
10. Audit records the schema version, records and output.

Do not make the user repeat facts that already exist in SOT.

---

## 34. Report issue flow

1. User selects `Report issue` on an answer or record.
2. The system pre-fills answer ID, record ID and cited excerpt.
3. User selects issue type:
   - Incorrect.
   - Outdated.
   - Ambiguous.
   - Missing source.
   - Access concern.
4. User adds concise context.
5. Submission creates an immutable issue event.
6. Curator queue receives it.

The original answer remains traceable and is not silently rewritten.

---

## 35. Knowledge gap flow

1. Retrieval returns no permitted approved fact.
2. Copilot displays honest null.
3. Question is normalized and grouped with variants.
4. Domain owner is suggested.
5. Frequency and business criticality update priority.
6. Curator sends a structured fact request.
7. Approved fact enters kernel.
8. Publish gate updates the relevant pack.
9. Gap is resolved with links to the new record.

---

## 36. Role and access UX

### L3 Employee

Visible:

- Overview.
- Copilot.
- Document Studio.
- Employee-safe Source of Truth.

Can:

- Ask.
- Verify.
- Generate permitted documents.
- Report issues.
- Propose facts.

Cannot:

- Edit SOT.
- Access L1/L2 material.
- Change tiers.

### L2 Leadership

Receives all L3 capabilities plus approved leadership records and workflows.

### L1 Curator

Receives governance tools:

- Gap processing.
- Fact intake.
- Conflict review.
- Tier proposal.
- Publish gate.
- Full audit.

### L1 CEO/CTO

Receives approval and oversight capabilities according to policy.

### Access display rule

The current workspace and tier must remain visible in the shell. A user should not have to infer which knowledge pack is active.

---

## 37. Microcopy system

### 37.1 Voice

RtR Copilot copy is:

- Direct.
- Precise.
- Calm.
- Evidence-oriented.
- Operational.

### 37.2 Good examples

```text
Verified from SOT
Effective 22 Jul 2026
SOT chưa có thông tin này.
Document cannot render until Meeting date is complete.
Two conflicting records require curator review.
Rejected by tier gate.
```

### 37.3 Bad examples

```text
I think this might be...
Here is my best guess...
Oops! Something went wrong.
Great news! Your amazing document is ready!
Our AI confidently believes...
```

### 37.4 Bilingual behavior

- Navigation labels may follow the selected interface language.
- Record IDs, gate codes and product names remain unchanged.
- A citation opens the canonical source language and may provide a translated explanation.
- Do not mix Vietnamese and English randomly inside one sentence.

---

# Part VII · Responsive system

## 38. Breakpoints

The approved mock uses two primary breakpoints:

```css
@media (max-width: 1150px) { ... }
@media (max-width: 900px)  { ... }
```

Production may add a mobile breakpoint only while preserving the rules below.

---

## 39. Medium desktop and tablet landscape: 901–1150 px

Changes:

- Evidence dock becomes 310 px.
- Document Studio becomes two columns.
- Live preview column is hidden and accessible by an explicit preview action.
- Overview art panel is hidden.
- Main overview becomes one column.

The unified 76 px header remains unchanged.

---

## 40. Compact: 900 px and below

Changes:

- Sidebar collapses to 74 px.
- Brand copy, navigation text, counts and workspace text hide.
- Icons remain centered.
- Evidence dock hides from the persistent grid.
- Evidence opens as a drawer or full-screen sheet.
- Document Studio becomes one column.
- Template registry becomes a selector or drawer.
- Quick actions stack.
- Stats use two columns.

The compact sidebar brand region remains exactly 76 px high so the header line still aligns.

---

## 41. Mobile portrait guidance

The current approved HTML is desktop-first. A production mobile implementation SHOULD use:

- No persistent sidebar.
- 56–64 px mobile topbar, documented as a separate mobile token.
- Bottom or drawer navigation.
- Full-width conversation.
- Composer safe-area inset.
- Evidence full-screen sheet.
- Document forms one column.
- Preview as a dedicated route.

Do not scale the desktop UI down proportionally. Recompose it.

---

# Part VIII · Accessibility and resilience

## 42. Accessibility

### 42.1 Contrast

- Normal text: target WCAG AA 4.5:1.
- Large text: target 3:1.
- Muted and faint tokens must be tested on every background they appear on.
- Status must not depend on color alone.

### 42.2 Keyboard

All interactive controls MUST be reachable by keyboard.

Required behavior:

- Visible focus state.
- Logical focus order.
- `⌘K` or `Ctrl K` opens command menu.
- `⌘ Enter` or `Ctrl Enter` submits composer.
- Escape closes dismissible overlays.
- Evidence cards are operable with Enter/Space.

### 42.3 Screen readers

- Icon-only controls require accessible names.
- Status dots require text equivalents.
- Tables use proper headers.
- Error messages are associated with fields.
- Streaming answers announce completion without reading every token.

### 42.4 Zoom and text scaling

The interface MUST remain usable at 200% browser zoom. Horizontal scrolling is acceptable for complex tables only when an alternative detail view exists.

---

## 43. Empty states

Empty states must explain operational meaning.

### No conversation history

- State what Copilot can answer.
- Offer 2–3 starter prompts.
- Repeat that answers come only from SOT.

### No search results

- Distinguish `no matching current records` from `record exists but is restricted` without leaking restricted content.
- Offer filter reset.

### No gaps

- State that no unresolved knowledge gaps match current filters.
- Do not use celebratory illustration.

### No audit events

- Explain the selected date/filter scope.

---

## 44. Performance behavior

- Shell and last active screen should render before secondary data.
- Preserve composer and navigation stability during loading.
- Evidence cards may appear progressively after the answer shell, but the answer cannot be marked verified until evidence is ready.
- Large tables should use pagination or virtualization.
- Document preview loading must show render stage and trace ID.

Suggested product targets:

- Shell interactive: under 1.5 s on corporate broadband.
- Navigation response: under 100 ms perceived.
- First answer status: under 500 ms.
- No cumulative layout shift in the shell.

---

# Part IX · Implementation contract

## 45. Recommended component hierarchy

```text
AppShell
├── Sidebar
│   ├── BrandHeader
│   ├── WorkspaceSwitcher
│   ├── NavigationGroup
│   └── UserProfile
├── MainShell
│   ├── Topbar
│   │   ├── Breadcrumb
│   │   ├── SotSyncChip
│   │   ├── LanguageControl
│   │   ├── ThemeControl
│   │   └── CommandMenuButton
│   └── ScreenRouter
│       ├── OverviewScreen
│       ├── CopilotScreen
│       │   ├── ConversationThread
│       │   ├── Composer
│       │   └── EvidenceDock
│       ├── DocumentStudioScreen
│       ├── SourceOfTruthScreen
│       ├── KnowledgeGapsScreen
│       └── AuditTrailScreen
```

---

## 46. Suggested design token naming

```text
color.bg.canvas
color.bg.sidebar
color.bg.panel
color.bg.panelStrong
color.text.primary
color.text.muted
color.text.faint
color.border.default
color.border.strong
color.signal.primary
color.status.success
color.status.warning
color.status.danger

size.header.app
size.sidebar.expanded
size.sidebar.compact
size.panel.evidence
size.content.threadMax
size.content.composerMax

space.page.data
space.thread.inline
space.composer.inline

motion.fast
motion.normal
```

Component code MUST consume semantic tokens. Do not scatter raw hex values and shell dimensions throughout the application.

---

## 47. Figma structure

Recommended Figma pages:

1. `00 Foundations`
2. `01 Shell`
3. `02 Copilot`
4. `03 Document Studio`
5. `04 Source of Truth`
6. `05 Governance`
7. `06 Responsive`
8. `07 Prototype`
9. `08 QA References`

### Component naming

```text
Shell/Sidebar/Expanded
Shell/Sidebar/Compact
Shell/Topbar/Default
Navigation/Item/Default
Navigation/Item/Active
Status/Tag/Current
Status/Tag/Reconfirm
Status/Tag/Conflict
Copilot/Answer/Verified
Copilot/Answer/HonestNull
Copilot/EvidenceCard/Default
Copilot/EvidenceCard/Selected
Document/Field/UserParameter
Document/Field/SOTLocked
Document/Field/RequiredMissing
```

### Variant properties

Use explicit properties such as:

- `state=default|hover|focus|active|disabled`.
- `trust=verified|stale|null|restricted|conflict`.
- `theme=dark|light`.
- `tier=L1|L2|L3|L4`.
- `density=default|compact`.

---

## 48. CSS reference shell

```css
:root {
  --header-h: 76px;
  --sidebar-w: 236px;
  --sidebar-w-compact: 74px;
  --evidence-w: 356px;
}

.app {
  display: grid;
  grid-template-columns: var(--sidebar-w) minmax(0, 1fr);
  height: 100vh;
}

.sidebar {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border-right: 1px solid var(--line);
}

.brand {
  height: var(--header-h);
  border-bottom: 1px solid var(--line);
}

.main {
  display: grid;
  grid-template-rows: var(--header-h) minmax(0, 1fr);
  min-width: 0;
}

.topbar {
  height: var(--header-h);
  border-bottom: 1px solid var(--line);
}

.copilot-layout {
  display: grid;
  grid-template-columns: minmax(520px, 1fr) var(--evidence-w);
  height: 100%;
}

.composer-wrap {
  border-top: 0;
}
```

The four highlighted invariants are:

1. One header height token.
2. Brand and topbar use that token.
3. Main body begins immediately below it.
4. Composer wrapper has no body-level top divider.

---

# Part X · Quality gates

## 49. Pixel QA

### 49.1 Reference viewports

Capture visual-regression snapshots at:

- 1440 × 900.
- 1280 × 800.
- 1150 × 800.
- 900 × 768.
- 768 × 1024 for compact/tablet review.

### 49.2 Tolerances

At the 1440 × 900 canonical viewport:

- Master header line: 0 px vertical mismatch.
- Sidebar width: ±0 px.
- Evidence width: ±0 px.
- Major panel boundaries: ±1 px.
- Internal spacing and typography: ±1 px where font rendering permits.
- Text wrapping may vary only when the approved font metrics differ.

### 49.3 Overlay inspection

Use 50% opacity overlay comparison between implementation and approved reference.

Check in order:

1. Global coordinates.
2. Header line.
3. Sidebar/main vertical boundary.
4. Evidence boundary.
5. Composer position.
6. Typography baselines.
7. Internal component spacing.
8. Color and border contrast.

Do not begin polishing icons while the shell grid is misaligned.

---

## 50. Shell acceptance checklist

- [ ] Sidebar is exactly 236 px at desktop.
- [ ] Compact sidebar is exactly 74 px.
- [ ] Brand header and topbar are exactly 76 px.
- [ ] Their bottom borders form one uninterrupted horizontal line.
- [ ] Main body begins at y = 76 px.
- [ ] No full-width body divider appears above the composer.
- [ ] Composer has its own border and elevation.
- [ ] Sidebar remains fixed while screen content scrolls.
- [ ] Topbar does not jump between routes.
- [ ] Evidence width is exactly 356 px on the canonical desktop.

---

## 51. Copilot acceptance checklist

- [ ] Every factual answer shows one or more citations.
- [ ] Effective date is visible.
- [ ] Trust state is textual, not color-only.
- [ ] Evidence opens from every citation.
- [ ] Honest null never fabricates missing content.
- [ ] Conflict blocks silent selection.
- [ ] Restricted state leaks no sensitive metadata.
- [ ] Composer note states that Copilot answers from SOT.
- [ ] Arbitrary upload is not represented as knowledge ingestion.
- [ ] Keyboard submission works.

---

## 52. Document Studio acceptance checklist

- [ ] Template version is visible.
- [ ] User parameters are editable.
- [ ] SOT fields are visibly locked.
- [ ] Locked fields show record IDs.
- [ ] Required missing fields block render.
- [ ] Conflict blocks render.
- [ ] Tier rejection blocks render.
- [ ] Preview shows SOT verification state.
- [ ] Audit records template, records, user and output.
- [ ] No LLM-generated freeform file bypasses the render service.

---

## 53. Accessibility acceptance checklist

- [ ] All controls have accessible names.
- [ ] Focus is visible in dark and light themes.
- [ ] Keyboard order matches visual order.
- [ ] Status is not color-only.
- [ ] Text contrast meets target.
- [ ] 200% zoom remains usable.
- [ ] Reduced motion is honored.
- [ ] Table headers and form labels are semantic.
- [ ] Errors are associated with inputs.

---

## 54. Anti-pattern gate

Reject a design or implementation containing any of the following unless formally approved:

- Different heights for sidebar header and topbar.
- An extra horizontal rule above the composer.
- Uncontrolled nested card borders.
- Rounded pill navigation.
- Neon blue/purple AI styling.
- Gradient primary buttons.
- Glowing or animated AI orb.
- Evidence hidden by default on large desktop.
- Confidence score without citations.
- Editable SOT facts inside a document.
- Generic upload-to-knowledge action.
- Silent conflict resolution.
- Decorative dashboard metrics unrelated to user action.
- Multiple equally dominant yellow CTAs in one region.
- Consumer-style celebratory copy.

---

# Part XI · Governance

## 55. Design change process

A design change request must include:

1. Problem observed.
2. User or operational evidence.
3. Proposed change.
4. Screens and components affected.
5. Governance and access impact.
6. Pixel/token impact.
7. Responsive impact.
8. Accessibility impact.
9. Updated reference images.
10. Owner signoff.

Pure aesthetic preference is not sufficient to weaken truth, citation, access or deterministic-render behavior.

---

## 56. Definition of done

A feature is complete only when:

- Product behavior follows NT-1 through NT-5.
- Design tokens are used.
- Component states are complete.
- Desktop and compact layouts pass.
- Dark and light modes pass.
- Keyboard and screen-reader behavior pass.
- Audit events are defined.
- Error, empty, restricted, conflict and honest-null states exist.
- Visual regression passes at canonical viewports.
- Documentation is updated.

---

## 57. Canonical visual signature

A screen should be recognizable as RtR Copilot even without the logo when it exhibits all of the following:

- Obsidian or field-paper base.
- One continuous structural grid.
- Warm yellow used as a technical signal.
- Off-white editorial typography.
- Thin one-pixel rules.
- Square, restrained geometry.
- Fact-first content.
- Record-level evidence.
- Fail-loud system behavior.
- Minimalist composition with low fragmentation.

This is the RtR Copilot design DNA.

---

# Appendix A · Canonical component measurements

| Component | Measurement |
|---|---|
| Application header | 76 px |
| Sidebar expanded | 236 px |
| Sidebar compact | 74 px |
| Brand mark | 34 × 34 px |
| Workspace badge | 26 × 26 px |
| Workspace outer height | 48 px |
| Navigation icon | 17 × 17 px |
| Topbar system chip | 28 px high |
| Topbar icon button | 30 × 30 px visual |
| Evidence dock | 356 px |
| Evidence header | 55 px |
| Evidence body padding | 14 px |
| Answer mark | 28 × 28 px |
| Question max width | 620 px |
| Thread max width | 850 px |
| Composer max width | 900 px |
| Composer textarea | 62 px high |
| Composer send | 32 × 28 px |
| Page padding | 30 px |
| Standard button | 34 px high |
| Standard subheader | 44 px high |
| Template registry | 320 px |
| Template preview column | 340 px |
| Document icon | 32 × 38 px |
| Document paper | 286 × min 404 px |
| Filter bar | 48 px high |
| Search field | min 300 × 30 px |
| Filter chip | 28 px high |
| Status tag | 20 px high |
| Audit node | 9 × 9 px + 2 px border |

---

# Appendix B · Canonical page inventory

| Screen | Core job | Primary action | Persistent proof |
|---|---|---|---|
| Overview | Orient and route | Ask a verified fact | SOT sync and tier |
| Copilot | Answer with evidence | Send question | Citation and Evidence dock |
| Document Studio | Produce controlled file | Render document | Locked fact IDs and render gate |
| Source of Truth | Inspect approved record | Propose/report fact | Provenance and effective date |
| Knowledge Gaps | Prioritize missing knowledge | Send fact request | Ask frequency and owner |
| Audit Trail | Trace system actions | Export/filter audit | Immutable event code |

---

# Appendix C · Version history

## v1.0 · 27/07/2026

- Established canonical RtR Copilot UI/UX design DNA.
- Locked unified application header at 76 px.
- Locked expanded sidebar at 236 px and compact sidebar at 74 px.
- Locked evidence dock at 356 px.
- Required one continuous horizontal header line through the full application.
- Removed body-level horizontal divider above the composer.
- Defined product principles, screen recipes, trust states, deterministic document UX, responsive behavior, accessibility and pixel QA gates.

