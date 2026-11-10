const test = require("node:test");
const assert = require("node:assert/strict");
const { findFinishedJobs } = require("../backend/static/watch-logic.js");

const job = (id) => ({ job_id: id, name: `job-${id}`, state: "RUNNING" });

test("a watched job missing from the queue is reported as finished", () => {
  const watched = { "100": { name: "train-a" } };
  const result = findFinishedJobs(watched, { jobs: [job("200")], error: null });
  assert.deepEqual(result, [{ id: "100", name: "train-a" }]);
});

test("a watched job still in the queue is not reported", () => {
  const watched = { "100": { name: "train-a" } };
  const result = findFinishedJobs(watched, { jobs: [job("100")], error: null });
  assert.deepEqual(result, []);
});

test("jobs that are not watched never produce a notification", () => {
  const result = findFinishedJobs({}, { jobs: [], error: null });
  assert.deepEqual(result, []);
});

test("a poll with an error reports nothing, even if the job list is empty", () => {
  const watched = { "100": { name: "train-a" } };
  const result = findFinishedJobs(watched, { jobs: [], error: "ssh timed out" });
  assert.deepEqual(result, []);
});

test("only the watched jobs that vanished are reported", () => {
  const watched = { "100": { name: "a" }, "101": { name: "b" }, "102": { name: "c" } };
  const result = findFinishedJobs(watched, { jobs: [job("101")], error: null });
  assert.deepEqual(result, [
    { id: "100", name: "a" },
    { id: "102", name: "c" },
  ]);
});
