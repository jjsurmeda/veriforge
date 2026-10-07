import { CfnOutput, Duration, Stack, Tags, type StackProps } from 'aws-cdk-lib/core';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import {
  AwsCustomResource,
  AwsCustomResourcePolicy,
  PhysicalResourceId,
} from 'aws-cdk-lib/custom-resources';
import type { Construct } from 'constructs';
import type { AppStack } from './app';

/**
 * One CloudFront distribution in front of the instance.
 *
 * No domain, so no ACM certificate and no Route 53 record. CloudFront serves
 * `https://<distribution-id>.cloudfront.net` on its own certificate, which is
 * why the viewer side is HTTPS while the hop to the origin is plain HTTP.
 */

/**
 * The origin-verify secret reaches CloudFront without ever being written down.
 *
 * Two shapes were tried and one was rejected by `cdk synth` itself:
 *
 * 1. A `{{resolve:ssm-secure:...}}` dynamic reference. Rejected, and the error
 *    is specific: `OriginCustomHeaders.0.HeaderValue: Dynamic reference
 *    '{{resolve:ssm-secure:...}}' to SSM secure strings can only be used in
 *    resource properties (CloudFormation Validate)`. Dynamic references are not
 *    allowed on a distribution's custom origin headers.
 * 2. A CloudFormation parameter. Rejected on our own rules: the value would
 *    appear in `cdk synth` output and in the template body in the S3 template
 *    bucket, which is exactly "a secret in a file and in output".
 *
 * So the value is read out of SSM at deploy time by an AwsCustomResource, and
 * the header value is that resource's output — a CloudFormation reference, not
 * a literal. SSM stays the single source of truth: the same SecureString the
 * instance reads to set ORIGIN_VERIFY for Caddy.
 *
 * Requires the parameter to exist before this stack deploys, so up.sh writes
 * SSM first. day-2: confirm the distribution's header value is non-empty with
 *   aws cloudfront get-distribution --id <id> \
 *     --query 'Distribution.DistributionConfig.Origins[0].OriginCustomHeaders'
 * and then confirm a direct request to the instance is refused.
 */
const ORIGIN_VERIFY_SSM_PARAMETER = '/veriforge/beta/ORIGIN_VERIFY';

export class EdgeStack extends Stack {
  readonly distribution: cloudfront.Distribution;

  constructor(
    scope: Construct,
    id: string,
    // originVerifyVersion changes on every deploy, from up.sh. It is a counter,
    // never the secret itself.
    props: StackProps & { app: AppStack; originVerifyVersion: string },
  ) {
    super(scope, id, props);

    const readOriginVerify = new AwsCustomResource(this, 'ReadOriginVerify', {
      onUpdate: {
        service: 'SSM',
        action: 'getParameter',
        parameters: {
          Name: ORIGIN_VERIFY_SSM_PARAMETER,
          WithDecryption: true,
        },
        // The value is regenerated on every deploy, so CloudFormation has to
        // call ssm:GetParameter again or the distribution would keep serving
        // the previous secret and Caddy would 403 every request. A changing
        // physical id forces that; the cost is that this one resource is
        // non-deterministic in the template, which is acceptable for a
        // throwaway and is the whole reason the read is not cached.
        physicalResourceId: PhysicalResourceId.of(
          `origin-verify-${props.originVerifyVersion}`,
        ),
        // Reading a SecureString is not worth the log; suppress the response
        // body so the value does not land in the custom resource's Lambda log.
        outputPaths: [],
      },
      policy: AwsCustomResourcePolicy.fromSdkCalls({
        resources: [
          Stack.of(this).formatArn({
            service: 'ssm',
            resource: 'parameter',
            resourceName: `${ORIGIN_VERIFY_SSM_PARAMETER.replace(/^\//, '')}`,
          }),
        ],
      }),
      // Short by design: one ssm:GetParameter at deploy time.
      timeout: Duration.minutes(2),
    });
    const distribution = new cloudfront.Distribution(this, 'Distribution', {
      defaultBehavior: {
        // The instance's public DNS name over plain HTTP. `protocolPolicy`
        // must be HTTP_ONLY: aws-cdk-lib's default for an HttpOrigin is
        // HTTPS_ONLY (aws-cloudfront-origins/lib/http-origin.js,
        // `this.props.protocolPolicy ?? OriginProtocolPolicy.HTTPS_ONLY`), and
        // there is no origin certificate for a domain we do not own.
        origin: new origins.HttpOrigin(props.app.instance.instancePublicDnsName, {
          protocolPolicy: cloudfront.OriginProtocolPolicy.HTTP_ONLY,
          httpPort: 80,
          // 120s, the documented maximum. docs/ops/deploy-risk-checks.md has
          // the reasoning: the origin read timeout also applies BETWEEN
          // packets, so it is an idle timeout on a stream rather than a total
          // budget. The api heartbeats every 15s, making 120s an 8x margin
          // where the 30s default is 2x — and a 30s stall is a normal event on
          // a 4 GiB box running a database next to the api.
          //
          // It must be set explicitly. renderCustomOriginConfig emits
          // `originReadTimeout: this.props.readTimeout?.toSeconds()`, which is
          // undefined when unset, and CloudFront then applies its own 30s.
          readTimeout: Duration.seconds(120),
          // On the origin, not the behaviour: in this version of aws-cdk-lib
          // `customHeaders` is an OriginProps field and BehaviorOptions has no
          // `originCustomHeaders`.
          customHeaders: {
            'X-Origin-Verify': readOriginVerify.getResponseFieldReference(
              'Parameter.Value',
            ).toString(),
          },
        }),

        // POST/PUT/PATCH/DELETE/OPTIONS all have to reach the origin: signup,
        // login, run creation, upload and cancel are all non-GET.
        allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        cachedMethods: cloudfront.CachedMethods.CACHE_GET_HEAD,

        // No caching at all, for two reasons. The api is per-user state and a
        // cached answer would be another user's answer; and CloudFront does
        // not cache an incomplete chunked response, which is exactly what an
        // SSE stream is.
        cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,

        // Forward everything the viewer sent except Host (CloudFront must set
        // that to the origin's name), plus all cookies and all query strings.
        // This matters beyond api correctness: the Caddy collision rule keys
        // on the browser's `Accept` header, and CloudFront's header table says
        // it removes `Accept` unless the behaviour forwards it.
        // AllViewerExceptHostHeader is exactly "all headers except Host",
        // which is what the dispatch specifies.
        originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,

        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        compress: false, // with nothing cached, there is nothing to compress
      },

      // CloudFront's own certificate: no ACM, no Route 53, no custom domain.
      // `minimumProtocolVersion` is deliberately NOT set: aws-cdk-lib warns
      // "Ignoring 'minimumProtocolVersion': it has no effect without a custom
      // 'certificate'", and CloudFormation's own validation turns it into a
      // synthesis error. The default certificate's policy is fixed.
      enableIpv6: true,
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      httpVersion: cloudfront.HttpVersion.HTTP2_AND_3,
      comment: 'Veriforge beta — throwaway, one week, no domain',
    });
    this.distribution = distribution;

    Tags.of(this).add('project', 'veriforge');
    Tags.of(this).add('lifecycle', 'throwaway');

    new CfnOutput(this, 'DistributionDomain', {
      value: distribution.distributionDomainName,
      description:
        'The beta URL, and the value of WEB_ORIGIN. It changes on every ' +
        're-deploy of this stack — with no domain there is nothing to hold it ' +
        'steady, which is why up.sh writes WEB_ORIGIN after this stack exists.',
    });
    new CfnOutput(this, 'DistributionId', { value: distribution.distributionId });
  }
}