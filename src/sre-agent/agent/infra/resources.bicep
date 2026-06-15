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

@description('Monthly SRE Agent unit cap for the resource.')
@minValue(1)
param monthlyAgentUnitLimit int = 10000

@description('Enable the newer SRE sandbox group feature.')
param enableSandboxGroup bool = true

@description('Enable newer workspace tool capabilities on the SRE Agent runtime.')
param enableWorkspaceTools bool = true

@description('Initial sponsor group ID used to initialize 2026 SRE Agent identity on first create. Leave empty for idempotent updates.')
param initialSponsorGroupId string = ''

@description('Create and attach a Microsoft.App/agentSpaces resource. Requires Agent Spaces to be enabled for the tenant/subscription.')
param enableAgentSpace bool = false

@description('Enable private endpoint-capable topology for SRE Agent dependencies.')
param enablePrivateEndpoints bool = true

@description('Address prefix reserved for the SRE Agent virtual network.')
param vnetAddressPrefix string = '10.42.0.0/16'

@description('Address prefix reserved for the SRE Agent private endpoint subnet.')
param privateEndpointSubnetPrefix string = '10.42.1.0/24'

@description('Existing Private DNS zone resource IDs keyed by service: keyVault, azureMonitor, logAnalyticsOms, logAnalyticsOds, azureMonitorAgentSvc. Empty values let child modules create zones when implemented.')
param privateDnsZoneResourceIds object = {
  keyVault: ''
  azureMonitor: ''
  logAnalyticsOms: ''
  logAnalyticsOds: ''
  azureMonitorAgentSvc: ''
}

@description('Link the SRE Agent VNet to existing Private DNS zones when privateDnsZoneResourceIds are provided.')
param linkExistingPrivateDnsZones bool = true

var uniqueSuffix = substring(uniqueString(resourceGroup().id, environmentName), 0, 8)
var agentName = 'sre-farsight-${uniqueSuffix}'
var agentSpaceName = 'space-sre-farsight-${uniqueSuffix}'
var logAnalyticsName = 'law-sre-farsight-${uniqueSuffix}'
var appInsightsName = 'appi-sre-farsight-${uniqueSuffix}'
var identityName = 'id-sre-farsight-${uniqueSuffix}'
var keyVaultName = 'kv-sre-farsight-${uniqueSuffix}'
var vnetName = 'vnet-sre-farsight-${uniqueSuffix}'
var normalizedPrivateDnsZoneResourceIds = union({
  keyVault: ''
  azureMonitor: ''
  logAnalyticsOms: ''
  logAnalyticsOds: ''
  azureMonitorAgentSvc: ''
}, privateDnsZoneResourceIds)
var privateNetworking = {
  enablePrivateEndpoints: enablePrivateEndpoints
  vnetAddressPrefix: vnetAddressPrefix
  privateEndpointSubnetPrefix: privateEndpointSubnetPrefix
  privateDnsZoneResourceIds: normalizedPrivateDnsZoneResourceIds
  linkExistingPrivateDnsZones: linkExistingPrivateDnsZones
}
module networking 'modules/networking.bicep' = if (enablePrivateEndpoints) {
  name: 'networking'
  params: {
    environmentName: environmentName
    location: location
    vnetName: vnetName
    vnetAddressPrefix: privateNetworking.vnetAddressPrefix
    privateEndpointSubnetPrefix: privateNetworking.privateEndpointSubnetPrefix
    privateDnsZoneResourceIds: privateNetworking.privateDnsZoneResourceIds
    linkExistingPrivateDnsZones: privateNetworking.linkExistingPrivateDnsZones
    tags: tags
  }
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    location: location
    logAnalyticsName: logAnalyticsName
    appInsightsName: appInsightsName
    tags: tags
    enablePrivateEndpoints: enablePrivateEndpoints
    privateEndpointSubnetId: enablePrivateEndpoints ? networking!.outputs.privateEndpointSubnetId : ''
    azureMonitorPrivateDnsZoneId: enablePrivateEndpoints ? networking!.outputs.privateDnsZoneResourceIds.azureMonitor : ''
    logAnalyticsOmsPrivateDnsZoneId: enablePrivateEndpoints ? networking!.outputs.privateDnsZoneResourceIds.logAnalyticsOms : ''
    logAnalyticsOdsPrivateDnsZoneId: enablePrivateEndpoints ? networking!.outputs.privateDnsZoneResourceIds.logAnalyticsOds : ''
    azureMonitorAgentSvcPrivateDnsZoneId: enablePrivateEndpoints ? networking!.outputs.privateDnsZoneResourceIds.azureMonitorAgentSvc : ''
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

// Microsoft.App/agents and Microsoft.App/agentSpaces do not expose private endpoint
// configuration in the 2026-01-01 Bicep schema, so private networking is applied only
// to supported dependency resources rather than adding invalid agent properties.
module keyVault 'modules/key-vault.bicep' = {
  name: 'key-vault'
  params: {
    location: location
    keyVaultName: keyVaultName
    agentIdentityPrincipalId: identity.outputs.identityPrincipalId
    principalId: principalId
    tags: tags
    enablePrivateEndpoints: enablePrivateEndpoints
    privateEndpointSubnetId: enablePrivateEndpoints ? networking!.outputs.privateEndpointSubnetId : ''
    privateDnsZoneId: enablePrivateEndpoints ? networking!.outputs.privateDnsZoneResourceIds.keyVault : ''
  }
}

module sreAgent 'modules/sre-agent.bicep' = {
  name: 'sre-agent'
  params: {
    location: location
    agentName: agentName
    agentSpaceId: enableAgentSpace ? agentSpace!.outputs.agentSpaceId : ''
    initialSponsorGroupId: enableAgentSpace ? initialSponsorGroupId : ''
    identityId: identity.outputs.identityId
    appInsightsAppId: monitoring.outputs.appInsightsAppId
    appInsightsId: monitoring.outputs.appInsightsId
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    managedResourceGroupId: resourceGroup().id
    principalId: principalId
    upgradeChannel: upgradeChannel
    defaultModelProvider: defaultModelProvider
    defaultModelName: defaultModelName
    monthlyAgentUnitLimit: monthlyAgentUnitLimit
    enableSandboxGroup: enableSandboxGroup
    enableWorkspaceTools: enableWorkspaceTools
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
output privateEndpointVnetId string = enablePrivateEndpoints ? networking!.outputs.vnetId : ''
output privateEndpointSubnetId string = enablePrivateEndpoints ? networking!.outputs.privateEndpointSubnetId : ''
output privateDnsZoneResourceIds object = enablePrivateEndpoints ? networking!.outputs.privateDnsZoneResourceIds : normalizedPrivateDnsZoneResourceIds
output keyVaultPrivateEndpointId string = keyVault.outputs.keyVaultPrivateEndpointId
output azureMonitorPrivateLinkScopeId string = monitoring.outputs.azureMonitorPrivateLinkScopeId
output azureMonitorPrivateEndpointId string = monitoring.outputs.azureMonitorPrivateEndpointId
