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
      v3Coverage: new Map(),
      v4Coverage: new Map(),
      v5Coverage: new Map(),
      v6Coverage: new Map(),
    };
  }

  const json = JSON.parse(fs.readFileSync(testResultsPath, "utf8"));
  const acCoverage = new Map();
  const v2Coverage = new Map();
  const v3Coverage = new Map();
  const v4Coverage = new Map();
  const v5Coverage = new Map();
  const v6Coverage = new Map();
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

    const v3Match = result.name.match(/\b(V3-\d+)\b/);
    if (v3Match) {
      v3Coverage.set(v3Match[1], {
        status: result.status,
        evidence: result.evidence || "scripts/run-tests.js",
        note: result.status === "PASS" ? "Automated check passed" : result.error || "Automated check failed",
      });
    }

    const v4Match = result.name.match(/\b(V4-\d+)\b/);
    if (v4Match) {
      v4Coverage.set(v4Match[1], {
        status: result.status,
        evidence: result.evidence || "scripts/run-tests.js",
        note: result.status === "PASS" ? "Automated check passed" : result.error || "Automated check failed",
      });
    }

    const v5Match = result.name.match(/\b(V5-\d+)\b/);
    if (v5Match) {
      v5Coverage.set(v5Match[1], {
        status: result.status,
        evidence: result.evidence || "scripts/run-tests.js",
        note: result.status === "PASS" ? "Automated check passed" : result.error || "Automated check failed",
      });
    }

    const v6Match = result.name.match(/\b(V6-\d+)\b/);
    if (v6Match) {
      v6Coverage.set(v6Match[1], {
        status: result.status,
        evidence: result.evidence || "scripts/run-tests.js",
        note: result.status === "PASS" ? "Automated check passed" : result.error || "Automated check failed",
      });
    }
  }
  return {
    acCoverage,
    v2Coverage,
    v3Coverage,
    v4Coverage,
    v5Coverage,
    v6Coverage,
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

  const v3Ids = Array.from(coverage.v3Coverage.keys()).sort();
  const v3Rows = [];
  let v3Pass = 0;
  let v3Fail = 0;
  for (const v3Id of v3Ids) {
    const item = coverage.v3Coverage.get(v3Id);
    const status = item.status === "PASS" ? "PASS" : "FAIL";
    if (status === "PASS") {
      v3Pass += 1;
    } else {
      v3Fail += 1;
    }
    v3Rows.push(
      toRow([
        v3Id,
        status,
        item.evidence,
        item.note.replace(/\|/g, "/"),
      ])
    );
  }

  const v4Ids = Array.from(coverage.v4Coverage.keys()).sort();
  const v4Rows = [];
  let v4Pass = 0;
  let v4Fail = 0;
  for (const v4Id of v4Ids) {
    const item = coverage.v4Coverage.get(v4Id);
    const status = item.status === "PASS" ? "PASS" : "FAIL";
    if (status === "PASS") {
      v4Pass += 1;
    } else {
      v4Fail += 1;
    }
    v4Rows.push(
      toRow([
        v4Id,
        status,
        item.evidence,
        item.note.replace(/\|/g, "/"),
      ])
    );
  }

  const v5Ids = Array.from(coverage.v5Coverage.keys()).sort();
  const v5Rows = [];
  let v5Pass = 0;
  let v5Fail = 0;
  for (const v5Id of v5Ids) {
    const item = coverage.v5Coverage.get(v5Id);
    const status = item.status === "PASS" ? "PASS" : "FAIL";
    if (status === "PASS") {
      v5Pass += 1;
    } else {
      v5Fail += 1;
    }
    v5Rows.push(
      toRow([
        v5Id,
        status,
        item.evidence,
        item.note.replace(/\|/g, "/"),
      ])
    );
  }

  const v6Ids = Array.from(coverage.v6Coverage.keys()).sort();
  const v6Rows = [];
  let v6Pass = 0;
  let v6Fail = 0;
  for (const v6Id of v6Ids) {
    const item = coverage.v6Coverage.get(v6Id);
    const status = item.status === "PASS" ? "PASS" : "FAIL";
    if (status === "PASS") {
      v6Pass += 1;
    } else {
      v6Fail += 1;
    }
    v6Rows.push(
      toRow([
        v6Id,
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
    "# v0.3 Hardening Checkpoint",
    "",
    `Summary: ${v3Pass} PASS / ${v3Fail} FAIL / ${v3Pass + v3Fail} TOTAL`,
    "",
    toRow(["V3_ID", "Status", "Evidence Artifact", "Note"]),
    toRow(["---", "---", "---", "---"]),
    ...(v3Rows.length > 0
      ? v3Rows
      : [
          toRow([
            "none",
            "FAIL",
            "none",
            "No v0.3 evidence in test-results.json",
          ]),
        ]),
    "",
    "# v0.4 Chain-Reconcile Checkpoint",
    "",
    `Summary: ${v4Pass} PASS / ${v4Fail} FAIL / ${v4Pass + v4Fail} TOTAL`,
    "",
    toRow(["V4_ID", "Status", "Evidence Artifact", "Note"]),
    toRow(["---", "---", "---", "---"]),
    ...(v4Rows.length > 0
      ? v4Rows
      : [
          toRow([
            "none",
            "FAIL",
            "none",
            "No v0.4 evidence in test-results.json",
          ]),
        ]),
    "",
    "# v0.5 RPC Mode Checkpoint",
    "",
    `Summary: ${v5Pass} PASS / ${v5Fail} FAIL / ${v5Pass + v5Fail} TOTAL`,
    "",
    toRow(["V5_ID", "Status", "Evidence Artifact", "Note"]),
    toRow(["---", "---", "---", "---"]),
    ...(v5Rows.length > 0
      ? v5Rows
      : [
          toRow([
            "none",
            "FAIL",
            "none",
            "No v0.5 evidence in test-results.json",
          ]),
        ]),
    "",
    "# v0.6 RPC Hardening Checkpoint",
    "",
    `Summary: ${v6Pass} PASS / ${v6Fail} FAIL / ${v6Pass + v6Fail} TOTAL`,
    "",
    toRow(["V6_ID", "Status", "Evidence Artifact", "Note"]),
    toRow(["---", "---", "---", "---"]),
    ...(v6Rows.length > 0
      ? v6Rows
      : [
          toRow([
            "none",
            "FAIL",
            "none",
            "No v0.6 evidence in test-results.json",
          ]),
        ]),
    "",
  ].join("\n");

  fs.mkdirSync(path.dirname(checkpointPath), { recursive: true });
  fs.writeFileSync(checkpointPath, output, "utf8");
  process.stdout.write(output);
}

main();
