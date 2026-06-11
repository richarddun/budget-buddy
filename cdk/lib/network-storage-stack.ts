import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as efs from 'aws-cdk-lib/aws-efs';
import { Construct } from 'constructs';

/**
 * BudgetBuddyNetworkStorageStack — VPC + subnets + security groups + EFS
 *
 * Everything that needs to live in a VPC together. Merged into one stack
 * to avoid CDK cross-stack dependency cycles.
 *
 * Creates:
 *  - VPC with 2 private + 2 public subnets + 1 NAT gateway
 *  - Lambda security group (outbound HTTPS)
 *  - EFS filesystem (Regional, encrypted)
 *  - EFS access point at /budget-buddy (uid=99333)
 *  - EFS security group (inbound NFS 2049 from Lambda SG)
 *
 * Exports:
 *  - `vpc` — the VPC
 *  - `lambdaSecurityGroup` — SG for Lambda functions
 *  - `efsFilesystem` — EFS filesystem
 *  - `efsAccessPoint` — EFS access point
 */
export class BudgetBuddyNetworkStorageStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly lambdaSecurityGroup: ec2.SecurityGroup;
  public readonly efsFilesystem: efs.FileSystem;
  public readonly efsAccessPoint: efs.AccessPoint;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ═════════════════════════════════════════════════════════════
    // VPC
    // ═════════════════════════════════════════════════════════════
    this.vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr('10.0.0.0/16'),
      maxAzs: 2,
      natGateways: 1,           // Single NAT — cost optimization
      subnetConfiguration: [
        {
          name: 'Private',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24,
        },
        {
          name: 'Public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
      ],
      enableDnsHostnames: true,
      enableDnsSupport: true,
    });

    // ═════════════════════════════════════════════════════════════
    // Lambda security group
    // ═════════════════════════════════════════════════════════════
    this.lambdaSecurityGroup = new ec2.SecurityGroup(this, 'LambdaSecurityGroup', {
      vpc: this.vpc,
      description: 'Security group for budget-buddy Lambda functions',
      allowAllOutbound: true,   // Can reach OpenAI/Bedrock/YNAB APIs
    });

    // ═════════════════════════════════════════════════════════════
    // EFS security group
    // ═════════════════════════════════════════════════════════════
    const efsSecurityGroup = new ec2.SecurityGroup(this, 'EfsSecurityGroup', {
      vpc: this.vpc,
      description: 'Allow NFS (2049) from Lambda functions',
      allowAllOutbound: false,
    });

    efsSecurityGroup.addIngressRule(
      this.lambdaSecurityGroup,
      ec2.Port.tcp(2049),
      'Allow NFS from Lambda security group',
    );

    // ═════════════════════════════════════════════════════════════
    // EFS filesystem
    // ═════════════════════════════════════════════════════════════
    this.efsFilesystem = new efs.FileSystem(this, 'EfsFilesystem', {
      vpc: this.vpc,
      vpcSubnets: this.vpc.selectSubnets({
        subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
      }),
      securityGroup: efsSecurityGroup,
      lifecyclePolicy: efs.LifecyclePolicy.AFTER_30_DAYS,
      outOfInfrequentAccessPolicy: efs.OutOfInfrequentAccessPolicy.AFTER_1_ACCESS,
      encrypted: true,
      performanceMode: efs.PerformanceMode.GENERAL_PURPOSE,
      throughputMode: efs.ThroughputMode.BURSTING,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ═════════════════════════════════════════════════════════════
    // EFS access point
    // ═════════════════════════════════════════════════════════════
    this.efsAccessPoint = new efs.AccessPoint(this, 'EfsAccessPoint', {
      fileSystem: this.efsFilesystem,
      posixUser: { uid: '99333', gid: '99333' },
      path: '/budget-buddy',
      createAcl: {
        ownerUid: '99333',
        ownerGid: '99333',
        permissions: '0755',
      },
    });

    // ── Outputs ─────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'VpcId', { value: this.vpc.vpcId });
    new cdk.CfnOutput(this, 'LambdaSecurityGroupId', {
      value: this.lambdaSecurityGroup.securityGroupId,
    });
    new cdk.CfnOutput(this, 'EfsFilesystemId', {
      value: this.efsFilesystem.fileSystemId,
    });
    new cdk.CfnOutput(this, 'EfsAccessPointId', {
      value: this.efsAccessPoint.accessPointId,
    });
  }
}