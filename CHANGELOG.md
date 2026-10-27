## v0.8.1 (2026-10-27)

### Fix

- sanitize the LLM-returned vendor before it hits the filename

## v0.8.0 (2026-10-27)

### Feat

- add OpenAI-based receipt categorization and fix EXIF rotation in OCR

## v0.7.3 (2026-10-23)

### Fix

- harden release.yml deploy/verify against flaky timing and reruns

## v0.7.2 (2026-10-23)

### Fix

- render booking-confirmation email bodies alongside an incidental image attachment

## v0.7.1 (2026-10-21)

### Fix

- sniff magic bytes when an attachment is mislabeled octet-stream

## v0.7.0 (2026-09-11)

### Feat

- make the HTTP upload path configurable via env

## v0.6.0 (2026-08-30)

### Feat

- build output filenames from Tesseract OCR / PDF text

## v0.5.0 (2026-08-29)

### Feat

- add HTTP upload channel for receipt photos

## v0.4.2 (2026-08-25)

### Fix

- skip redundant email-body PDF when an image/PDF attachment exists

## v0.4.1 (2026-08-24)

### Fix

- use GITHUB_TOKEN instead of PAT for release creation

## v0.4.0 (2026-08-24)

### Feat

- forward inbox mail whose subject contains [rec]

## v0.3.1 (2026-08-24)

### Fix

- bump azkees to 7.0.2
- search rec/in by label instead of selecting it as the mailbox

## v0.3.0 (2026-08-07)

### Feat

- name forwarded attachments by date, sender, amount, currency

## v0.2.1 (2026-08-07)

### Fix

- cache Chromium download independent of source changes

## v0.2.0 (2026-08-07)

### Feat

- initial Gmail receipt/invoice forwarder service
