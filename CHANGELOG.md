# PEAC website changelog

Dates use America/Los_Angeles. The public changelog is available at `/changelog`.

## 2026-10-21

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
