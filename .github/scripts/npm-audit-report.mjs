// Summarize `npm audit --json` output, distinguishing findings from failures.
//
// Exit 0 with a summary line when the report is valid (warning annotation if
// high/critical advisories exist); exit 2 when npm produced no usable report
// (registry outage, missing lockfile, CLI error), so CI fails loudly instead
// of reporting an empty warning.
import { readFileSync, writeFileSync } from "node:fs";

const [reportPath, summaryPath, bead] = process.argv.slice(2);

function fail(message) {
  console.error(`::error title=Mobile npm audit::${message}`);
  process.exit(2);
}

let report;
try {
  report = JSON.parse(readFileSync(reportPath, "utf8"));
} catch {
  fail("npm audit produced no JSON report");
}
if (report.error) {
  fail(`npm audit failed: ${report.error.summary || report.error.code || "unknown error"}`);
}
const counts = report.metadata?.vulnerabilities;
if (!counts || typeof counts.total !== "number") {
  fail("npm audit report lacks metadata.vulnerabilities");
}

const line =
  `${counts.total} vulnerabilities (critical ${counts.critical ?? 0}, high ${counts.high ?? 0}, ` +
  `moderate ${counts.moderate ?? 0}, low ${counts.low ?? 0})`;
writeFileSync(summaryPath, `${line}\n`);
if ((counts.critical ?? 0) + (counts.high ?? 0) > 0) {
  console.log(`::warning title=Mobile npm audit::${line} - see ${bead}`);
} else {
  console.log(line);
}
