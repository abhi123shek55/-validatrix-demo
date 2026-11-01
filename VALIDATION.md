# Local verification

Verified with Python 3.12 and the pinned application dependencies using Flask's test client.

- Homepage and health routes respond successfully.
- Sample XML upload produces a validation table.
- Excel export opens successfully with four sample question rows.
- Invalid report payloads are rejected; formula-like labels export as plain text.
- XML comments do not crash parsing.
- Malformed XML and DTD/entity declarations are rejected.
- Oversized requests return HTTP 413.

Existing validation rules were retained. This does not verify every possible survey or replace manual survey testing.

Cloud deployment and browser layout testing have not been performed.
