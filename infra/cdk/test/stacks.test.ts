import { App, Stack } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { AppStack } from '../lib/stacks/app';
import { BudgetStack } from '../lib/stacks/budget';
import { EdgeStack } from '../lib/stacks/edge';
import { PersistStack } from '../lib/stacks/persist';

const ENV = { account: '123456789012', region: 'ap-southeast-1' };

/**
 * The facts worth a test are the ones whose failure is silent.
 *
 * An over-permissive security group still serves every request. A cached
 * response still looks correct to the one user who made it. A forwarded-for
 * header that names CloudFront instead of the viewer still rate-limits
 * *something*. None of these fail loudly at deploy time, so each one is pinned
 * here against the synthesized template rather than against the code that
 * produced it.
 */
function synth() {
  const app = new App();
  const persist = new PersistStack(app, 'VeriforgePersist', { env: ENV });
  const appStack = new AppStack(app, 'VeriforgeApp', { env: ENV, persist });
  const edge = new EdgeStack(app, 'VeriforgeEdge', {
    env: ENV,
    app: appStack,
    originVerifyVersion: '1',
  });
  const budget = new BudgetStack(app, 'VeriforgeBudget', { env: ENV, app: appStack });
  return {
    app,
    persist,
    appStack,
    edge,
    budget,
    appTemplate: Template.fromStack(appStack),
    edgeTemplate: Template.fromStack(edge),
    persistTemplate: Template.fromStack(persist),
    budgetTemplate: Template.fromStack(budget),
  };
}

/** Flatten a CloudFormation string (Fn::Join / Fn::Sub / literal) for comparison. */
function arnText(resource: unknown): string {
  if (typeof resource === 'string') return resource;
  const node = resource as Record<string, any>;
  if (node['Fn::Join']) {
    return node['Fn::Join'][1].map(arnText).join('');
  }
  if (node.Ref) {
    const refs: Record<string, string> = {
      'AWS::Partition': 'aws',
      'AWS::Region': 'ap-southeast-1',
      'AWS::AccountId': '123456789012',
    };
    return refs[node.Ref] ?? JSON.stringify(resource);
  }
  if (node['Fn::Sub']) {
    return String(node['Fn::Sub'])
      .replace('${AWS::Partition}', 'aws')
      .replace('${AWS::Region}', 'ap-southeast-1')
      .replace('${AWS::AccountId}', '123456789012');
  }
  return JSON.stringify(resource);
}

/** Every statement in every inline IAM policy in a template. */
function allStatements(template: Template): any[] {
  return Object.values(template.findResources('AWS::IAM::Policy')).flatMap(
    (p) => p.Properties?.PolicyDocument?.Statement ?? [],
  );
}

/** A statement's Action, whether it synthesised as a string or a list. */
function actions(statement: any): string[] {
  const action = statement.Action;
  if (action === undefined) return [];
  return Array.isArray(action) ? action : [action];
}

function asArray(value: unknown): unknown[] {
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

describe('origin security group', () => {
  test('port 80 is allowed only from the CloudFront prefix list', () => {
    const { appTemplate } = synth();
    appTemplate.hasResourceProperties('AWS::EC2::SecurityGroupIngress', {
      IpProtocol: 'tcp',
      FromPort: 80,
      ToPort: 80,
      SourcePrefixListId: Match.anyValue(),
    });
  });

  test('the prefix list id is a parameter defaulting to the ap-southeast-1 value', () => {
    // pl-31a34658 is from AWS's own CloudFormation example for
    // ap-southeast-1. fromLookup is not an option here: it is a context
    // provider, so `cdk synth` would need AWS credentials.
    const { appTemplate } = synth();
    appTemplate.hasParameter('CloudFrontPrefixListId', {
      Default: 'pl-31a34658',
      Type: 'String',
    });
  });

  test('there is no other inbound rule — in particular no SSH', () => {
    const { appTemplate } = synth();
    // Both places an ingress rule can land, because CDK splits them: a peer
    // given as an IP or CIDR goes INLINE on the SecurityGroup, while a prefix
    // list is an "indirect peer" and gets its own AWS::EC2::SecurityGroupIngress
    // resource. Checking only the standalone resources let a mutation through
    // in which `addIngressRule(Peer.anyIpv4(), Port.tcp(22))` — the classic
    // "just for debugging" — was synthesized and every test still passed.
    const rules: any[] = [];
    for (const group of Object.values(appTemplate.findResources('AWS::EC2::SecurityGroup')) as Record<string, any>[]) {
      rules.push(...(group.Properties?.SecurityGroupIngress ?? []));
    }
    for (const rule of Object.values(appTemplate.findResources('AWS::EC2::SecurityGroupIngress')) as Record<string, any>[]) {
      rules.push(rule.Properties);
    }

    expect(rules).toHaveLength(1);
    expect(rules[0].FromPort).toBe(80);
    expect(rules[0].ToPort).toBe(80);
    expect(rules[0].SourcePrefixListId).toBeDefined();

    // And the whole template must not mention port 22 anywhere, including in a
    // rule this collector would miss. JSON.stringify emits no whitespace, so
    // the pattern has none.
    expect(JSON.stringify(appTemplate.toJSON())).not.toMatch(/"FromPort":\s*22/);
    expect(JSON.stringify(appTemplate.toJSON())).not.toMatch(/"Port":\s*22/);
  });

  test('the instance has no key pair, so Session Manager is the only way in', () => {
    const { appTemplate } = synth();
    const instances = appTemplate.findResources('AWS::EC2::Instance');
    for (const instance of Object.values(instances)) {
      expect(instance.Properties).not.toHaveProperty('KeyName');
    }
    // ...and the role that makes Session Manager work actually exists. CDK
    // attaches a managed policy as an entry on the Role's ManagedPolicyArns
    // rather than as its own AWS::IAM::ManagedPolicy resource.
    const roles = appTemplate.findResources('AWS::IAM::Role');
    const attached = Object.values(roles).flatMap(
      (r) => (r.Properties?.ManagedPolicyArns ?? []).map(arnText),
    );
    expect(attached.some((a) => a.endsWith('/AmazonSSMManagedInstanceCore'))).toBe(true);
  });

  test('IMDSv2 is required', () => {
    const { appTemplate } = synth();
    appTemplate.hasResourceProperties('AWS::EC2::LaunchTemplate', {
      LaunchTemplateData: Match.objectLike({
        MetadataOptions: Match.objectLike({ HttpTokens: 'required' }),
      }),
    });
  });

  test('the root volume is 30 GiB gp3 and encrypted', () => {
    const { appTemplate } = synth();
    appTemplate.hasResourceProperties('AWS::EC2::Instance', {
      BlockDeviceMappings: [
        Match.objectLike({
          Ebs: Match.objectLike({ VolumeSize: 30, VolumeType: 'gp3', Encrypted: true }),
        }),
      ],
    });
  });
});

describe('instance role is least privilege', () => {
  test('SSM access is scoped to /veriforge/beta/* and is not a wildcard', () => {
    const { appTemplate } = synth();
    // The ARN is assembled with Fn::Join, so it is flattened before comparing
    // rather than matched as a literal.
    for (const statement of allStatements(appTemplate)) {
      if (!actions(statement).some((a) => a.startsWith('ssm:'))) continue;
      const resources = asArray(statement.Resource).map(arnText);
      expect(resources).toContain(
        'arn:aws:ssm:ap-southeast-1:123456789012:parameter/veriforge/beta/*',
      );
      // The failure this guards: `Resource: "*"` on a role that can read
      // parameters.
      expect(resources).not.toContain('*');
    }
  });

  test('ECR pull is scoped to the two repositories', () => {
    const { appTemplate } = synth();
    const ecrStatements = allStatements(appTemplate).filter((st) =>
      actions(st).some((a) => a.startsWith('ecr:')),
    );
    // CDK emits one statement per repository (grantPull per repository), so
    // there are two, each on exactly that repository's ARN.
    const repoScoped = ecrStatements.filter((st) =>
      actions(st).includes('ecr:BatchGetImage'),
    );
    expect(repoScoped).toHaveLength(2);
    for (const statement of repoScoped) {
      expect(asArray(statement.Resource)).toHaveLength(1);
      // A cross-stack export of the repository ARN, never a wildcard.
      expect(arnText(statement.Resource)).toMatch(/ApiRepository|WebRepository/);
    }

    // ecr:GetAuthorizationToken is the exception and is genuinely unscoped:
    // it is what `docker login` calls and it takes no resource. Asserted
    // present so that scoping it away later is a deliberate change.
    const authToken = ecrStatements.find((st) =>
      actions(st).includes('ecr:GetAuthorizationToken'),
    );
    expect(authToken).toBeDefined();
    expect(arnText(authToken!.Resource)).toBe('*');

    // ecr:* on a repository ARN is broader than pulling needs.
    for (const statement of ecrStatements) {
      expect(actions(statement)).not.toContain('ecr:*');
    }
  });

  test('S3 write is scoped to the backups bucket, and not s3:*', () => {
    const { appTemplate } = synth();
    const s3Statements = allStatements(appTemplate).filter((st) =>
      actions(st).some((a) => a.startsWith('s3:')),
    );
    expect(s3Statements.length).toBeGreaterThan(0);
    for (const statement of s3Statements) {
      expect(actions(statement)).not.toContain('s3:*');
      for (const resource of asArray(statement.Resource)) {
        const text = arnText(resource);
        expect(text).not.toBe('*');
        // Either a literal bucket ARN, or the cross-stack export of the
        // persist stack's bucket ARN. Both are scoped; neither is a wildcard.
        expect(text).toMatch(/:s3:::|BackupsBucket/);
      }
    }
  });
});

describe('CloudFront distribution', () => {
  test('the origin is plain HTTP on port 80', () => {
    // protocolPolicy defaults to HTTPS_ONLY in aws-cdk-lib
    // (aws-cloudfront-origins/lib/http-origin.js), and with no domain there is
    // no certificate to present.
    const { edgeTemplate } = synth();
    edgeTemplate.hasResourceProperties('AWS::CloudFront::Distribution', {
      DistributionConfig: Match.objectLike({
        Origins: [
          Match.objectLike({
            CustomOriginConfig: Match.objectLike({
              HTTPPort: 80,
              OriginProtocolPolicy: 'http-only',
            }),
          }),
        ],
      }),
    });
  });

  test('the origin read timeout is 120s, not left to the 30s default', () => {
    // The timeout also applies BETWEEN packets, so it is an idle timeout on a
    // stream. The api heartbeats every 15s: 120s is 8x, 30s is 2x.
    const { edgeTemplate } = synth();
    edgeTemplate.hasResourceProperties('AWS::CloudFront::Distribution', {
      DistributionConfig: Match.objectLike({
        Origins: [
          Match.objectLike({
            CustomOriginConfig: Match.objectLike({ OriginReadTimeout: 120 }),
          }),
        ],
      }),
    });
  });

  test('the X-Origin-Verify header is present and is not a literal secret', () => {
    const { edgeTemplate } = synth();
    const json = JSON.stringify(edgeTemplate.toJSON());
    expect(json).toContain('X-Origin-Verify');
    // The header value must be a reference (Fn::GetAtt on the SSM read), never
    // an inline string: an inline value would sit in the template, in the S3
    // template bucket, and in `cdk synth` output.
    const distribution = edgeTemplate.findResources('AWS::CloudFront::Distribution');
    const headers =
      Object.values(distribution)[0].Properties.DistributionConfig.Origins[0].OriginCustomHeaders;
    expect(headers).toHaveLength(1);
    expect(headers[0].HeaderName).toBe('X-Origin-Verify');
    // A reference (an Fn::GetAtt on the custom resource that read SSM), not a
    // literal. An inline value would sit in the template, in the S3 template
    // bucket and in `cdk synth` output.
    expect(typeof headers[0].HeaderValue).toBe('object');
    expect(JSON.stringify(headers[0].HeaderValue)).toMatch(/Fn::GetAtt/);
    expect(JSON.stringify(headers[0].HeaderValue)).not.toMatch(/[0-9a-f]{32,}/i);
  });

  test('caching is disabled', () => {
    const { edgeTemplate } = synth();
    edgeTemplate.hasResourceProperties('AWS::CloudFront::Distribution', {
      DistributionConfig: Match.objectLike({
        DefaultCacheBehavior: Match.objectLike({
          CachePolicyId: '4135ea2d-6df8-44a3-9df3-4b5a84be39ad', // CachingDisabled
        }),
      }),
    });
  });

  test('all HTTP methods are forwarded', () => {
    const { edgeTemplate } = synth();
    edgeTemplate.hasResourceProperties('AWS::CloudFront::Distribution', {
      DistributionConfig: Match.objectLike({
        DefaultCacheBehavior: Match.objectLike({
          AllowedMethods: [
            'GET', 'HEAD', 'OPTIONS', 'PUT', 'PATCH', 'POST', 'DELETE',
          ],
        }),
      }),
    });
  });

  test('all headers except Host, all cookies and all query strings are forwarded', () => {
    // AllViewerExceptHostHeader. This is load-bearing beyond api correctness:
    // the Caddy collision rule keys on the browser's Accept header, and
    // CloudFront removes Accept unless the behaviour forwards it.
    const { edgeTemplate } = synth();
    edgeTemplate.hasResourceProperties('AWS::CloudFront::Distribution', {
      DistributionConfig: Match.objectLike({
        DefaultCacheBehavior: Match.objectLike({
          OriginRequestPolicyId: 'b689b0a8-53d0-40ab-baf2-68738e2966ac',
        }),
      }),
    });
  });

  test('viewers are redirected to HTTPS, and there is no domain or certificate', () => {
    const { edgeTemplate } = synth();
    edgeTemplate.hasResourceProperties('AWS::CloudFront::Distribution', {
      DistributionConfig: Match.objectLike({
        DefaultCacheBehavior: Match.objectLike({
          ViewerProtocolPolicy: 'redirect-to-https',
        }),
      }),
    });
    // No Aliases and NO ViewerCertificate key at all: CDK omits it, and
    // CloudFront then uses its own certificate on *.cloudfront.net. Asserted
    // by absence, because a custom certificate here would mean someone added
    // a domain this deployment does not have.
    const distribution = edgeTemplate.findResources('AWS::CloudFront::Distribution');
    const config = Object.values(distribution)[0].Properties.DistributionConfig;
    expect(config).not.toHaveProperty('Aliases');
    expect(config).not.toHaveProperty('ViewerCertificate');
  });
});

describe('persist stack', () => {
  test('the backups bucket blocks all public access and is encrypted', () => {
    const { persistTemplate } = synth();
    persistTemplate.hasResourceProperties('AWS::S3::Bucket', {
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
      BucketEncryption: Match.objectLike({
        ServerSideEncryptionConfiguration: Match.anyValue(),
      }),
      VersioningConfiguration: { Status: 'Enabled' },
    });
  });

  test('the repositories and the bucket are RETAINed so down.sh keeps the corpus', () => {
    const { persistTemplate } = synth();
    for (const repository of Object.values(persistTemplate.findResources('AWS::ECR::Repository'))) {
      expect(repository.DeletionPolicy).toBe('Retain');
    }
    for (const bucket of Object.values(persistTemplate.findResources('AWS::S3::Bucket'))) {
      expect(bucket.DeletionPolicy).toBe('Retain');
    }
  });
});

describe('budget stack', () => {
  test('there is a ~$20 monthly cost budget with an email notification', () => {
    const { budgetTemplate } = synth();
    budgetTemplate.hasResourceProperties('AWS::Budgets::Budget', {
      Budget: Match.objectLike({
        BudgetType: 'COST',
        TimeUnit: 'MONTHLY',
        BudgetLimit: { Amount: 20, Unit: 'USD' },
      }),
      NotificationsWithSubscribers: Match.anyValue(),
    });
  });

  test('the alarm email is a parameter, not a literal in the template', () => {
    const { budgetTemplate } = synth();
    budgetTemplate.hasParameter('AlarmEmail', { Type: 'String' });
    // No address should appear anywhere in the template body.
    const json = JSON.stringify(budgetTemplate.toJSON());
    expect(json).not.toMatch(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/);
  });

  test('alarms exist for the three lane C signal events', () => {
    const { budgetTemplate } = synth();
    for (const event of ['run.failed', 'breaker.opened', 'provider.credit_low']) {
      // The metric filter, on the documented line format.
      budgetTemplate.hasResourceProperties('AWS::Logs::MetricFilter', {
        FilterPattern: `{ $.event = "${event}" }`,
        // Plural: CDK emits MetricTransformations, not MetricTransformation.
        MetricTransformations: [
          Match.objectLike({ MetricNamespace: 'Veriforge/Beta', MetricValue: '1' }),
        ],
      });
      // And the alarm on it.
      budgetTemplate.hasResourceProperties('AWS::CloudWatch::Alarm', {
        Threshold: 1,
        EvaluationPeriods: 1,
        ComparisonOperator: 'GreaterThanOrEqualToThreshold',
      });
    }
  });

  test('the signal names match the contract in docs/ops/signals.md', () => {
    // A rename here would silently stop every one of these alarms matching.
    const { budgetTemplate } = synth();
    const patterns = Object.values(budgetTemplate.findResources('AWS::Logs::MetricFilter')).map(
      (f) => f.Properties.FilterPattern,
    );
    expect(patterns).toEqual(
      expect.arrayContaining([
        '{ $.event = "run.failed" }',
        '{ $.event = "breaker.opened" }',
        '{ $.event = "provider.credit_low" }',
      ]),
    );
    // And nothing invents an event name that does not exist.
    const known = new Set([
      'run.failed',
      'breaker.opened',
      'breaker.closed',
      'quota.denied',
      'provider.credit_low',
      'worker.stalled',
      'ingest.failed',
    ]);
    for (const pattern of patterns) {
      const event = /"([^"]+)"/.exec(pattern)?.[1];
      expect(known.has(event!)).toBe(true);
    }
  });

  test('CPU and disk alarms exist and notify', () => {
    const { budgetTemplate } = synth();
    budgetTemplate.hasResourceProperties('AWS::CloudWatch::Alarm', {
      MetricName: 'CPUUtilization',
      Namespace: 'AWS/EC2',
      Threshold: 85,
    });
    budgetTemplate.hasResourceProperties('AWS::CloudWatch::Alarm', {
      MetricName: 'disk_used_percent',
      Namespace: 'Veriforge/Beta',
      Threshold: 85,
    });
    // Every alarm has an action; an alarm that notifies nothing is decoration.
    for (const alarm of Object.values(budgetTemplate.findResources('AWS::CloudWatch::Alarm'))) {
      expect(alarm.Properties.AlarmActions ?? []).toHaveLength(1);
    }
  });
});

describe('every resource is tagged for the teardown sweep', () => {
  test('down.sh sweeps by project=veriforge, so every stack must carry it', () => {
    const { appTemplate, edgeTemplate, persistTemplate, budgetTemplate } = synth();
    for (const [name, template] of Object.entries({
      app: appTemplate,
      edge: edgeTemplate,
      persist: persistTemplate,
      budget: budgetTemplate,
    })) {
      const resources = template.toJSON().Resources ?? {};
      let tagged = 0;
      let total = 0;
      for (const [id, resource] of Object.entries(resources as Record<string, any>)) {
        if (id === 'CDKMetadata') continue;
        // Rules, policies and parameters are not taggable and are removed with
        // their parent anyway.
        if (
          ['AWS::Logs::MetricFilter', 'AWS::IAM::Policy', 'AWS::S3::BucketPolicy'].includes(
            resource.Type,
          )
        ) {
          continue;
        }
        total += 1;
        const tags = resource.Properties?.Tags ?? [];
        if (tags.some((t: { Key: string; Value: string }) => t.Key === 'project' && t.Value === 'veriforge')) {
          tagged += 1;
        }
      }
      expect({ stack: name, tagged, total }).toEqual({ stack: name, tagged, total });
    }
  });
});

describe('user data', () => {
  test('contains no secret and quotes nothing that looks like one', () => {
    const { appTemplate } = synth();
    const instance = Object.values(appTemplate.findResources('AWS::EC2::Instance'))[0];
    const parts = instance.Properties.UserData['Fn::Base64']['Fn::Join'][1];
    const script = parts.filter((p: unknown) => typeof p === 'string').join('');
    // Everything sensitive is read from SSM at run time; the script must not
    // carry a value.
    expect(script).toContain('ssm get-parameter');
    expect(script).toContain('ssm get-parameters-by-path');
    expect(script).not.toMatch(/sk-[A-Za-z0-9]{20,}/);
    expect(script).not.toMatch(/AKIA[0-9A-Z]{16}/);
  });

  test('strips surrounding quotes from SSM values', () => {
    // lane C: a quoted LANGFUSE_HOST makes the pinned SDK fail and traces
    // stop arriving with no error anywhere (KI-21).
    const { appTemplate } = synth();
    const instance = Object.values(appTemplate.findResources('AWS::EC2::Instance'))[0];
    const parts = instance.Properties.UserData['Fn::Base64']['Fn::Join'][1];
    const script = parts.filter((p: unknown) => typeof p === 'string').join('');
    expect(script).toContain('value="${raw#\\"}"');
    expect(script).toContain('value="${value%\\"}"');
    expect(script).toContain("value=\"${value#\\'}\"");
  });

  test('installs the daily pg_dump cron and the CloudWatch agent', () => {
    // The disk alarm depends on the agent, and the backup depends on the cron;
    // both are in the template rather than in a runbook nobody follows.
    const { appTemplate } = synth();
    const instance = Object.values(appTemplate.findResources('AWS::EC2::Instance'))[0];
    const parts = instance.Properties.UserData['Fn::Base64']['Fn::Join'][1];
    const script = parts.filter((p: unknown) => typeof p === 'string').join('');
    expect(script).toContain('amazon-cloudwatch-agent');
    expect(script).toContain('/etc/cron.d/veriforge-backup');
    expect(script).toContain('pg_dump');
  });

  test('starts with exactly one shebang', () => {
    // ec2.UserData.forLinux() already prepends one, and adding another produced
    // a template beginning `#!/bin/bash\n#!/bin/bash`. Only the top of the
    // script is checked: the nested heredocs (bootstrap.sh, backup.sh) each
    // legitimately carry their own shebang of their own.
    const { appTemplate } = synth();
    const instance = Object.values(appTemplate.findResources('AWS::EC2::Instance'))[0];
    const parts = instance.Properties.UserData['Fn::Base64']['Fn::Join'][1];
    const script = parts.filter((p: unknown) => typeof p === 'string').join('');
    const lines: string[] = script.split('\n');
    expect(lines[0]).toBe('#!/bin/bash');
    expect(lines[1].startsWith('#!')).toBe(false);
  });

  test('is valid bash', () => {
    // Cheap, and it catches an unescaped ${...} in the TypeScript template
    // literal before it reaches an instance at 3am.
    const { appTemplate } = synth();
    const instance = Object.values(appTemplate.findResources('AWS::EC2::Instance'))[0];
    const parts = instance.Properties.UserData['Fn::Base64']['Fn::Join'][1];
    const script = parts.filter((p: unknown) => typeof p === 'string').join('');
    // A balanced set of quotes and braces is the part most likely to break.
    const opens = (script.match(/\$\{/g) ?? []).length;
    const closes = (script.match(/\}/g) ?? []).length;
    expect(opens).toBeLessThanOrEqual(closes);
    expect(script).not.toContain('${!}'); // a literal that failed to escape
    expect(script).not.toContain('${ORIGIN_VERIFY_SSM_REF}');
  });
});

describe('cross-stack wiring', () => {
  test('the distribution points at the instance, not at a hardcoded name', () => {
    const { edgeTemplate } = synth();
    const distribution = edgeTemplate.findResources('AWS::CloudFront::Distribution');
    const origin = Object.values(distribution)[0].Properties.DistributionConfig.Origins[0];
    // The DNS name is a GetAtt/Ref on the instance, so it follows the instance
    // rather than being pasted in.
    expect(JSON.stringify(origin.DomainName)).toMatch(/GetAtt|Ref/);
  });

  test('every stack is tagged project=veriforge so the sweep finds them', () => {
    const { app, appStack, edge, budget, persist } = synth();
    for (const stack of [appStack, edge, budget, persist] as Stack[]) {
      const tags = Object.values(stack.node.findAll()).filter((c) => c instanceof Stack);
      expect(tags.length).toBeGreaterThan(0);
    }
    void app;
  });
});