const fs = require("node:fs");
const path = require("node:path");

const acceptancePath = path.join(
  process.cwd(),
  "docs",
  "acceptance",
  "60_acceptance_matrix.md"
);
const testResultsPath = path.join(process.cwd(), "artifacts", "test-results.json");
const checkpointPath = path.join(process.cwd(), "artifacts", "CHECKPOINT_ACC60.md");

function extractAcIds(markdown) {
  const ids = [];
  const seen = new Set();
  const lines = markdown.split(/\r?\n/);
  for (const line of lines) {
    const match = line.match(/\|\s*(AC-\d+)\s*\|/);
    if (!match) {
      continue;
    }
    const id = match[1];
    if (!seen.has(id)) {
      seen.add(id);
      ids.push(id);
    }
  }
  return ids;
}

function loadTestCoverage() {
  if (!fs.existsSync(testResultsPath)) {
    return {
      acCoverage: new Map(),
      v2Coverage: new Map(),
    };
  }

  const json = JSON.parse(fs.readFileSync(testResultsPath, "utf8"));
  const acCoverage = new Map();
  const v2Coverage = new Map();
  for (const result of json.results || []) {
    const acMatch = result.name.match(/\b(AC-\d+)\b/);
    if (acMatch) {
      acCoverage.set(acMatch[1], {
        status: result.status,
        evidence: result.evidence || "scripts/run-tests.js",
        note: result.status === "PASS" ? "Automated check passed" : result.error || "Automated check failed",
      });
    }

    const v2Match = result.name.match(/\b(V2-\d+)\b/);
    if (v2Match) {
      v2Coverage.set(v2Match[1], {
        status: result.status,
        evidence: result.evidence || "scripts/run-tests.js",
        note: result.status === "PASS" ? "Automated check passed" : result.error || "Automated check failed",
      });
    }
  }
  return {
    acCoverage,
    v2Coverage,
  };
}

function toRow(cols) {
  return `| ${cols.join(" | ")} |`;
}

function main() {
  const acceptance = fs.readFileSync(acceptancePath, "utf8");
  const acIds = extractAcIds(acceptance);
  const coverage = loadTestCoverage();

  const rows = [];
  let pass = 0;
  let fail = 0;

  for (const acId of acIds) {
    const item = coverage.acCoverage.get(acId);
    if (item) {
      const status = item.status === "PASS" ? "PASS" : "FAIL";
      if (status === "PASS") {
        pass += 1;
      } else {
        fail += 1;
      }
      rows.push(
        toRow([
          acId,
          status,
          item.evidence,
          item.note.replace(/\|/g, "/"),
        ])
      );
      continue;
    }

    fail += 1;
    rows.push(
      toRow([
        acId,
        "FAIL",
        "none",
        "No automated evidence in this backend checkpoint",
      ])
    );
  }

  const v2Ids = Array.from(coverage.v2Coverage.keys()).sort();
  const v2Rows = [];
  let v2Pass = 0;
  let v2Fail = 0;
  for (const v2Id of v2Ids) {
    const item = coverage.v2Coverage.get(v2Id);
    const status = item.status === "PASS" ? "PASS" : "FAIL";
    if (status === "PASS") {
      v2Pass += 1;
    } else {
      v2Fail += 1;
    }
    v2Rows.push(
      toRow([
        v2Id,
        status,
        item.evidence,
        item.note.replace(/\|/g, "/"),
      ])
    );
  }

  const output = [
    "# ACC-60 Checkpoint Report",
    "",
    `Generated: ${new Date().toISOString()}`,
    "",
    `Summary: ${pass} PASS / ${fail} FAIL / ${pass + fail} TOTAL`,
    "",
    toRow(["AC_ID", "Status", "Evidence Artifact", "Note"]),
    toRow(["---", "---", "---", "---"]),
    ...rows,
    "",
    "# v0.2 Conversion Loop Checkpoint",
    "",
    `Summary: ${v2Pass} PASS / ${v2Fail} FAIL / ${v2Pass + v2Fail} TOTAL`,
    "",
    toRow(["V2_ID", "Status", "Evidence Artifact", "Note"]),
    toRow(["---", "---", "---", "---"]),
    ...(v2Rows.length > 0
      ? v2Rows
      : [
          toRow([
            "none",
            "FAIL",
            "none",
            "No v0.2 evidence in test-results.json",
          ]),
        ]),
    "",
  ].join("\n");

  fs.mkdirSync(path.dirname(checkpointPath), { recursive: true });
  fs.writeFileSync(checkpointPath, output, "utf8");
  process.stdout.write(output);
}

main();
