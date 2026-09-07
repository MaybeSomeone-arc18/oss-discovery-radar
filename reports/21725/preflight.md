# Preflight Report: AnkiDroid #21725

## 1. LIVE ISSUE VERIFICATION
- **Repository**: `ankidroid/Anki-Android`
- **Issue Number**: #21725
- **Title**: Opening a valid .apkg from Telegram, WhatsApp fails with a UTF-8 error; text/plain Intent selects CSV import
- **Status**: OPEN
- **Description**: Users are unable to import `.apkg` files directly from messaging apps like Telegram or WhatsApp on Android because it opens as `text/plain` or triggers a UTF-8 error, selecting CSV import instead of the proper Anki package importer.
- **Labels**: `Needs Triage`

## 2. PR / COMMIT CONFLICT CHECK
- **Open PRs referencing #21725**: 0
- **Closed/Merged PRs referencing #21725**: 0
- **Branch/Commit Mentions**: None found on GitHub search
- **Status**: `ACTIVE_UNADDRESSED` - There are absolutely no known active development efforts for this specific intent bug.

## 3. DUPLICATE / RELATED ISSUE CHECK
- **Related Issues**: Import/Intent related issues occasionally pop up in AnkiDroid, but this specific bug (falling back to CSV for `.apkg` from Telegram/WhatsApp due to content-type misattribution) is unique and explicitly reproducible in the current version.

## 4. REPOSITORY CONTRIBUTION MODEL
- **External Contributors**: AnkiDroid actively encourages and accepts external contributions.
- **Review Behavior**: Maintainers are highly active, thorough in code reviews, and emphasize testing and stability.
- **Newcomer Friendliness**: Yes, they have a solid `CONTRIBUTING.md` and standard Android build instructions. They expect reproducible bugs and clean commits.

## 5. TECHNICAL AREA
- **Domain**: Android Intents, Content Providers, and MIME-type handling.
- **Code Scope**: `IntentHandler.java` or `DeckPicker.java` (specifically how it handles `ACTION_VIEW` and `ACTION_SEND` intents with `content://` URIs).

## 6. ENGINEERING DEPTH
- **Medium**. It requires understanding Android Intent filters and how third-party apps (like Telegram) broadcast file types. The fix is likely scoped to a few lines of intent parsing or manifest XML updates, but testing it will be tricky.

## 7. PERSONAL FIT
- **Score**: 33.1 (Strong match for Android UI/System engineering skills).

## 8. GSoC PREPARATION VALUE
- **High**. Fixing a core Android system integration bug (Intents) is excellent evidence of deep Android platform understanding, which is highly valued by organizations like AnkiDroid for GSoC.

## 9. CONTRIBUTION RISK
- **Low to Medium**. The biggest risk is testing the fix across different Android versions (Scoped Storage changes). There is zero conflict risk with other contributors.

## 10. AI-POLICY STATUS
- **Policy**: AnkiDroid expects human-verified, high-quality code. Raw AI dumps are generally discouraged across OSS, so any AI-assisted code must be manually reviewed, fully tested, and formatted perfectly to match their style.

## 11. FINAL ELIGIBILITY DECISION
- **Decision**: `STRONG_CANDIDATE`
- **Reasoning**: This issue has a clear scope, zero competing PRs, high value for Android experience, and addresses a very annoying usability bug.

---

## Comparison Table

| Rank | Issue  | Org       | C-Val | GSoC | Fit  | Depth  | Maintainer | Conflict Risk | Confidence |
|------|--------|-----------|-------|------|------|--------|------------|---------------|------------|
| 1    | #21725 | ankidroid | High  | High | 33.1 | Medium | Active     | **Zero**      | High       |
| 2    | #21135 | ankidroid | Med   | Med  | 35.0 | High   | Active     | Zero          | Med        |
| 3    | #19749 | ankidroid | High  | High | 34.9 | High   | Active     | Zero          | Low        |
| 4    | #19678 | ankidroid | Med   | Low  | 39.6 | Low    | Active     | High (1 PR)   | Med        |
| 5    | #18358 | ankidroid | Med   | Low  | 35.2 | Low    | Active     | High (2 PRs)  | Med        |
| 6    | #13283 | ankidroid | Low   | Low  | 46.2 | Low    | Active     | High (30 PRs) | Med        |
