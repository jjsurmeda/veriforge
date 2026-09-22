import { Stack, type StackProps } from 'aws-cdk-lib/core';
import type { Construct } from 'constructs';
import type { NetworkStack } from './network';

export interface DataStackProps extends StackProps {
  network: NetworkStack;
}

export class DataStack extends Stack {
  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);
    void props.network;
  }
}
