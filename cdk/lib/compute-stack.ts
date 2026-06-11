import * as cdk from 'aws-cdk-lib';
import * as apigw from 'aws-cdk-lib/aws-apigatewayv2';
import * as apigw_integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as efs from 'aws-cdk-lib/aws-efs';
import { Construct } from 'constructs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as path from 'path';

export interface ComputeStackProps extends cdk.StackProps {
  readonly vpc: ec2.Vpc;
  readonly lambdaSecurityGroup: ec2.SecurityGroup;
  readonly efsAccessPoint: efs.AccessPoint;
  readonly efsFilesystem: efs.FileSystem;
}

/**
 * BudgetBuddyCompute — Lambda functions + API Gateway
 *
 * Creates:
 *  - Python Lambda Layer (shared dependencies)
 *  - 6 Lambda functions (overview, commitments, transactions,
 *    categories, forecast, budget-targets)
 *  - API Gateway HTTP v2 (cheaper than REST) with routes
 *  - EFS mount on all Lambda functions (for SQLite)
 *
 * Each Lambda mounts the EFS access point at /mnt/efs and reads
 * the SQLite database directly using Python's built-in sqlite3.
 */
export class BudgetBuddyComputeStack extends cdk.Stack {
  public readonly apiEndpoint: string;
  public readonly overviewFunction: lambda.Function;

  constructor(scope: Construct, id: string, props: ComputeStackProps) {
    super(scope, id);

    // ── EFS mount configuration (shared by all Lambda functions) ─
    const efsMount = lambda.FileSystem.fromEfsAccessPoint(
      props.efsAccessPoint,
      '/mnt/efs',
    );

    // ── Lambda execution role (shared, with minimal permissions) ─
    const lambdaRole = new iam.Role(this, 'LambdaExecutionRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Execution role for budget-buddy Lambda functions',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          'service-role/AWSLambdaVPCAccessExecutionRole',
        ),
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          'service-role/AWSLambdaENIManagementAccess',
        ),
      ],
      inlinePolicies: {
        EfsAccess: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              actions: [
                'elasticfilesystem:ClientMount',
                'elasticfilesystem:ClientWrite',
                'elasticfilesystem:ClientRootAccess',
              ],
              resources: [props.efsFilesystem.fileSystemArn],
            }),
          ],
        }),
        SsmAccess: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              actions: ['ssm:GetParameter*', 'ssm:DescribeParameters'],
              resources: [
                `arn:aws:ssm:${cdk.Stack.of(this).region}:${cdk.Stack.of(this).account}:parameter/budget-buddy/*`,
              ],
            }),
          ],
        }),
      },
    });

    // ── Lambda Layer (shared Python dependencies) ───────────────
    // Currently minimal since core logic uses only stdlib.
    // Add pydantic, httpx, jinja2 here when needed (e.g. for AI agent).
    const sharedLayer = new lambda.LayerVersion(this, 'SharedLayer', {
      layerVersionName: 'budget-buddy-shared-deps',
      description: 'Shared Python dependencies for budget-buddy Lambda functions',
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
      compatibleArchitectures: [lambda.Architecture.ARM_64],
      code: lambda.Code.fromAsset(
        path.join(__dirname, '..', 'lambda', 'shared'),
      ),
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ── Helper: build a Lambda function with shared defaults ────
    const makeFunction = (opts: {
      id: string;
      functionName: string;
      description: string;
      handler: string;
      codePath: string;
      extraEnv?: Record<string, string>;
      memorySize?: number;
      timeout?: cdk.Duration;
    }): lambda.Function => {
      return new lambda.Function(this, opts.id, {
        runtime: lambda.Runtime.PYTHON_3_12,
        architecture: lambda.Architecture.ARM_64,
        role: lambdaRole,
        vpc: props.vpc,
        vpcSubnets: props.vpc.selectSubnets({
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
        }),
        securityGroups: [props.lambdaSecurityGroup],
        filesystem: efsMount,
        memorySize: opts.memorySize ?? 256,
        timeout: opts.timeout ?? cdk.Duration.seconds(29),
        functionName: opts.functionName,
        description: opts.description,
        handler: opts.handler,
        code: lambda.Code.fromAsset(
          path.join(__dirname, '..', 'lambda', opts.codePath),
        ),
        layers: [sharedLayer],
        environment: {
          DB_PATH: '/mnt/efs/localdb/budget.db',
          LOG_LEVEL: 'INFO',
          ...opts.extraEnv,
        },
      });
    };

    // ═════════════════════════════════════════════════════════════
    // LAMBDA: overview — computes digest (balance, safe-to-spend, cliff)
    // ═════════════════════════════════════════════════════════════
    this.overviewFunction = makeFunction({
      id: 'OverviewFunction',
      functionName: 'budget-buddy-overview',
      description: 'Compute overview digest (balance, safe-to-spend, next cliff)',
      handler: 'handler.handler',
      codePath: 'overview',
      extraEnv: { POWERTOOLS_SERVICE_NAME: 'budget-buddy-overview' },
    });

    // ═════════════════════════════════════════════════════════════
    // LAMBDA: commitments — CRUD for recurring bill tracking
    // ═════════════════════════════════════════════════════════════
    const commitmentsFunction = makeFunction({
      id: 'CommitmentsFunction',
      functionName: 'budget-buddy-commitments',
      description: 'CRUD operations on commitments table',
      handler: 'handler.handler',
      codePath: 'commitments',
    });

    // ═════════════════════════════════════════════════════════════
    // LAMBDA: transactions — CRUD for transaction history
    // ═════════════════════════════════════════════════════════════
    const transactionsFunction = makeFunction({
      id: 'TransactionsFunction',
      functionName: 'budget-buddy-transactions',
      description: 'CRUD operations on transactions table',
      handler: 'handler.handler',
      codePath: 'transactions',
    });

    // ═════════════════════════════════════════════════════════════
    // LAMBDA: forecast — calendar forecast engine + snapshot
    // ═════════════════════════════════════════════════════════════
    const forecastFunction = makeFunction({
      id: 'ForecastFunction',
      functionName: 'budget-buddy-forecast',
      description: 'Compute forecast calendar (balances, entries, min)',
      handler: 'handler.handler',
      codePath: 'forecast',
    });

    // ── API Gateway HTTP v2 ─────────────────────────────────────
    // HTTP API is ~$1/mo vs REST API at ~$3.50/mo.
    // It supports Lambda proxy, JWT auth, CORS, and custom domains.
    const httpApi = new apigw.HttpApi(this, 'HttpApi', {
      apiName: 'budget-buddy-api',
      description: 'Budget Buddy HTTP API (HTMX + JSON)',
      corsPreflight: {
        allowOrigins: ['*'],     // Tighten this when CloudFront is added
        allowMethods: [
          apigw.CorsHttpMethod.GET,
          apigw.CorsHttpMethod.POST,
          apigw.CorsHttpMethod.PUT,
          apigw.CorsHttpMethod.DELETE,
        ],
        allowHeaders: ['Content-Type', 'Authorization'],
        maxAge: cdk.Duration.days(1),
      },
    });

    // ── API Routes → Lambda integrations ────────────────────────

    // Overview
    const overviewIntegration = new apigw_integrations.HttpLambdaIntegration(
      'OverviewIntegration', this.overviewFunction,
    );
    httpApi.addRoutes({
      path: '/overview',
      methods: [apigw.HttpMethod.GET],
      integration: overviewIntegration,
    });

    // Digest (same Lambda, different path)
    httpApi.addRoutes({
      path: '/digest',
      methods: [apigw.HttpMethod.GET],
      integration: overviewIntegration,
    });

    // Commitments
    const commitmentsIntegration = new apigw_integrations.HttpLambdaIntegration(
      'CommitmentsIntegration', commitmentsFunction,
    );
    httpApi.addRoutes({
      path: '/commitments',
      methods: [apigw.HttpMethod.GET, apigw.HttpMethod.POST],
      integration: commitmentsIntegration,
    });
    httpApi.addRoutes({
      path: '/commitments/{id}',
      methods: [apigw.HttpMethod.GET, apigw.HttpMethod.PUT, apigw.HttpMethod.DELETE],
      integration: commitmentsIntegration,
    });

    // Transactions
    const txIntegration = new apigw_integrations.HttpLambdaIntegration(
      'TransactionsIntegration', transactionsFunction,
    );
    httpApi.addRoutes({
      path: '/transactions',
      methods: [apigw.HttpMethod.GET, apigw.HttpMethod.POST],
      integration: txIntegration,
    });
    httpApi.addRoutes({
      path: '/transactions/{id}',
      methods: [apigw.HttpMethod.DELETE],
      integration: txIntegration,
    });

    // Forecast
    const forecastIntegration = new apigw_integrations.HttpLambdaIntegration(
      'ForecastIntegration', forecastFunction,
    );
    httpApi.addRoutes({
      path: '/forecast',
      methods: [apigw.HttpMethod.GET],
      integration: forecastIntegration,
    });

    // ── Store the API URL as an output ──────────────────────────
    this.apiEndpoint = httpApi.apiEndpoint;

    // ── Outputs ─────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'ApiEndpoint', {
      value: httpApi.apiEndpoint,
      description: 'HTTP API endpoint URL',
    });
    new cdk.CfnOutput(this, 'OverviewFunctionName', {
      value: this.overviewFunction.functionName,
      description: 'Overview Lambda function name',
    });
    new cdk.CfnOutput(this, 'LambdaRoleArn', {
      value: lambdaRole.roleArn,
      description: 'Lambda execution role ARN',
    });
  }
}
