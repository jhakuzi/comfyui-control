# Manual tests for 1.0

[Download the spreadsheet](ComfyUI-Control-1.0-Test-Plan.xlsx?raw=1) and open it
in LibreOffice Calc or Excel.

1. **Overview:** record the exact app build, ComfyUI, PC, phone and NAS setup.
2. **Tonight:** work through the real NAS, fallback, mobile gallery and recovery
   checks. Choose a Status and record what actually happened, including image
   filenames and exact errors. Run the active-generation NAS outage test last.
3. **Issues:** give each problem an ID such as `BUG-01`. Keep reproduction steps
   and screenshot/log references; record the fix build and retest result later.
4. **Before 1.0:** finish the broader regression and packaging checks. The RPM
   upgrade test needs a release candidate later; this plan does not trigger a build.

All tests start **Not run**. Use **Pass**, **Fail**, **Blocked**, or **Not applicable**
with a reason. Preserve failure notes when retesting. The summary counts results;
it does not replace a release review. Every Required check should pass, and any
conditional check not performed needs an explanation.

The workbook records the build it was prepared against. If the app changes,
update that field and record the actual build/date for each retest. It contains
no macros or external data connections. Tests and this workbook are not included
in the small app download ZIP.
