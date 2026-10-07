import { CfnOutput, CfnParameter, RemovalPolicy, Stack, Tags, type StackProps } from 'aws-cdk-lib/core';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import type { Construct } from 'constructs';
import type { PersistStack } from './persist';

/**
 * One EC2 box running the whole stack behind Caddy.
 *
 * Instance sizing is item 0's measured table: the dev stack's five processes
 * came to 2037 MiB resident against a database holding 14,216 chunks, and
 * compose.prod.yaml's limits sum to 3128 MiB — which fits 4 GiB with roughly
 * 518 MiB of slack. t4g is Graviton, so every image needs a linux/arm64
 * build; item 0 checked all four base images before anything was built,
 * because ParadeDB was the risk.
 */
export class AppStack extends Stack {
  readonly instance: ec2.Instance;
  readonly logGroup: LogGroup;
  readonly securityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: StackProps & { persist: PersistStack }) {
    super(scope, id, props);

    // The CloudFront origin-facing managed prefix list. `fromLookup` would be
    // the ergonomic choice, but it is a context provider: `cdk synth` would
    // need AWS credentials and this lane has none. The id is per-region, so it
    // is a parameter with the ap-southeast-1 value from AWS's own example
    // template. day-2: verify with
    //   aws ec2 describe-managed-prefix-lists --region ap-southeast-1 \
    //     --prefix-list-ids pl-31a34658 \
    //     --query 'PrefixLists[0].PrefixListName'
    //   which must print com.amazonaws.global.cloudfront.origin-facing
    const prefixListId = new CfnParameter(this, 'CloudFrontPrefixListId', {
      type: 'String',
      default: 'pl-31a34658',
      allowedPattern: '^pl-[0-9a-f]+$',
      description:
        'Managed prefix list id for com.amazonaws.global.cloudfront.origin-facing in the deploy region.',
    }).valueAsString;

    const instanceType = new CfnParameter(this, 'InstanceType', {
      type: 'String',
      default: 't4g.medium',
      allowedValues: ['t4g.medium', 't4g.large'],
      description: 'Graviton instance type. Move to t4g.large if the corpus grows.',
    }).valueAsString;

    // One public subnet, no NAT. Nothing here is private that anything else
    // needs to reach: the origin must be reachable by CloudFront, and every
    // outbound call (ECR, SSM, S3) goes to the internet. A NAT gateway would
    // add about $32/month to a deployment whose entire budget is about $9.
    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [{ subnetType: ec2.SubnetType.PUBLIC, name: 'public' }],
    });

    const securityGroup = new ec2.SecurityGroup(this, 'OriginSecurityGroup', {
      vpc,
      description: 'Port 80 from the CloudFront origin-facing prefix list only.',
      allowAllOutbound: true,
    });
    // Port 80, from the prefix list, and nothing else. No SSH rule anywhere:
    // access is SSM Session Manager via the instance role below, so there is no
    // key pair and nothing to brute-force. The Caddyfile's X-Origin-Verify
    // check is the second lock on the same door.
    securityGroup.addIngressRule(
      ec2.PrefixList.fromPrefixListId(this, 'CloudFrontPrefixList', prefixListId),
      ec2.Port.tcp(80),
      'HTTP from CloudFront only. Direct access is refused by X-Origin-Verify.',
    );
    this.securityGroup = securityGroup;

    // The docker awslogs driver ships here (see user data), which is what the
    // log-event alarms in the budget stack filter over.
    const logGroup = new LogGroup(this, 'DockerLogs', {
      logGroupName: '/veriforge/beta/docker',
      retention: RetentionDays.ONE_WEEK,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    this.logGroup = logGroup;

    const role = new iam.Role(this, 'InstanceRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      description: 'Least privilege for the beta instance: SSM reads, ECR pulls, S3 backups.',
    });

    // The deployment's own secrets, scoped to the beta path. Deliberately not
    // `*`: this role can read the beta deployment's configuration and nothing
    // else in the account.
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['ssm:GetParameter', 'ssm:GetParameters', 'ssm:GetParametersByPath'],
        resources: [
          `arn:${this.partition}:ssm:${this.region}:${this.account}:parameter/veriforge/beta/*`,
        ],
      }),
    );

    // Pull the two images. Scoped to these repositories;
    // grantPull adds BatchGetImage + GetDownloadUrlForLayer, which is the
    // minimum that works and narrower than ecr:* on the repository ARN.
    props.persist.apiRepository.grantPull(role);
    props.persist.webRepository.grantPull(role);

    // Read and write the backups bucket only: no s3:*, no ListAllMyBuckets.
    props.persist.backupsBucket.grantReadWrite(role);

    // Session Manager, so there is no SSH. The managed policy is the
    // documented, maintained way to reach an instance with no key pair.
    role.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'),
    );

    // The CloudWatch agent in user data writes the disk metric the budget
    // stack alarms on; EC2 publishes CPU on its own but not disk.
    logGroup.grantWrite(role);

    const instance = new ec2.Instance(this, 'Origin', {
      instanceType: new ec2.InstanceType(instanceType),
      machineImage: ec2.MachineImage.latestAmazonLinux2023(),
      vpc,
      securityGroup,
      role,
      // No key pair at all — neither keyName nor keyPair is set, which is the
      // point: Session Manager is the only way in, so there is nothing to
      // brute-force and no key to leak.
      // A public address: CloudFront has to reach the origin.
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      // Item 2's entire forwarded-allow-ips argument rests on the proxy
      // headers being trustworthy, and IMDSv1 is open to anything that achieves
      // SSRF on the box. `requireImdsv2` alone; combining it with
      // `httpTokens` throws CannotRequireImdsvMetadataOptions.
      requireImdsv2: true,
      blockDevices: [
        {
          deviceName: '/dev/xvda',
          volume: ec2.BlockDeviceVolume.ebs(30, {
            volumeType: ec2.EbsDeviceVolumeType.GP3,
            encrypted: true,
            deleteOnTermination: true,
          }),
        },
      ],
      userData: ec2.UserData.forLinux(),
    });
    instance.addUserData(
      renderUserData({ logGroupName: logGroup.logGroupName, region: this.region }),
    );
    this.instance = instance;

    Tags.of(this).add('project', 'veriforge');
    Tags.of(this).add('lifecycle', 'throwaway');

    new CfnOutput(this, 'InstanceId', { value: instance.instanceId, description: 'EC2 instance id' });
    new CfnOutput(this, 'PublicDnsName', {
      value: instance.instancePublicDnsName,
      description: 'CloudFront origin. Changes whenever the instance is replaced.',
    });
    new CfnOutput(this, 'LogGroupName', {
      value: logGroup.logGroupName,
      description: 'Where container logs land; the alarms are metric filters on this.',
    });
    new CfnOutput(this, 'SecurityGroupId', {
      value: securityGroup.securityGroupId,
      description: 'Origin security group: port 80 from the CloudFront prefix list only',
    });
  }
}

/**
 * User data: install Docker, point the log driver at CloudWatch Logs, install
 * the CloudWatch agent for the disk metric, and write
 * `/opt/veriforge/bootstrap.sh` — which is the script `up.sh` actually runs,
 * over SSM Run Command, once SSM holds the environment.
 *
 * Splitting it this way is not tidiness. The api needs `WEB_ORIGIN`, which is
 * the CloudFront distribution's domain, and that does not exist until the edge
 * stack is deployed — which is after this instance boots. So the boot script
 * cannot carry the environment, and `up.sh` pushes it and runs the bootstrap
 * afterwards.
 *
 * No secret is in this file. The instance reads them from SSM at run time with
 * its own role.
 */
function renderUserData(props: { logGroupName: string; region: string }): string {
  // No shebang here: ec2.UserData.forLinux() already prepends one, and the
  // synthesised template began `#!/bin/bash\n#!/bin/bash`. Harmless to the
  // shell and wrong to ship.
  return `# Managed by the Veriforge beta app stack. Local changes are lost on reboot.
set -euo pipefail

dnf install -y docker docker-compose-plugin awscli-2 amazon-cloudwatch-agent jq
systemctl enable --now docker

# Every container's logs go to CloudWatch Logs, because the alarms in the
# budget stack are metric filters over the api's JSON signal lines
# (docs/ops/signals.md) and a json-file driver would leave them on the box
# where nothing can see them. No credentials option: the awslogs driver uses
# the EC2 instance role.
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'DOCKERJSON'
{
  "log-driver": "awslogs",
  "log-opts": {
    "awslogs-group": "${props.logGroupName}",
    "awslogs-region": "${props.region}",
    "awslogs-create-group": "false",
    "awslogs-stream-prefix": "veriforge"
  }
}
DOCKERJSON
systemctl restart docker

# The disk alarm needs a disk metric and EC2 does not publish one by default.
cat > /opt/veriforge/cwagent.json <<'CWAGENT'
{
  "logs": {
    "metrics_collected": { "disk": {} },
    "flush_interval": 60
  },
  "metrics": {
    "namespace": "Veriforge/Beta",
    "append_dimensions": { "InstanceId": "\${aws:InstanceId}" },
    "aggregation_dimensions": [["InstanceId"]]
  }
}
CWAGENT
amazon-cloudwatch-agent-ctl -f fetch-config -m ec2 -s
systemctl enable amazon-cloudwatch-agent || true
amazon-cloudwatch-agent-ctl -f /opt/veriforge/cwagent.json -s || true

install -d -m 0750 /opt/veriforge

cat > /opt/veriforge/bootstrap.sh <<'BOOTSTRAP'
#!/bin/bash
# Run by up.sh over SSM Run Command. Idempotent: safe to re-run after a code
# change, and up.sh re-runs it on every deploy.
#
# up.sh invokes it as:
#   API_IMAGE=<ecr>/api:<sha> WEB_IMAGE=<ecr>/web:<sha> \\
#   BACKUP_BUCKET=<bucket> /opt/veriforge/bootstrap.sh
#
# Reads this deployment's secrets from SSM using the instance role, writes them
# to a 0600 file, and never echoes, logs, or passes a value on a command line.
set -euo pipefail
cd /opt/veriforge

# Named guards rather than relying on \${VAR} failing somewhere further down
# with "unbound variable".
: "\${API_IMAGE:?up.sh must set API_IMAGE}"
: "\${WEB_IMAGE:?up.sh must set WEB_IMAGE}"
: "\${BACKUP_BUCKET:?up.sh must set BACKUP_BUCKET}"
REGION="\${AWS_REGION:?the instance role supplies AWS_REGION}"

: > /opt/veriforge/.env
chmod 600 /opt/veriforge/.env
while IFS= read -r name; do
  [ -n "$name" ] || continue
  raw="\$(aws ssm get-parameter --region "$REGION" --name "veriforge/beta/$name" \\
    --with-decryption --query 'Parameter.Value' --output text)"
  # Strip surrounding quotes. A quoted LANGFUSE_HOST makes the pinned SDK fail
  # to authenticate and traces simply stop arriving, with no error anywhere
  # (KI-21) — lane C found this on the deployment. Not optional formatting.
  value="\${raw#\\"}"
  value="\${value%\\"}"
  value="\${value#\\'}"
  value="\${value%\\'}"
  printf '%s=%s\\n' "$name" "$value" >> /opt/veriforge/.env
done < <(aws ssm get-parameters-by-path --region "$REGION" \\
  --path "/veriforge/beta" --query 'Parameters[].Name' --output text | sed 's|.*/||')

# compose.prod.yaml lives in the repository, not in an image; up.sh uploads it
# to the backups bucket at deploy time and it is fetched from there. That keeps
# git the single source of truth for the compose file.
aws s3 cp "s3://$BACKUP_BUCKET/compose/compose.prod.yaml" /opt/veriforge/compose.prod.yaml \\
  --region "$REGION"

for repo in "\${API_IMAGE%%:*}" "\${WEB_IMAGE%%:*}"; do
  aws ecr get-login-password --region "$REGION" \\
    | docker login --username AWS --password-stdin "$repo"
done

export API_IMAGE WEB_IMAGE
docker compose --env-file /opt/veriforge/.env -f /opt/veriforge/compose.prod.yaml pull -q
docker compose --env-file /opt/veriforge/.env -f /opt/veriforge/compose.prod.yaml up -d

# --- daily pg_dump to S3 ----------------------------------------------------
cat > /opt/veriforge/backup.sh <<'BACKUPSCRIPT'
#!/bin/bash
set -euo pipefail
set -a; . /opt/veriforge/.env; set +a
ts="\$(date -u +%Y%m%dT%H%M%SZ)"
dump="/tmp/veriforge-$ts.dump"
docker compose --env-file /opt/veriforge/.env -f /opt/veriforge/compose.prod.yaml \\
  exec -T postgres pg_dump -U "\${POSTGRES_USER:-veriforge}" -d "\${POSTGRES_DB:-veriforge}" -Fc \\
  > "$dump"
aws s3 cp "$dump" "s3://$BACKUP_BUCKET/db/veriforge-$ts.dump" --region "$REGION"
rm -f "$dump"
echo "dump uploaded to s3://$BACKUP_BUCKET/db/veriforge-$ts.dump"
BACKUPSCRIPT
chmod 700 /opt/veriforge/backup.sh

# 03:17 rather than 03:00, so it does not land on the hour with everything
# else in the world.
cat > /etc/cron.d/veriforge-backup <<CRON
17 3 * * * root /opt/veriforge/backup.sh >> /var/log/veriforge-backup.log 2>&1
CRON
chmod 644 /etc/cron.d/veriforge-backup

docker compose --env-file /opt/veriforge/.env -f /opt/veriforge/compose.prod.yaml ps
BOOTSTRAP
chmod 700 /opt/veriforge/bootstrap.sh

echo "veriforge user data complete; run /opt/veriforge/bootstrap.sh via SSM Run Command"
`;
}