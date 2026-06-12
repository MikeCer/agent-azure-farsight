// ============================================================
// Resources Bicep - Resource Group Orchestrator
// Deploys new SRE Agent resources into the calling resource group.
// ============================================================

@description('Environment name used for unique resource naming.')
param environmentName string

@description('Azure region for all resources.')
param location string

@description('Tags applied to all resources.')
param tags object

@description('Object ID of the deploying user. Receives SRE Agent Administrator role. Leave empty to skip.')
param principalId string = ''

@description('SRE Agent runtime upgrade channel.')
@allowed(['Stable', 'Preview'])
param upgradeChannel string = 'Stable'

@description('Default model provider for the SRE Agent runtime.')
@allowed(['Anthropic', 'MicrosoftFoundry'])
param defaultModelProvider string = 'Anthropic'

@description('Default model name for the SRE Agent runtime.')
param defaultModelName string = 'Automatic'

@description('Initial sponsor group ID used to initialize 2026 SRE Agent identity. Falls back to principalId when omitted.')
param initialSponsorGroupId string = ''

@description('Create and attach a Microsoft.App/agentSpaces resource. Requires Agent Spaces to be enabled for the tenant/subscription.')
param enableAgentSpace bool = false

var uniqueSuffix = substring(uniqueString(resourceGroup().id, environmentName), 0, 8)
var agentName = 'sre-farsight-${uniqueSuffix}'
var agentSpaceName = 'space-sre-farsight-${uniqueSuffix}'
var logAnalyticsName = 'law-sre-farsight-${uniqueSuffix}'
var appInsightsName = 'appi-sre-farsight-${uniqueSuffix}'
var identityName = 'id-sre-farsight-${uniqueSuffix}'
var keyVaultName = 'kv-sre-farsight-${uniqueSuffix}'

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    location: location
    logAnalyticsName: logAnalyticsName
    appInsightsName: appInsightsName
    tags: tags
  }
}

module identity 'modules/identity.bicep' = {
  name: 'identity'
  params: {
    location: location
    identityName: identityName
    tags: tags
  }
}

module agentSpace 'modules/agent-space.bicep' = if (enableAgentSpace) {
  name: 'agent-space'
  params: {
    location: location
    agentSpaceName: agentSpaceName
    tags: tags
  }
}

module keyVault 'modules/key-vault.bicep' = {
  name: 'key-vault'
  params: {
    location: location
    keyVaultName: keyVaultName
    agentIdentityPrincipalId: identity.outputs.identityPrincipalId
    principalId: principalId
    tags: tags
  }
}

module sreAgent 'modules/sre-agent.bicep' = {
  name: 'sre-agent'
  params: {
    location: location
    agentName: agentName
    agentSpaceId: enableAgentSpace ? agentSpace!.outputs.agentSpaceId : ''
    initialSponsorGroupId: enableAgentSpace ? (empty(initialSponsorGroupId) ? principalId : initialSponsorGroupId) : ''
    identityId: identity.outputs.identityId
    appInsightsAppId: monitoring.outputs.appInsightsAppId
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    appInsightsId: monitoring.outputs.appInsightsId
    managedResourceGroupId: resourceGroup().id
    principalId: principalId
    upgradeChannel: upgradeChannel
    defaultModelProvider: defaultModelProvider
    defaultModelName: defaultModelName
    tags: tags
  }
}

output agentName string = sreAgent.outputs.agentName
output agentEndpoint string = sreAgent.outputs.agentEndpoint
output agentPortalUrl string = sreAgent.outputs.agentPortalUrl
output agentPrincipalId string = sreAgent.outputs.agentPrincipalId
output logAnalyticsWorkspaceId string = monitoring.outputs.logAnalyticsWorkspaceId
output appInsightsAppId string = monitoring.outputs.appInsightsAppId
output identityPrincipalId string = identity.outputs.identityPrincipalId
output keyVaultName string = keyVault.outputs.keyVaultName
output keyVaultUri string = keyVault.outputs.keyVaultUri
output agentSpaceId string = enableAgentSpace ? agentSpace!.outputs.agentSpaceId : ''
