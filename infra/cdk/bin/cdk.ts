#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { AppStack } from '../lib/stacks/app';
import { DataStack } from '../lib/stacks/data';
import { EdgeStack } from '../lib/stacks/edge';
import { NetworkStack } from '../lib/stacks/network';

const app = new cdk.App();

const network = new NetworkStack(app, 'VeriforgeNetwork', {});
const data = new DataStack(app, 'VeriforgeData', { network });
new AppStack(app, 'VeriforgeApp', { network, data });
new EdgeStack(app, 'VeriforgeEdge', {});
