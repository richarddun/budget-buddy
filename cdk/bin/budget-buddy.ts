#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { BudgetBuddyNetworkStorageStack } from '../lib/network-storage-stack';
import { BudgetBuddyComputeStack } from '../lib/compute-stack';

const app = new cdk.App();

// Don't set env explicitly — CDK resolves from current AWS profile/region
// at deploy time. This avoids CrossRegionReferences errors during synth.

// ─── Stack 1: VPC + EFS ────────────────────────────────────────
const infra = new BudgetBuddyNetworkStorageStack(app, 'BudgetBuddyInfra', {
  description: 'VPC + EFS for budget-buddy Lambda functions',
});

// ─── Stack 2: Lambda functions + API Gateway ────────────────────
new BudgetBuddyComputeStack(app, 'BudgetBuddyCompute', {
  description: 'Lambda functions + API Gateway for budget-buddy',
  vpc: infra.vpc,
  lambdaSecurityGroup: infra.lambdaSecurityGroup,
  efsAccessPoint: infra.efsAccessPoint,
  efsFilesystem: infra.efsFilesystem,
});

app.synth();