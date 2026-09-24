import { randomUUID } from 'node:crypto'
import path from 'node:path'

export const TEST_PASSWORD = 'VeriforgeE2E-password-42!'

export interface TestUser {
  email: string
  password: string
}

export function makeTestUser(domain = process.env.VERIFORGE_TEST_EMAIL_DOMAIN ?? 'veriforge.test'): TestUser {
  return {
    email: `test-user-${randomUUID()}@${domain}`,
    password: TEST_PASSWORD,
  }
}

export const repoRoot = path.resolve(process.cwd(), '..', '..')
export const docentUploadRoot =
  process.env.DOCENT_UPLOAD_ROOT ?? path.resolve(repoRoot, '..', 'docent', 'data', 'local-uploads')

export const docentFixtures = {
  pdf: path.join(
    docentUploadRoot,
    'fbaeb29b-0d97-430e-89f4-791622a11bb3',
    'AI_Engineering_Crash_Course.pdf',
  ),
  jekyll: path.join(
    docentUploadRoot,
    '12f55658-cc7e-4b36-8273-a21b6d6aced4',
    'cas-etrange-du-docteur-jekyll-76412.txt',
  ),
  faust: path.join(
    docentUploadRoot,
    'b1f70809-2456-4709-905a-d7477252fc8b',
    'faust-erster-teil-2229.txt',
  ),
}
