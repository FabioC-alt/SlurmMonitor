// Pure logic for "notify me when this job finishes". squeue only lists live
// jobs, so a watched job counts as finished once it is absent from a
// successful poll. Loaded as a plain script in the browser (global
// WatchLogic) and via require() in tests.
(function (root) {
  function findFinishedJobs(watched, data) {
    if (!data || data.error || !Array.isArray(data.jobs)) return [];
    const live = new Set(data.jobs.map((j) => j.job_id));
    return Object.keys(watched)
      .filter((id) => !live.has(id))
      .map((id) => ({ id, name: watched[id].name }));
  }

  const api = { findFinishedJobs };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.WatchLogic = api;
})(typeof window !== "undefined" ? window : this);
