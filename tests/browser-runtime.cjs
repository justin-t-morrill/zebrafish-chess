// Shared local browser-test prerequisites; overrides also work in a fresh checkout.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const cached = path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies');
let playwright;
if (process.env.ZEBRAFISH_PLAYWRIGHT) {
  playwright = require(process.env.ZEBRAFISH_PLAYWRIGHT);
} else {
  try { playwright = require('playwright'); }
  catch { playwright = require(path.join(cached, 'node/node_modules/playwright')); }
}
const candidates = [
  path.join(root, '.venv/Scripts/python.exe'),
  path.join(root, '.venv/bin/python'),
  path.join(cached, 'python/python.exe'),
];
const python = process.env.ZEBRAFISH_PYTHON || candidates.find(file => fs.existsSync(file)) ||
  (process.platform === 'win32' ? 'python.exe' : 'python3');
module.exports = {playwright, python};
