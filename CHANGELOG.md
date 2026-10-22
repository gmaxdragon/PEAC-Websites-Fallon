# PEAC website changelog

Dates use America/Los_Angeles. The public changelog is available at `/changelog`.

## 2026-10-21

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
