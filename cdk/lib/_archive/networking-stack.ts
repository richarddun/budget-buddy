import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';


export interface NetworkingStackProps extends cdk.StackProps {
  /** CIDR block for the VPC (default: 10.0.0.0/16) */
  readonly vpcCidr?: string;
}

/**
 * BudgetBuddyNetworkingStack — VPC + subnets + security groups
 *
 * Creates a VPC with:
 *  - 2 private subnets (for Lambda functions + EFS mount targets)
 *  - 2 public subnets (for NAT gateway outbound traffic)
 *  - A NAT gateway (so Lambda can reach OpenAI/Bedrock/YNAB APIs)
 *  - Security group for Lambda functions
 *
 * Exports:
 *  - `vpc` — the VPC
 *  - `lambdaSecurityGroup` — SG allowing outbound HTTPS + EFS NFS inbound
 */
export class BudgetBuddyNetworkingStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly lambdaSecurityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: NetworkingStackProps) {
    super(scope, id);

    // ── VPC ─────────────────────────────────────────────────────
    this.vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr(props.vpcCidr ?? '10.0.0.0/16'),
      maxAzs: 2, // Two AZs for EFS mount target HA

      // Single NAT gateway (cost optimization — ~$32/mo otherwise)
      natGateways: 1,

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

      // Required by EFS
      enableDnsHostnames: true,
      enableDnsSupport: true,
    });

    // ── Security group for Lambda functions ──────────────────────
    // allowAllOutbound = true means Lambda can reach the internet
    // (through the NAT gateway) for API calls to OpenAI/Bedrock/YNAB.
    // EFS inbound is handled by the EFS security group in the storage stack.
    this.lambdaSecurityGroup = new ec2.SecurityGroup(this, 'LambdaSecurityGroup', {
      vpc: this.vpc,
      description: 'Security group for budget-buddy Lambda functions',
      allowAllOutbound: true,
    });

    // ── Tag everything ─────────────────────────────────────────
    cdk.Tags.of(this).add('project', 'budget-buddy');
    cdk.Tags.of(this).add('stack', 'networking');

    // ── Outputs ─────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'VpcId', {
      value: this.vpc.vpcId,
      description: 'VPC ID',
    });
    new cdk.CfnOutput(this, 'LambdaSecurityGroupId', {
      value: this.lambdaSecurityGroup.securityGroupId,
      description: 'Lambda Security Group ID',
    });
  }
}
