window.AuthorStudioV5Patch = (function buildPatchHelpers() {
  function cloneJson(input) {
    return JSON.parse(JSON.stringify(input));
  }

  function parsePath(path) {
    const tokens = [];
    const regex = /([^.[\]]+)|\[(\d+)\]/g;
    let match;
    while ((match = regex.exec(path)) !== null) {
      if (match[1] !== undefined) tokens.push(match[1]);
      if (match[2] !== undefined) tokens.push(Number(match[2]));
    }
    return tokens;
  }

  function setByPath(target, path, value) {
    const tokens = parsePath(path);
    if (!tokens.length) return;
    let current = target;
    for (let i = 0; i < tokens.length - 1; i += 1) {
      const key = tokens[i];
      const nextKey = tokens[i + 1];
      if (current[key] === undefined || current[key] === null) {
        current[key] = typeof nextKey === "number" ? [] : {};
      }
      current = current[key];
    }
    current[tokens[tokens.length - 1]] = cloneJson(value);
  }

  return {
    cloneJson,
    parsePath,
    setByPath,
  };
})();
