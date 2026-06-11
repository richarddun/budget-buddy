import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as efs from 'aws-cdk-lib/aws-efs';
import { Construct } from 'constructs';


export interface StorageStackProps extends cdk.StackProps {
  readonly vpc: ec2.Vpc;
  readonly appSecurityGroup: ec2.SecurityGroup;
}

/**
 * BudgetBuddyStorage — EFS filesystem for persistent SQLite storage
 *
 * Creates:
 *  - EFS Regional filesystem (standard, multi-AZ)
 *  - Access point at /budget-buddy with POSIX user mapping (uid=99333)
 *  - Mount targets in private subnets
 *  - Security group allowing NFS (2049) from Lambda functions
 *  - Lifecycle policy to move cold data to IA storage
 *
 * Cost: ~$0.01/mo for a 10MB SQLite database
 */
export class BudgetBuddyStorageStack extends cdk.Stack {
  public readonly efsFilesystem: efs.FileSystem;
  public readonly efsAccessPoint: efs.AccessPoint;
  public readonly efsMountTargetsSecurityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: StorageStackProps) {
    super(scope, id);

    // How to use EFS with Lambda in CDK:
    //
    // 1. Create EFS file system (this stack)
    // 2. Create an access point with POSIX user mapping
    // 3. In the Lambda stack, mount via:
    //      lambda.FileSystem.fromEfsAccessPoint(accessPoint, '/mnt/efs')
    // 4. Lambda adds filesystem config: EFS access point + mount path
    // 5. Lambda connects to EFS mount target through the VPC
    //
    // The SQLite database lives at /mnt/efs/localdb/budget.db
    // No data migration — copy your existing localdb/budget.db there.

    // ── Security group for EFS mount targets ────────────────────
    this.efsMountTargetsSecurityGroup = new ec2.SecurityGroup(this, 'EfsSecurityGroup', {
      vpc: props.vpc,
      description: 'Allow NFS (2049) from Lambda functions',
      allowAllOutbound: false,
    });

    this.efsMountTargetsSecurityGroup.addIngressRule(
      props.appSecurityGroup,
      ec2.Port.tcp(2049),
      'Allow NFS from Lambda security group',
    );

    // ── EFS filesystem (Regional — standard, multi-AZ) ──────────
    // One Zone (~50% cheaper) is available via `oneZone: true`
    // but for a 10MB DB the savings are ~$0.001/mo — not worth the
    // single-AZ risk. Stick with Regional for simplicity.
    this.efsFilesystem = new efs.FileSystem(this, 'EfsFilesystem', {
      vpc: props.vpc,

      // Mount targets go into the private subnets
      vpcSubnets: props.vpc.selectSubnets({
        subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
      }),

      securityGroup: this.efsMountTargetsSecurityGroup,

      // Lifecycle: move to IA after 30 days of no access
      lifecyclePolicy: efs.LifecyclePolicy.AFTER_30_DAYS,
      outOfInfrequentAccessPolicy: efs.OutOfInfrequentAccessPolicy.AFTER_1_ACCESS,

      // Encrypted at rest (AWS managed key = free)
      encrypted: true,

      // Burstable is fine for our IO pattern
      performanceMode: efs.PerformanceMode.GENERAL_PURPOSE,
      throughputMode: efs.ThroughputMode.BURSTING,

      // Destroy on stack deletion (no orphaned EFS)
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ── EFS Access Point ────────────────────────────────────────
    // Lambda mounts this specific path. POSIX user is mapped so
    // sqlite3 can read/write the database without permission errors.
    this.efsAccessPoint = new efs.AccessPoint(this, 'EfsAccessPoint', {
      fileSystem: this.efsFilesystem,

      // Lambda's default execution user is 99333
      posixUser: { uid: '99333', gid: '99333' },

      // Root path inside the access point
      path: '/budget-buddy',
      createAcl: {
        ownerUid: '99333',
        ownerGid: '99333',
        permissions: '0755',
      },
    });

    // ── Outputs ─────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'EfsFilesystemId', {
      value: this.efsFilesystem.fileSystemId,
      description: 'EFS Filesystem ID',
    });
    new cdk.CfnOutput(this, 'EfsAccessPointId', {
      value: this.efsAccessPoint.accessPointId,
      description: 'EFS Access Point ID',
    });
  }
}