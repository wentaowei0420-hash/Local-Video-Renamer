# Actor Cup Field Details Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store parsed cup-size data alongside bust/waist/hip and show it as a separate field on the actor detail page.

**Architecture:** Extend `actor_enrichments` with `binghuo_cup` and `baomu_cup`, update both scrapers/enrichment save paths to capture cup values, then surface a merged `cup` field in actor detail data and UI. Keep existing bust/waist/hip behavior unchanged.

**Tech Stack:** Python, SQLite, PyQt5, `unittest`, regex-based scraper parsing

---

### Task 1: Lock Cup Parsing and Display Behavior With Tests

**Files:**
- Modify: `tests/test_baomu_actor_scraper.py`
- Modify: `tests/test_binghuo_actor_scraper.py`
- Modify: `tests/test_actor_profile_display.py`
- Modify: `tests/test_actor_detail_viewer.py`
- Modify: `tests/test_binghuo_actor_profile_storage.py`

- [ ] **Step 1: Add failing tests**

Cover:
- `84cm (D)` stores bust `84` and cup `D`
- `B:80(C)` stores bust `80` and cup `C`
- detail data exposes merged cup
- detail UI shows a separate cup field

- [ ] **Step 2: Run targeted tests to verify they fail**

Run: `python -m pytest tests/test_baomu_actor_scraper.py tests/test_binghuo_actor_scraper.py tests/test_actor_profile_display.py tests/test_actor_detail_viewer.py tests/test_binghuo_actor_profile_storage.py -v`
Expected: FAIL because cup fields are not stored or displayed yet

### Task 2: Implement Cup Storage and Detail Wiring

**Files:**
- Modify: `app/data/database_handler.py`
- Modify: `app/scraper/baomu_actor_scraper.py`
- Modify: `app/scraper/binghuo_actor_scraper.py`
- Modify: `app/services/enrichment/actor_baomu_enrichment.py`
- Modify: `app/services/enrichment/actor_binghuo_enrichment.py`
- Modify: `app/services/detail/actor_detail_library.py`
- Modify: `app/gui/actor_detail_viewer.py`
- Modify: `app/gui/i18n.py`

- [ ] **Step 1: Add minimal implementation**

Implement:
- new DB columns + row mapping
- save methods accept `cup`
- scrapers parse cup
- enrichment services pass cup through
- detail library merges cup from Binghuo/Baomu
- actor detail UI shows separate `罩杯`

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_baomu_actor_scraper.py tests/test_binghuo_actor_scraper.py tests/test_actor_profile_display.py tests/test_actor_detail_viewer.py tests/test_binghuo_actor_profile_storage.py -v`
Expected: PASS
