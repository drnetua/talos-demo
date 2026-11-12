# Spreadsheet safety verification record

Verifies that the export's safe text rule keeps formula-like values inert in real spreadsheet
applications. The automated tests only check the file; this record covers the applications.

## Generate the file

```
uv run python tests/spreadsheet_fixture.py fixture.csv
```

The file is produced by calling `GET /notes/export` (fields `id,title,body,tags`) through the
app. Every title and body of notes 1-8 is formula-like and must show as a leading `'` marker in
the file; note 9 (`Meeting` / `\tindented`) is a control and is unchanged.

## Import paths to try (each application)

1. Open the file directly (double-click / File > Open).
2. Import as text/CSV through the application's import wizard (UTF-8, comma separated).
3. Paste or upload into a fresh sheet (Google Sheets: File > Import > Upload).

## Pass rule

All fixture values are inert (displayed as text, not evaluated; no formula) in all three
applications. A failure means the contract rule must be revised, then fidelity and safety checks
rerun. **A missing application is a release blocker.**

## Results

| Application   | Version | Platform | Import path | Displayed value | Is formula (yes/no) |
|---------------|---------|----------|-------------|-----------------|---------------------|
| Excel         |         |          |             |                 |                     |
| Google Sheets |         |          |             |                 |                     |
| LibreOffice   |         |          |             |                 |                     |
