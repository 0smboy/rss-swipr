# Changelog

## Integrated Update

### Backend and Data

- Fixed Open Graph fetch crash caused by metadata save signature mismatch.
- Unified Open Graph response shape for cache hit/miss paths.
- Kept compatibility aliases for legacy frontend fields.

### Mobile UX

- Built a focused minimal mode for mobile.
- Removed non-essential visual noise in minimal mode.
- Improved tap-to-open reliability and action feedback behavior.

### Desktop UX

- Reworked desktop layout for better center alignment and visual balance.
- Added desktop minimal mode directional mouse controls (up/down/left/right).
- Ensured minimal/full mode switching behaves consistently across viewports.

### Link Opening Stability

- Fixed desktop "double navigation" when opening original links.
- Added open action de-dup lock and stable new-tab opening path.

### Repository Cleanup

- Consolidated docs into concise `README.md` + this changelog.
- Removed redundant one-off migration/troubleshooting documents.

更新日期: 2026-02-05
