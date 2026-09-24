import { execFileSync } from 'node:child_process'

import { repoRoot } from './seed'

export function grantAdmin(email: string): void {
  if (!/^[^@\s]+@[^@\s]+$/.test(email)) throw new Error('invalid test email')
  const safeEmail = email.replaceAll("'", "''")
  execFileSync(
    'docker',
    [
      'compose',
      'exec',
      '-T',
      'db',
      'psql',
      '-U',
      'veriforge',
      '-d',
      'veriforge',
      '-c',
      `update users set role='admin' where email='${safeEmail}';`,
    ],
    { cwd: repoRoot, encoding: 'utf8' },
  )
}

export function revokeAdmin(email: string): void {
  if (!/^[^@\s]+@[^@\s]+$/.test(email)) throw new Error('invalid test email')
  const safeEmail = email.replaceAll("'", "''")
  execFileSync(
    'docker',
    [
      'compose',
      'exec',
      '-T',
      'db',
      'psql',
      '-U',
      'veriforge',
      '-d',
      'veriforge',
      '-c',
      `update users set role='user' where email='${safeEmail}';`,
    ],
    { cwd: repoRoot, encoding: 'utf8' },
  )
}
