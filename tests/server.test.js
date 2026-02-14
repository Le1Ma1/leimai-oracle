const test = require("node:test");
const assert = require("node:assert/strict");

const { createAppServer } = require("../src/server");
const { hasLockedData } = require("../src/denylist");

async function withServer(fn) {
  const server = createAppServer();
  await new Promise((resolve) => server.listen(0, resolve));
  const address = server.address();
  const baseUrl = `http://127.0.0.1:${address.port}`;

  try {
    await fn(baseUrl);
  } finally {
    await new Promise((resolve, reject) => {
      server.close((err) => (err ? reject(err) : resolve()));
    });
  }
}

test("public endpoints exist and respond", async () => {
  await withServer(async (baseUrl) => {
    const rankingRes = await fetch(`${baseUrl}/rankings`);
    const rankingJson = await rankingRes.json();
    assert.equal(rankingRes.status, 200);
    assert.equal(hasLockedData(rankingJson), false);

    const summariesRes = await fetch(`${baseUrl}/summaries`);
    assert.equal(summariesRes.status, 200);

    const methodologyRes = await fetch(`${baseUrl}/methodology`);
    assert.equal(methodologyRes.status, 200);
  });
});

test("private-scope requests require auth and use safe error envelope", async () => {
  await withServer(async (baseUrl) => {
    const res = await fetch(`${baseUrl}/rankings?scope=private`);
    const json = await res.json();
    assert.equal(res.status, 401);
    assert.deepEqual(Object.keys(json).sort(), [
      "error_code",
      "message",
      "request_id",
      "timestamp",
    ]);
    assert.equal(hasLockedData(json), false);
  });
});
