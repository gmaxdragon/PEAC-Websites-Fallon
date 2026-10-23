# PEAC website changelog

Dates use America/Los_Angeles. The public changelog is available at `/changelog`.

## 2026-10-22: line icons and reliability fixes (2026.10.22.2)

- Replaced authored emoji and decorative glyph icons with same-origin monochrome SVG symbols on public pages, sign-in, newsletter cards and the private console. User-submitted text is not rewritten.
- Kept the scroll-triggered theme switch and breathing timing intact.
- Require a valid Lunch Buddies receipt before showing success. Retry with the same key, retain details after malformed responses, and lock fields while sending.
- Recover safely from malformed saved browser state; offer a retry when request availability cannot load.
- Add feedback retry keys and per-visitor throttling instead of a single 12-per-hour limit shared by all public visitors.
- Preserve newer public/private feedback drafts if an earlier save completes.
- Bound sign-in and initial session requests with timeouts and reject malformed success replies.
- Preserve roster edits across searches, grade/week changes and refreshes; save hidden changed rows as well as visible ones. Empty counts are not silently treated as zero.
- Normalize student-name spacing and Unicode consistently to avoid duplicate weekly totals. Ambiguous existing duplicates are reported, not merged or deleted.
- Restore three CSV and two Excel template downloads, fix the removed public-directory anchor, and keep `/admin` aliases behind existing authentication.
- Add keyboard navigation and explicit tab associations for entry modes, and an accessible private-feedback label.
- Add regression coverage for server permissions, templates, forms, icons, responsive console sections and failure recovery. Tests use isolated data; no production forms are submitted.

## 2026-10-22

### Reversible page-wide scroll theme

Theme revision: `2026.10.22.1`. Supersedes the static section fade in `2026.10.21.3`.

- Switch the entire public homepage to forest green when the feedback divider reaches the upper part of the viewport. Scrolling back above it restores the light theme.
- Update page backgrounds, text, form fields, cards, symbols and footer together. Remove the isolated Coming soon mask and extra fade padding.
- Keep the switch position stable with a small hysteresis buffer and color-only changes, passive scroll listeners and one queued animation-frame measurement.
- Recalculate for restored positions, deep links, resize, orientation changes, and asynchronously loaded content. Avoid keyboard-induced threshold shifts during editing.
- Keep the breathing dialog's palette, controls and timing isolated from the theme. No backend, authentication, storage or data changes.
- Improve narrow-screen touch targets and use 16px form text. Respect both reduced-motion controls.
- Add Chromium and WebKit checks across 11 desktop/tablet/phone viewport configurations. Cover both directions, threshold stability, deep links, reloads, draft preservation, text contrast and breathing controls.
- Add a read-only production UI check that waits for the exact deployed JavaScript before checking the live page. It does not submit forms.

## 2026-10-21

### Soft transition into Coming soon

Visual refinement: `2026.10.21.3`.

- Replaced the hard top border and shadow with a gradual, background-only fade into the forest-green Coming soon section.
- Kept headings, cards and links fully opaque and below the fade for readability.
- Scaled the fade for phones and larger screens, with standard and Safari-compatible masking.
- The fade is static and remains available with reduced motion. No new scrolling animation or script was added.
- Preserved the box-breathing code, interface, timing and controls without modification.
- Extended five-viewport browser checks to verify the computed fade, text placement and unchanged breathing access.

### Spread-out symbols and a broader coming-soon preview

Public layout revision: `2026.10.21.2`. This is a presentation-only update; the application release and breathing tool remain unchanged.

- Distributed outline symbols through seven staggered spaces across the homepage, not only along the edges.
- Made the desktop margin artwork extend along the full document, with fewer visible decorations on small screens.
- Replaced the single online-compliments teaser with six broad areas: kindness and connection, community activities, moments of calm, student ideas, resources and support, and future extras.
- Added a forest-green section with cream, sage and warm neutral cards, clearer typography, responsive spacing and links to feedback and the changelog.
- Clearly labeled the preview as future ideas, not available features or a dated release promise.
- Preserved the box-breathing interface, timing, controls and styles without modification.
- Added isolated browser regression checks at 1440, 1024, 768, 390 and 320 pixels for overflow, decoration placement, anchors, reduced motion and breathing-dialog access.

### Design and navigation

- Refreshed the public homepage layout, headings, spacing, and decorative artwork.
- Added dark forest-green orbital artwork with eight animated planets and a centered PEAC ribbon.
- Added a quote-of-the-day strip below the hero.
- Simplified margin ribbon doodles to an outer outline without interior crossing lines, and removed the main ribbon’s interior highlight.
- Added a dated public changelog with navigation links and feedback access.
- Improved private-console typography, touch targets, and form readability on small screens.
- Added a dedicated homepage breathing section, visible launch controls, and breathing access from the changelog. The guide runs for three rounds and 48 seconds in total.

### Box breathing

- Completed the guided three-round, 48-second exercise using four equal four-second phases.
- Kept keyboard operation, visible phase guidance, pause/resume, and reduced-motion support.

## 2026-10-20

### Community publishing and motion

Source commit: `23857894f1c535bc88af280735b5a8b31d29cdae`.

- Added newsletter drafts and explicit public publishing in the existing private console.
- Added a public feed that displays published newsletter posts only.
- Added version checks and idempotent retries for newsletter changes, with 16 access and persistence tests.
- Added the initial three-round box-breathing guide.
- Added eight orbiting planets, margin doodles, floating notes, and shared button and panel transitions.
- Made the homepage header scroll with the page and added a dismissible site notice.

### Public resources

Source commit: `aa592776e28d7dc5dcd43c000eb29782c6c6c4eb`.

- Added public PEAC Introductions slideshow and Lunch Support Google Form cards.
- Added hover summaries, accessible preview dialogs, and direct new-tab links.
- Retained the existing website Lunch Buddies signup and private approval workflow.
- Added persistent reduced-motion controls and kept Google embeds restricted to public HTML pages.
