import { CfnParameter, Duration, Stack, Tags, type StackProps } from 'aws-cdk-lib/core';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cloudwatchActions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import type { Construct } from 'constructs';
import type { AppStack } from './app';

/**
 * What stops a throwaway deployment from quietly costing money overnight.
 *
 * A ~$20 monthly budget with an email notification, and five alarms: three
 * built from the api's own structured signals (docs/ops/signals.md), plus CPU
 * and disk for the box itself.
 *
 * The signal alarms are metric filters over the log group the instance's Docker
 * awslogs driver writes to. The event names are the contract in
 * docs/ops/signals.md and are not renamed here: `{ $.event = "run.failed" }`
 * keeps matching only while the name and the field stay as documented.
 */
export class BudgetStack extends Stack {
  constructor(scope: Construct, id: string, props: StackProps & { app: AppStack }) {
    super(scope, id, props);

    const alarmEmail = new CfnParameter(this, 'AlarmEmail', {
      type: 'String',
      allowedPattern: '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$',
      description:
        'Address notified when the budget is forecast to be exceeded, or when ' +
        'any alarm fires.',
    }).valueAsString;

    // One topic for the alarms. Without a delivery target an alarm is a row in
    // a console nobody opens, which is the same as no alarm.
    const alarmTopic = new sns.Topic(this, 'AlarmTopic', {
      displayName: 'Veriforge beta alarms',
      topicName: 'veriforge-beta-alarms',
    });
    alarmTopic.addSubscription(new subscriptions.EmailSubscription(alarmEmail));

    // A budget with no notification attached is a report nobody reads.
    //
    // MONTHLY rather than the default period: a one-week deployment is allowed
    // to spend the whole budget inside a single month, and a daily budget would
    // alert on a day that is perfectly fine.
    //
    // Not CfnBudgetsAction, and that is a finding rather than a preference: in
    // this version of aws-cdk-lib that L1 is the newer budget-actions API. It
    // requires an executionRoleArn and an iamActionDefinition /
    // ssmActionDefinition / scpActionDefinition, and has no EMAIL action type
    // and no subscribers — so it cannot express "email me when this is
    // forecast to be exceeded" at all. CfnBudget's
    // notificationsWithSubscribers is the legacy shape and is still what the
    // console writes.
    new budgets.CfnBudget(this, 'MonthlyBudget', {
      budget: {
        budgetName: 'veriforge-beta-monthly',
        timeUnit: 'MONTHLY',
        budgetType: 'COST',
        budgetLimit: { amount: 20, unit: 'USD' },
      },
      // A sibling of `budget`, not a field inside it.
      notificationsWithSubscribers: [
        {
          notification: {
            notificationType: 'ACTUAL_AND_FORECASTED',
            comparisonOperator: 'GREATER_THAN',
            // 80% of the 20. The forecast is what catches a runaway before the
            // money is spent; 100% would be too late to be useful.
            threshold: 80,
            thresholdType: 'PERCENTAGE',
          },
          // From a stack parameter, never a literal in this file.
          subscribers: [{ address: alarmEmail, subscriptionType: 'EMAIL' }],
        },
      ],
    });

    const logGroup = props.app.logGroup;
    const instance = props.app.instance;

    /** One alarm per structured signal, via a metric filter on the log group. */
    const signalAlarm = (id: string, event: string, description: string): cloudwatch.Alarm => {
      const filter = new logs.MetricFilter(this, `${id}Filter`, {
        logGroup,
        // The documented line format is one JSON object per line, which is what
        // CloudWatch Logs parses without a schema — so the pattern has to name
        // the field as `$.event`.
        //
        // Spelled out with FilterPattern.literal rather than built from
        // FilterPattern.stringValue, because that helper synthesises
        // `{ event = "run.failed" }` with no `$.`. A jest assertion caught it:
        // a pattern without `$.` matches terms in a message string rather than
        // a JSON field, so all three alarms would have silently never fired.
        filterPattern: logs.FilterPattern.literal(`{ $.event = "${event}" }`),
        metricNamespace: 'Veriforge/Beta',
        metricName: event,
        metricValue: '1',
      });

      const alarm = new cloudwatch.Alarm(this, id, {
        metric: filter.metric({ statistic: 'Sum', period: Duration.minutes(5) }),
        threshold: 1,
        evaluationPeriods: 1,
        // One occurrence is worth knowing about: in a private beta of a
        // handful of people, a `run.failed` is a real failure, not a trend.
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        alarmDescription: description,
        // No data must not page anyone at 3am for a beta that is simply idle.
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      });
      alarm.addAlarmAction(new cloudwatchActions.SnsAction(alarmTopic));
      return alarm;
    };

    signalAlarm(
      'RunFailedAlarm',
      'run.failed',
      'A run ended failed. error_code carries the reason.',
    );
    signalAlarm(
      'BreakerOpenedAlarm',
      'breaker.opened',
      'The Jev circuit breaker opened — routing is on the LLM fallback.',
    );
    signalAlarm(
      'ProviderCreditLowAlarm',
      'provider.credit_low',
      'The provider returned 402 or a quota error. Runs fail until it clears.',
    );

    // CPU is published by EC2 itself.
    const highCpu = new cloudwatch.Alarm(this, 'HighCpuAlarm', {
      metric: new cloudwatch.Metric({
        namespace: 'AWS/EC2',
        metricName: 'CPUUtilization',
        dimensionsMap: { InstanceId: instance.instanceId },
        statistic: 'Average',
        period: Duration.minutes(5),
      }),
      threshold: 85,
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription:
        'Sustained high CPU on the origin. t4g.medium has 2 vCPUs shared with ' +
        'the api, both workers and Postgres.',
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    highCpu.addAlarmAction(new cloudwatchActions.SnsAction(alarmTopic));

    // Disk is NOT published by EC2; the CloudWatch agent installed in user data
    // emits this, which is why that install is not optional. `used_percent` on
    // /, where the database volume and the container logs land.
    const diskFull = new cloudwatch.Alarm(this, 'DiskFullAlarm', {
      metric: new cloudwatch.Metric({
        namespace: 'Veriforge/Beta',
        metricName: 'disk_used_percent',
        dimensionsMap: { InstanceId: instance.instanceId, path: '/', device: 'nvme0n1p1' },
        statistic: 'Average',
        period: Duration.minutes(5),
      }),
      threshold: 85,
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription:
        'Root volume above 85%. The 30 GiB gp3 holds image layers, Postgres ' +
        'data and a week of logs.',
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    diskFull.addAlarmAction(new cloudwatchActions.SnsAction(alarmTopic));

    Tags.of(this).add('project', 'veriforge');
    Tags.of(this).add('lifecycle', 'throwaway');
  }
}