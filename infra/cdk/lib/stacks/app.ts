import { Stack, type StackProps } from 'aws-cdk-lib/core';
import type { Construct } from 'constructs';
import type { DataStack } from './data';
import type { NetworkStack } from './network';

export interface AppStackProps extends StackProps {
  network: NetworkStack;
  data: DataStack;
}

export class AppStack extends Stack {
  constructor(scope: Construct, id: string, props: AppStackProps) {
    super(scope, id, props);
    void props.network;
    void props.data;
  }
}
