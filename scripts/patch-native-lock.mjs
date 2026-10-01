#!/usr/bin/env node
// Several packages in apps/web ship their real work as platform-specific
// optional dependencies. npm writes only the ones matching the machine that
// generated package-lock.json, so a lockfile made on macOS arm64 records
// `@oxlint/binding-darwin-arm64` and nothing else — and `npm ci` on the Linux
// runner then has nothing to install. The failure surfaces inside the package
// as "Cannot find native binding. npm has a bug related to optional
// dependencies" (npm/cli#4828), which reads like a broken toolchain rather
// than a lockfile problem.
//
// This bit oxlint (`npm run lint`), then rolldown (`npm run build`), and
// @tailwindcss/oxide and lightningcss were next in line. npm cannot fix it
// itself: `npm install --package-lock-only --os linux --cpu x64` crashes with
// "Cannot read properties of null (reading 'edgesOut')" on npm 10.9.8, and a
// plain regeneration on any one platform just moves the hole. So the lockfile
// is patched here instead: for each native package, add a package-lock entry
// for every optional dependency it declares, at its own pinned version, with
// the `os`/`cpu` the registry reports. Every entry stays `optional`, so npm
// still skips the ones the running machine cannot use.
//
//   node scripts/patch-native-lock.mjs          # add the missing entries
//   node scripts/patch-native-lock.mjs --check  # offline: fail if any are missing
//
// `--check` runs in CI before `npm ci`. It needs no network, and it fails with
// the one-line fix, so a lockfile regenerated on a laptop can no longer reach
// the runner broken.

import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const webDir = join(root, 'apps/web')
const lockPath = join(webDir, 'package-lock.json')

// Packages whose work is a native binary, so each drags in one optional
// dependency per platform. `--check` asserts the Linux x64 glibc binding of
// each, which is what ubuntu-latest needs.
//
// Matching is by the lockfile path *suffix*, so a nested copy is found too:
// `@tailwindcss/node` carries its own lightningcss 1.32.0 alongside the
// top-level 1.33.0, and both need their bindings.
//
// Adding a dependency that ships a native binary means adding it here too —
// otherwise `--check` cannot see it. Patch mode warns about any installed
// package with per-platform optional dependencies that is not listed, so a new
// one surfaces rather than waiting to fail the build.
const NATIVE_PACKAGES = [
  'oxlint',
  'rolldown',
  '@tailwindcss/oxide',
  'lightningcss',
  '@tailwindcss/node/node_modules/lightningcss',
]

// The binding ubuntu-latest (x86_64 glibc) needs. Used by --check and named in
// its failure message.
const RUNNER_BINDING = 'linux-x64-gnu'

const check = process.argv.includes('--check')
const lock = JSON.parse(readFileSync(lockPath, 'utf8'))

/** The manifest of an installed package, or null when node_modules is absent. */
function installedManifest(name) {
  const path = join(webDir, 'node_modules', ...name.split('/'), 'package.json')
  return existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) : null
}

/**
 * Read a package's pinned version and optional dependencies.
 *
 * The version always comes from the lockfile, never from node_modules: the
 * tree can be ahead of the lockfile (a local `npm install` without a lockfile
 * update), and `npm ci` installs the lockfile's version. Reading the installed
 * copy put 1.33.0 bindings in a lockfile that pins lightningcss 1.32.0
 * somewhere else in the tree, and `npm ci` then rejected the file outright
 * ("Missing: lightningcss-linux-x64-gnu@1.32.0 from lock file"). The
 * optionalDependencies list comes from the registry for that same version,
 * which is what npm will resolve.
 */
async function optionalDepsOf(lockPath) {
  const entry = lock.packages[`node_modules/${lockPath}`]
  if (!entry) {
    throw new Error(
      `${lockPath} is listed in NATIVE_PACKAGES but is not in the lockfile. ` +
        `Drop it from the list if it no longer ships a native binary.`,
    )
  }
  // A nested entry's registry name is the part after the last node_modules/,
  // not the path: `@tailwindcss/node/node_modules/lightningcss` is plain
  // `lightningcss` on the registry.
  const registryName = lockPath.split('node_modules/').pop()
  const res = await fetch(`https://registry.npmjs.org/${registryName}/${entry.version}`)
  if (!res.ok) {
    throw new Error(`cannot read ${registryName}@${entry.version}: HTTP ${res.status}`)
  }
  const meta = await res.json()
  return { version: entry.version, optionalDependencies: meta.optionalDependencies ?? {} }
}

if (check) {
  const missing = []
  for (const name of NATIVE_PACKAGES) {
    const entry = lock.packages[`node_modules/${name}`]
    if (!entry) {
      missing.push(`${name} — not in the lockfile at all`)
      continue
    }
    // Binding names are built differently per package (`@oxlint/binding-…`,
    // `lightningcss-…`), so match the platform suffix plus the package's own
    // last name segment. A nested package's binding sits under the same
    // nested path, so the prefix is matched too — otherwise the root copy
    // would satisfy the check for the nested one.
    const segment = name.split('/').pop()
    const prefix = name.includes('/node_modules/') ? `node_modules/${name}/node_modules/` : 'node_modules/'
    const has = Object.keys(lock.packages).some(
      (key) => key.startsWith(prefix) && key.endsWith(RUNNER_BINDING) && key.includes(segment),
    )
    if (!has) missing.push(`${name}@${entry.version} — no ${RUNNER_BINDING} binding`)
  }
  if (missing.length === 0) {
    console.log(
      `native lock ok: all ${NATIVE_PACKAGES.length} native packages carry a ${RUNNER_BINDING} binding`,
    )
    process.exit(0)
  }
  console.error(
    'apps/web/package-lock.json is missing a Linux binding for:\n' +
      missing.map((m) => `  - ${m}`).join('\n') +
      '\n\n' +
      "'npm ci' therefore cannot install the native binaries on the runner, and 'npm run lint' " +
      "and 'npm run build' die with \"Cannot find native binding\". Regenerating the lockfile on " +
      'one platform drops the other platforms\' bindings (npm/cli#4828).\n' +
      'Fix: node scripts/patch-native-lock.mjs',
  )
  process.exit(1)
}

let added = 0
for (const name of NATIVE_PACKAGES) {
  const { version, optionalDependencies } = await optionalDepsOf(name)
  for (const [dep, spec] of Object.entries(optionalDependencies)) {
    // Where npm would put it. A top-level package hoists its bindings to the
    // root; a nested one gets them under its own path, because the root slot
    // is already taken by the other version. This is not a detail: the tree
    // holds lightningcss 1.33.0 at the root and 1.32.0 under
    // @tailwindcss/node, and each needs its own version's binding. Writing both
    // at the root leaves `npm ci` rejecting the file with "Missing:
    // lightningcss-linux-x64-gnu@1.32.0 from lock file".
    const installPath = name.includes('/node_modules/')
      ? `node_modules/${name}/node_modules/${dep}`
      : `node_modules/${dep}`
    if (lock.packages[installPath]) continue
    if (spec !== version) {
      throw new Error(
        `${dep}@${spec} does not match ${name}@${version}; run npm install rather than patching`,
      )
    }
    const res = await fetch(`https://registry.npmjs.org/${dep}/${version}`)
    if (!res.ok) throw new Error(`cannot resolve ${dep}@${version}: HTTP ${res.status}`)
    const meta = await res.json()
    // Key order, and the absence of `resolved`/`integrity`, match how npm
    // already wrote the rest of this lockfile: it resolves by name@version.
    const entry = { version, dev: true, license: meta.license, optional: true }
    if (meta.cpu) entry.cpu = meta.cpu
    if (meta.os) entry.os = meta.os
    if (meta.engines) entry.engines = meta.engines
    lock.packages[installPath] = entry
    added += 1
  }
}

if (added > 0) writeFileSync(lockPath, `${JSON.stringify(lock, null, 2)}\n`)
console.log(`added ${added} native binding entr${added === 1 ? 'y' : 'ies'} to package-lock.json`)

// A newly added native dependency would be invisible to --check, so say so out
// loud rather than letting it fail the build later.
const unlisted = findUnlistedNativePackages()
if (unlisted.length > 0) {
  console.warn(
    'warning: these installed packages also ship per-platform optional dependencies but are ' +
      `not in NATIVE_PACKAGES, so --check cannot verify them: ${unlisted.sort().join(', ')}`,
  )
}

/** Installed packages with per-platform optional deps that NATIVE_PACKAGES misses. */
function findUnlistedNativePackages() {
  const modulesDir = join(webDir, 'node_modules')
  if (!existsSync(modulesDir)) return []
  const listed = new Set(NATIVE_PACKAGES)
  const found = new Set()
  const platformish = /darwin|linux|win32|wasm32|android|freebsd|s390x|riscv/
  for (const scope of readdirSync(modulesDir, { withFileTypes: true })) {
    // Skip the binding packages themselves; only their parents matter.
    if (scope.name.startsWith('.')) continue
    if (!scope.isDirectory() && !scope.isSymbolicLink()) continue
    if (scope.name.startsWith('@')) {
      for (const inner of readdirSync(join(modulesDir, scope.name), { withFileTypes: true })) {
        inspect(`${scope.name}/${inner.name}`, found, listed, platformish)
      }
    } else {
      inspect(scope.name, found, listed, platformish)
    }
  }
  return [...found]
}

function inspect(name, found, listed, platformish) {
  const manifest = installedManifest(name)
  if (!manifest) return
  const optional = Object.keys(manifest.optionalDependencies ?? {})
  if (optional.length > 1 && optional.some((dep) => platformish.test(dep)) && !listed.has(name)) {
    found.add(name)
  }
}