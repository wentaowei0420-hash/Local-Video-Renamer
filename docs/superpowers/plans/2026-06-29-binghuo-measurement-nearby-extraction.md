# Binghuo Measurement Nearby Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Binghuo measurement parsing prefer the nearby `三围` field so unrelated page text cannot corrupt bust, waist, and hip values.

**Architecture:** Keep the change isolated to the Binghuo scraper. Add one regression test that reproduces the noisy full-page parsing bug, then update measurement extraction to search a local `三围` snippet before falling back to broader patterns that already work today.

**Tech Stack:** Python, `unittest`, regex-based scraper parsing

---

### Task 1: Lock the Bug With a Regression Test

**Files:**
- Modify: `tests/test_binghuo_actor_scraper.py`
- Test: `tests/test_binghuo_actor_scraper.py`

- [ ] **Step 1: Write the failing test**

```python
def test_parse_profile_prefers_measurements_near_sanwei_field_over_page_noise(self):
    page = _FakePage(
        'https://www.fouroursonsinc.com/person/1867',
        '\n'.join(
            [
                'Random B001 W002 H21 noise',
                '三围：',
                '86-58-86(cm)',
            ]
        ),
    )

    profile = BinghuoActorScraper().parse_profile(page)

    self.assertEqual(profile['bust'], '86')
    self.assertEqual(profile['waist'], '58')
    self.assertEqual(profile['hip'], '86')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_binghuo_actor_scraper.py -k nearby -v`
Expected: FAIL because parser currently grabs `001`, `002`, `21` from unrelated page text first.

### Task 2: Narrow Measurement Extraction

**Files:**
- Modify: `app/scraper/binghuo_actor_scraper.py`
- Test: `tests/test_binghuo_actor_scraper.py`

- [ ] **Step 1: Write minimal implementation**

```python
def _extract_measurements(text):
    candidate_texts = _measurement_candidate_texts(text)
    for candidate_text in candidate_texts:
        explicit_measurements = {
            'bust': _extract_measurement(candidate_text, 'B'),
            'waist': _extract_measurement(candidate_text, 'W'),
            'hip': _extract_measurement(candidate_text, 'H'),
        }
        if any(explicit_measurements.values()):
            return explicit_measurements

        match = re.search(..., candidate_text, re.IGNORECASE)
        if match:
            ...
    return {'bust': '', 'waist': '', 'hip': ''}
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python -m pytest tests/test_binghuo_actor_scraper.py -k nearby -v`
Expected: PASS

### Task 3: Run Focused Regression Coverage

**Files:**
- Test: `tests/test_binghuo_actor_scraper.py`
- Test: `tests/test_actor_binghuo_enrichment_service.py`
- Test: `tests/test_actor_detail_viewer.py`

- [ ] **Step 1: Run focused verification**

Run: `python -m pytest tests/test_binghuo_actor_scraper.py tests/test_actor_binghuo_enrichment_service.py tests/test_actor_detail_viewer.py -v`
Expected: PASS with no new failures
