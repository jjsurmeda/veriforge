#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { AppStack } from '../lib/stacks/app';
import { BudgetStack } from '../lib/stacks/budget';
import { EdgeStack } from '../lib/stacks/edge';
import { PersistStack } from '../lib/stacks/persist';

const app = new cdk.App();

// Region is fixed rather than read from the environment: every prefix list id
// and the SNS topic are region-specific, and a deployment that quietly lands in
// the wrong region is a support ticket. `cdk.json` does the same.
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: 'ap-southeast-1' };

const persist = new PersistStack(app, 'VeriforgePersist', { env });
const appStack = new AppStack(app, 'VeriforgeApp', { env, persist });
// Edge depends on the instance's public DNS name, so it must be created after
// the app stack.
new EdgeStack(app, 'VeriforgeEdge', {
  env,
  app: appStack,
  // A counter, not a secret: it exists only to make the ssm:GetParameter read
  // happen again on every deploy, because the origin-verify value changes.
  originVerifyVersion: process.env.ORIGIN_VERIFY_VERSION ?? '1',
});
new BudgetStack(app, 'VeriforgeBudget', { env, app: appStack });

app.synth();