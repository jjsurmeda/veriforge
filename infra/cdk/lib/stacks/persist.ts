import { CfnOutput, Duration, RemovalPolicy, Stack, Tags, type StackProps } from 'aws-cdk-lib/core';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as s3 from 'aws-cdk-lib/aws-s3';
import type { Construct } from 'constructs';

/**
 * The only stack `down.sh` does not destroy unless it is given `--all`.
 *
 * One ECR repository for the api/workers image, one for the SPA+Caddy image,
 * and one S3 bucket for database dumps and the uploads directory. All three
 * survive a tear-down so the next bring-up can restore the corpus instead of
 * re-embedding the books, which costs provider credit and an hour.
 *
 * Nothing here is expensive: ECR stores images (a few hundred MB) and the
 * bucket holds a handful of pg_dump files. The bucket is the reason `persist`
 * exists and it is retained deliberately — see docs/ops/runbook.md.
 */
export class PersistStack extends Stack {
  readonly apiRepository: ecr.Repository;
  readonly webRepository: ecr.Repository;
  readonly backupsBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    // ImageScanningScanOnPush costs nothing extra on the images we push here
    // and is the difference between "we pushed an image" and "we know what is
    // in the image".
    this.apiRepository = new ecr.Repository(this, 'ApiRepository', {
      repositoryName: 'veriforge-beta-api',
      imageScanOnPush: true,
      imageTagMutability: ecr.TagMutability.MUTABLE, // up.sh re-pushes a SHA tag
      removalPolicy: RemovalPolicy.RETAIN,
      emptyOnDelete: false,
    });

    this.webRepository = new ecr.Repository(this, 'WebRepository', {
      repositoryName: 'veriforge-beta-web',
      imageScanOnPush: true,
      imageTagMutability: ecr.TagMutability.MUTABLE,
      removalPolicy: RemovalPolicy.RETAIN,
      emptyOnDelete: false,
    });

    this.backupsBucket = new s3.Bucket(this, 'BackupsBucket', {
      // No website, no public access, encrypted, versioned: a restored dump
      // that was truncated mid-write is recoverable, which is the only reason
      // versioning is worth the storage here.
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      versioned: true,
      removalPolicy: RemovalPolicy.RETAIN,
      autoDeleteObjects: false,
      lifecycleRules: [
        {
          // Dumps are written daily; a week of history is plenty for a
          // one-week beta and keeps the bucket from growing on an unattended
          // instance. Noncurrent versions go sooner.
          id: 'expire-old-dumps',
          enabled: true,
          expiration: Duration.days(30),
          noncurrentVersionExpiration: Duration.days(7),
        },
      ],
    });

    Tags.of(this).add('project', 'veriforge');
    Tags.of(this).add('lifecycle', 'persist');

    new CfnOutput(this, 'ApiRepositoryUri', {
      value: this.apiRepository.repositoryUri,
      description: 'ECR repository for the api/workers image',
    });
    new CfnOutput(this, 'WebRepositoryUri', {
      value: this.webRepository.repositoryUri,
      description: 'ECR repository for the SPA+Caddy image',
    });
    new CfnOutput(this, 'BackupsBucketName', {
      value: this.backupsBucket.bucketName,
      description: 'S3 bucket holding pg_dump files and uploads',
    });
  }
}