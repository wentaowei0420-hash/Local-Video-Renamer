# Mobile Library Parity Design

Date: 2026-06-19

## Goal

Bring the Flutter mobile app into closer parity with the desktop library experience while keeping the current constraints unchanged:

- personal use only
- Android sideload
- fully offline
- read-only app behavior
- direct reads from the existing `video_database.db`

This design covers three gaps:

1. non-local videos opened from actor/code-prefix flows do not consistently have a detail page
2. actor tier and code-prefix tier are not surfaced in the mobile UI
3. desktop library filtering rules are not applied in the mobile app

## Non-Goals

- adding write operations to the mobile app
- editing ladder tiers on mobile
- embedding the desktop Python backend into Android
- redesigning the database schema
- implementing a mobile filter editor in this phase

## Constraints

- Mobile remains a direct SQLite reader built in Flutter.
- The app must still work with no network and no backend process.
- The app must tolerate partial data: local-only rows, web-only rows, and mixed rows.
- The app must not depend on desktop runtime services.

## Recommended Approach

Implement parity in Flutter by recreating only the read-only display logic needed by mobile:

1. keep SQLite as the primary source of truth
2. add a small Dart-side repository for filter settings JSON
3. centralize mobile library shaping rules in the repository layer
4. keep screens focused on rendering already-shaped view models

This avoids shipping Python to Android and preserves the current offline installation model.

## Architecture

### 1. Unified mobile read layer

Add a shared mobile data layer that can build a consistent video-facing record from multiple tables.

Sources:

- `processed_videos` for local videos and richest local metadata
- `actor_movies` for actor-library web/indexed rows
- `code_prefix_movies` for code-prefix-library web/indexed rows
- `ladder_entries` for actor/prefix tiers
- `video_filter_settings.json` for desktop-aligned hide rules

Responsibilities:

- resolve a requested video code into the best available detail payload
- merge local and indexed fields with deterministic fallback order
- apply the same filter settings anywhere video lists are shown
- expose tier metadata for actor and code-prefix entities

### 2. Detail fallback strategy

Video detail loading becomes a two-stage lookup:

1. try `processed_videos` first
2. if not found, synthesize a read-only detail record from indexed rows in `actor_movies` and `code_prefix_movies`

The resulting detail view model must include a source flag:

- `local` when backed by `processed_videos`
- `indexed` when built from non-local library rows

UI behavior:

- local rows show file-path-specific fields when present
- indexed rows omit file-only sections such as physical storage path
- both local and indexed rows still show code, title, actors, release date, category, status, prefix, and related navigation

### 3. Tier parity

Actor and code-prefix screens must read ladder tier data directly from `ladder_entries`.

Behavior:

- actor detail reads `board_key = actor`, `entity_type = actor`
- code-prefix detail reads `board_key = code_prefix`, `entity_type = code_prefix`
- actor and code-prefix list cards show a lightweight tier badge when a tier exists
- detail headers show the tier alongside existing summary facts
- video detail does not invent a separate video-tier concept in this phase

### 4. Filter parity

Mobile adopts the same hide-rule shape as desktop by reading a companion JSON file:

- `video_database.db`
- `video_filter_settings.json`

Rules included in phase 1:

- code keyword rules
- title keyword rules
- JAVTXT tag keyword rules

Application points:

- video library list
- actor detail related videos
- code-prefix detail related videos
- any future mobile video-list surface should use the same filter helper

Fallback behavior:

- if the JSON file is missing, load desktop-equivalent defaults
- if the JSON file is malformed, ignore the bad file and fall back to defaults without crashing

## Data Model Changes

### Video detail

Extend the mobile `VideoDetail` model with:

- `detailSource`
- any extra merged fields required to distinguish local vs indexed records cleanly

### Actor detail

Extend `ActorDetail` with:

- `ladderTier`

### Code-prefix detail

Extend `CodePrefixDetail` with:

- `ladderTier`

### List items

Extend actor and code-prefix list item models with:

- `ladderTier`

This keeps list pages and detail pages consistent.

## Repository Design

### LibraryDetailRepository

Update detail repository behavior as follows:

- `fetchVideoDetail(code)`
  - local-first query against `processed_videos`
  - fallback query against indexed tables when local row is absent
  - merge actors, prefix, title, status, category, tags, and release-date fields using a fixed priority order
- `fetchActorDetail(actorName)`
  - include `ladderTier`
  - apply mobile filter rules to related video rows before mapping them
- `fetchCodePrefixDetail(prefix)`
  - include `ladderTier`
  - apply mobile filter rules to related video rows before mapping them

### Library list repositories

Update list repositories so that:

- actor search results include tier metadata
- code-prefix search results include tier metadata
- video rows continue to be paginated after filtering, not before filtering

Filtering must happen before final result slicing so page counts reflect visible rows.

## Filter Settings Design

Add a Flutter-side repository/service pair:

- `FilterSettingsRepository`
  - loads JSON from the app's expected companion file location
  - falls back to built-in defaults when file is missing or invalid
- `VideoFilterService`
  - evaluates code/title/tag rules against mobile row maps
  - exposes `isVisible(row)` and `filterRows(rows)`

The JSON structure must remain compatible with desktop's existing rule shape so the same file can be copied alongside the database.

## UI Design

### Video detail screen

- always opens when a code can be resolved from any supported source
- shows a compact source badge such as `Local` or `Indexed`
- only renders storage/file sections when those fields actually exist

### Actor detail screen

- show actor tier in the hero summary when present
- continue listing related videos, but after filter rules are applied

### Code-prefix detail screen

- show prefix tier in the hero summary when present
- continue listing related videos, but after filter rules are applied

### List cards

- actor cards get a tier badge
- code-prefix cards get a tier badge
- no empty placeholder badge when tier is absent

## Error Handling

- Missing local row with indexed fallback available: open indexed detail instead of showing not-found.
- Missing both local and indexed rows: keep the existing empty state.
- Missing filter file: use default rules silently.
- Invalid filter file: log internally if useful, but keep UI usable with defaults.
- Missing tier entry: render no tier badge rather than an error.

## Testing Strategy

Add focused tests for:

1. video detail falls back to indexed rows when `processed_videos` has no match
2. indexed detail omits local-only fields but still renders core metadata
3. actor detail exposes ladder tier when a ladder entry exists
4. code-prefix detail exposes ladder tier when a ladder entry exists
5. actor and code-prefix list rows map ladder tier correctly
6. filter settings loader uses defaults when JSON is missing
7. filter settings loader uses defaults when JSON is invalid
8. video filtering hides rows by code/title/tag rules
9. pagination reflects filtered visible rows rather than raw rows

## Implementation Order

1. add filter settings repository and Dart-side filter service
2. add tier fields to models and repositories
3. implement video-detail local-first fallback
4. wire filtered related-video lists through actor/code-prefix detail repositories
5. render tier badges and detail-source UI
6. add regression tests

## Risks

- Filtering before pagination may require repository query reshaping if current SQL-only paging is too early.
- Indexed rows may have inconsistent field completeness across `actor_movies` and `code_prefix_movies`; merge precedence must be explicit.
- Mobile file-location conventions for `video_filter_settings.json` must match the database copy workflow clearly in documentation.

## Decision Summary

We will keep the mobile app fully offline and read-only, avoid embedding Python, and close parity gaps by moving the missing desktop read logic into Flutter repositories and models. The implementation will prioritize consistent detail navigation, visible actor/prefix tiers, and desktop-aligned hide rules across mobile library surfaces.
