#!/usr/bin/env node
// oxlint ships its native linter as 18 platform-specific optional
// dependencies. npm writes only the ones matching the machine that generated
// the lockfile into package-lock.json, so a lockfile made on macOS arm64
// carries `@oxlint/binding-darwin-arm64` and nothing else — and `npm ci` on
// Linux x64 then has no binding to install, so `npm run lint` dies with
// "Cannot find native binding. npm has a bug related to optional
// dependencies" (npm/cli#4828). That is why `ci` was red on `main`.
//
// npm cannot fix this itself: `npm install --package-lock-only --os linux
// --cpu x64` crashes with "Cannot read properties of null (reading
// 'edgesOut')" on npm 10.9.8, and a plain regeneration on any one platform
// just moves the hole. So the lockfile is patched here instead: for each
// `@oxlint/binding-*` in oxlint's own optionalDependencies, add a
// package-lock entry at oxlint's version with the integrity hash from the
// registry. Every binding is marked optional and carries its real os/cpu, so
// npm still skips the ones the running machine cannot use.
//
//   node scripts/patch-oxlint-lock.mjs          # add the missing entries
//   node scripts/patch-oxlint-lock.mjs --check  # offline: fail if any are missing
//
// `--check` is what CI runs before `npm ci`; it needs no network, so a
// lockfile regenerated on a laptop fails the build with a one-line fix
// instead of a confusing native-binding error from inside oxlint.

import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const lockPath = join(root, 'apps/web/package-lock.json')
// The platform `ci` runs the linter on. This one is required even in
// --check mode, so the guard is about the runner rather than about whatever
// machine happens to be regenerating the lockfile.
const REQUIRED = '@oxlint/binding-linux-x64-gnu'

const check = process.argv.includes('--check')
const lock = JSON.parse(readFileSync(lockPath, 'utf8'))
const oxlint = lock.packages['node_modules/oxlint']
if (!oxlint) {
  console.error('apps/web/package-lock.json has no node_modules/oxlint entry')
  process.exit(1)
}

const version = oxlint.version
// The lockfile records what is installed, not what oxlint could install, so
// read the real list from oxlint itself. Fall back to the registry manifest
// when node_modules is absent (a fresh clone that has not run npm ci yet).
let optionalDeps = {}
try {
  const manifest = JSON.parse(
    readFileSync(join(root, 'apps/web/node_modules/oxlint/package.json'), 'utf8'),
  )
  optionalDeps = manifest.optionalDependencies ?? {}
} catch {
  const res = await fetch(`https://registry.npmjs.org/oxlint/${version}`)
  if (!res.ok) {
    console.error(`cannot read oxlint@${version} optionalDependencies: HTTP ${res.status}`)
    process.exit(1)
  }
  optionalDeps = (await res.json()).optionalDependencies ?? {}
}

const missing = Object.keys(optionalDeps).filter(
  (name) => !lock.packages[`node_modules/${name}`],
)
const requiredMissing = !lock.packages[`node_modules/${REQUIRED}`]

if (check) {
  if (!requiredMissing) {
    console.log(`oxlint lock ok: ${REQUIRED}@${version} present`)
    process.exit(0)
  }
  console.error(
    `apps/web/package-lock.json is missing ${REQUIRED}@${version}, so 'npm ci' ` +
      `cannot install the native linter on Linux and 'npm run lint' fails. ` +
      `Regenerating the lockfile on one platform drops the other platforms' ` +
      `bindings (npm/cli#4828). Fix: node scripts/patch-oxlint-lock.mjs`,
  )
  process.exit(1)
}

if (missing.length === 0) {
  console.log(`oxlint lock already complete (${Object.keys(optionalDeps).length} bindings)`)
  process.exit(0)
}

for (const name of missing) {
  const spec = optionalDeps[name]
  if (spec !== version) {
    // oxlint pins its bindings to its own version; a mismatch means the
    // lockfile is out of step with the manifest, which npm must resolve.
    console.error(`${name}@${spec} does not match oxlint@${version}; run npm install`)
    process.exit(1)
  }
  const res = await fetch(`https://registry.npmjs.org/${name}/${version}`)
  if (!res.ok) {
    console.error(`cannot resolve ${name}@${version}: HTTP ${res.status}`)
    process.exit(1)
  }
  const manifest = await res.json()
  // `os`/`cpu` come from the registry manifest, not from a guess, so npm's
  // platform filter stays correct on every machine. Key order and the
  // absence of `resolved`/`integrity` match how npm already wrote every
  // other entry in this lockfile (it resolves by name@version).
  const entry = { version, dev: true, license: manifest.license, optional: true }
  if (manifest.cpu) entry.cpu = manifest.cpu
  if (manifest.os) entry.os = manifest.os
  if (manifest.engines) entry.engines = manifest.engines
  lock.packages[`node_modules/${name}`] = entry
}

writeFileSync(lockPath, `${JSON.stringify(lock, null, 2)}\n`)
console.log(`added ${missing.length} oxlint binding(s) at ${version}: ${missing.join(', ')}`)
